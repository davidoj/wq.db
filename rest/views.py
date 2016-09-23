from rest_framework.generics import GenericAPIView as RestGenericAPIView
from rest_framework.response import Response
from rest_framework.decorators import detail_route
from rest_framework import status, viewsets
from .model_tools import get_ct, get_object_id, get_by_identifier
from django.db.models.fields import FieldDoesNotExist


class GenericAPIView(RestGenericAPIView):
    router = None
    ignore_kwargs = []

    @property
    def template_name(self):
        """
        Infer template name from view/viewset name
        """
        name = type(self).__name__
        name = name.replace('ViewSet', '')
        name = name.replace('View', '')
        return name.lower() + '.html'

    @property
    def depth(self):
        return 0

    def get_template_names(self):
        return [self.template_name]

    def get_queryset(self):
        if self.router is not None and self.model is not None:
            return self.router.get_queryset_for_model(self.model, self.request)
        return super(GenericAPIView, self).get_queryset()

    def get_serializer_class(self):
        if self.router is not None and self.model is not None:
            return self.router.get_serializer_for_model(self.model, self.depth)
        return super(GenericAPIView, self).get_serializer_class()


class SimpleView(GenericAPIView):
    def get(self, request, *args, **kwargs):
        return Response({})


class SimpleViewSet(viewsets.ViewSet, GenericAPIView):
    def list(self, request, *args, **kwargs):
        return Response({})


class ModelViewSet(viewsets.ModelViewSet, GenericAPIView):
    target = None

    @property
    def template_name(self):
        basename = get_ct(self.model).identifier
        if self.action in ('retrieve', 'create', 'update', 'delete'):
            suffix = 'detail'
        else:
            suffix = self.action
        return "%s_%s.html" % (basename, suffix)

    @property
    def depth(self):
        if self.action in ('retrieve', 'edit'):
            return 1
        else:
            return 0

    @detail_route()
    def edit(self, request, *args, **kwargs):
        """
        Generates a context appropriate for editing a form
        """
        response = self.retrieve(request, *args, **kwargs)
        self.add_lookups(response.data)
        return response

    def new(self, request):
        """
        new is a variant of the "edit" action, but with no existing model
        to lookup.
        """
        self.action = 'edit'
        init = request.GET.dict()
        for arg in self.ignore_kwargs:
            init.pop(arg, None)
        for key in list(init.keys()):
            try:
                field = self.model._meta.get_field(key)
            except FieldDoesNotExist:
                del init[key]
            else:
                if field.rel:
                    fk_model = field.rel.to
                    try:
                        obj = get_by_identifier(fk_model.objects, init[key])
                    except fk_model.DoesNotExist:
                        del init[key]
                    else:
                        init[key] = obj.pk

        obj = self.model(**init)
        serializer = self.get_serializer(obj)
        data = serializer.data
        self.add_lookups(data)
        return Response(data)

    def retrieve(self, request, *args, **kwargs):
        """
        Custom retrieve watches for "new" lookup value and switches modes
        accordingly
        """
        if hasattr(self, 'lookup_url_kwarg'):
            # New in DRF 2.4?
            lookup = self.lookup_url_kwarg or self.lookup_field
        else:
            lookup = self.lookup_field

        if self.kwargs.get(lookup, "") == "new":
            # new/edit mode
            return self.new(request)
        else:
            # Normal detail view
            return super(ModelViewSet, self).retrieve(request, *args, **kwargs)

    def add_lookups(self, context):
        # Mimic _addLookups in wq.app/app.js
        context['edit'] = True

        if not self.router:
            return

        ct = get_ct(self.model)
        conf = ct.get_config()

        for field in conf['form']:
            if 'choices' in field:
                # CharField choices
                context[field['name'] + '_choices'] = [{
                    'name': choice['name'],
                    'label': choice['label'],
                    'selected': (
                        choice['name'] == context.get(field['name'], '')
                    ),
                } for choice in field['choices']]

            elif 'wq:ForeignKey' in field:
                choices = self.get_lookup_choices(field, context)
                if choices:
                    context[field['name'] + '_list'] = choices

    def get_lookup_choices(self, field, context):
        model_name = field['wq:ForeignKey']
        model_conf = self.router.get_model_config(field['wq:ForeignKey'])
        if not model_conf:
            return

        qs = self.router.get_queryset_for_model(model_name)
        if field.get('filter', None):
            qs = qs.filter(**self.compute_filter(
                field['filter'],
                model_conf,
                context
            ))
        choices = self.serialize_choices(qs, field)
        self.set_selected(choices, context.get(field['name'] + '_id', ''))
        return choices

    def compute_filter(self, filter, model_conf, context):
        def render(value):
            import pystache
            result = pystache.render(value, context)
            if result.isdigit():
                result = int(result)
            return result

        fk_lookups = {}
        for field in model_conf['form']:
            if 'wq:ForeignKey' not in field:
                continue
            lookup = self.router.get_lookup_for_model(
                field['wq:ForeignKey']
            )
            if lookup and lookup != 'pk':
                fk_lookups['%s_id' % field['name']] = '%s__%s' % (
                    field['name'], lookup
                )

        computed_filter = {}
        for key, values in filter.items():
            if not isinstance(values, list):
                values = [values]
            values = [
                render(value) if '{{' in value else value
                for value in values
            ]

            if key in fk_lookups:
                key = fk_lookups[key]

            if len(values) > 1:
                computed_filter[key + '__in'] = values
            else:
                computed_filter[key] = values[0]

        return computed_filter

    def serialize_choices(self, qs, field):
        return [{
            'id': get_object_id(obj),
            'label': str(obj)
        } for obj in qs]

    def set_selected(self, choices, value):
        for choice in choices:
            if choice['id'] == value:
                choice['selected'] = True

    def list(self, request, *args, **kwargs):
        response = super(ModelViewSet, self).list(
            request, *args, **kwargs
        )
        if not isinstance(response.data, dict):
            return response

        if self.target:
            response.data['target'] = self.target
        ct = get_ct(self.model)
        for pct, fields in ct.get_foreign_keys().items():
            if len(fields) == 1:
                self.get_parent(pct, fields[0], response)
        return response

    def create(self, request, *args, **kwargs):
        response = super(ModelViewSet, self).create(
            request, *args, **kwargs
        )
        if not request.accepted_media_type.startswith('text/html'):
            # JSON request, assume client will handle redirect
            return response

        # HTML request, probably a form post from an older browser
        if response.status_code == status.HTTP_201_CREATED:
            return self.postsave(request, response)
        else:
            return self.saveerror(request, response)

    def update(self, request, *args, **kwargs):
        response = super(ModelViewSet, self).update(
            request, *args, **kwargs
        )
        if not request.accepted_media_type.startswith('text/html'):
            # JSON request, assume client will handle redirect
            return response

        # HTML request, probably a form post from an older browser
        if response.status_code == status.HTTP_200_OK:
            return self.postsave(request, response)
        else:
            return self.saveerror(request, response)

    def postsave(self, request, response):
        ct = get_ct(self.model)
        conf = ct.get_config(request.user)

        # Redirect to new page
        postsave = conf.get('postsave', ct.identifier + '_detail')
        if '_' in postsave:
            page, mode = postsave.split('_')
        else:
            page = postsave
            mode = 'detail'

        oid = ""
        if page != ct.identifier and self.router:
            # Optional: return to detail view of a parent model
            pconf = self.router.get_page_config(page)
            if pconf.get('list', None) and mode != "list":
                oid = response.data.get(page + '_id', None)
        else:
            # Default: return to detail view of the saved model
            pconf = conf
            if mode != "list":
                oid = response.data['id']

        url = "/" + pconf['url']
        if pconf['url'] and pconf.get('list', None):
            url += "/"
        if oid:
            url += str(oid)
            if mode == "edit":
                url += "/edit"

        return Response(
            {'detail': 'Created'},
            status=status.HTTP_302_FOUND,
            headers={'Location': url}
        )

    def saverror(self, request, response):
        errors = [{
            'field': key,
            'errors': val
        } for key, val in response.data.items()]
        template = get_ct(self.model).identifier + '_error.html'
        return Response(
            {
                'errors': errors,
                'post': request.DATA
            },
            status=response.status_code,
            template_name=template
        )

    def get_parent(self, ct, kwarg_name, response):
        pid = self.kwargs.get(kwarg_name, None)
        if not pid:
            return

        pcls = ct.model_class()
        if self.router:
            slug = self.router.get_lookup_for_model(pcls)
            parent = pcls.objects.get(**{slug: pid})
        else:
            parent = get_by_identifier(pcls.objects, pid)
        if ct.urlbase == '':
            urlbase = ''
        else:
            urlbase = ct.urlbase + '/'
        objid = get_object_id(parent)
        response.data['parent_label'] = str(parent)
        response.data['parent_id'] = objid
        response.data['parent_url'] = '%s%s' % (urlbase, objid)
        response.data['parent_is_' + ct.identifier] = True
        response.data['parent_page'] = ct.identifier
        response.data['page_config'] = get_ct(self.model).get_config()
        if self.router:
            response.data['parent'] = self.router.serialize(parent)
        return parent
