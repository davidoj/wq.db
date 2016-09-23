from wq.db import rest
from .models import (
    RootModel, UserManagedModel, Parent, Child, ItemType, Item, GeometryModel,
    SlugModel, SlugRefParent, SlugRefChild,
    DateModel, ChoiceModel, TranslatedModel,
)
from .serializers import (
    RootModelSerializer, ParentSerializer, ItemSerializer,
    SlugRefChildSerializer,
)

rest.router.register_model(
    RootModel,
    url="",
    lookup="slug",
    serializer=RootModelSerializer,
)
rest.router.register_model(UserManagedModel)
rest.router.register_model(Parent, serializer=ParentSerializer)
rest.router.register_model(Child, per_page=100, url="children")
rest.router.register_model(ItemType)
rest.router.register_model(Item, serializer=ItemSerializer)
rest.router.register_model(GeometryModel)
rest.router.register_model(SlugModel, lookup="code")
rest.router.register_model(SlugRefParent)
rest.router.register_model(
    SlugRefChild,
    url="slugrefchildren",
    serializer=SlugRefChildSerializer,
)
rest.router.register_model(DateModel)
rest.router.register_model(ChoiceModel)
rest.router.register_model(TranslatedModel)
rest.router.set_extra_config(debug=True)

rest.router.add_page("rest_context", {})
rest.router.add_page("auth_context", {})
