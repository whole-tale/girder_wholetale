from ..data_map import DataMap
from ..entity import Entity
from ..bdbag.bdbag_provider import BDBagProvider


class DerivaProvider(BDBagProvider):
    def __init__(self) -> None:
        super().__init__('DERIVA')

    def matches(self, entity: Entity) -> bool:
        try:
            return entity.getValue().startswith('https://pbcconsortium.s3.amazonaws.com/')
        except:
            return False

    def lookup(self, entity: Entity) -> DataMap:
        sz = -1
        if 'size' in entity:
            sz = entity['size']
        name = None
        if 'name' in entity:
            name = entity['name']
        return DataMap(entity.getValue(), size=sz, repository='DERIVA', name=name)
