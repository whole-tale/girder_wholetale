import pathlib
from urllib.parse import urlparse

from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.setting import Setting
from ...constants import PluginSettings
from ..data_map import DataMap
from ..entity import Entity
from ..bdbag.bdbag_provider import BDBagProvider


class DerivaProvider(BDBagProvider):
    def __init__(self) -> None:
        super().__init__('DERIVA')

    def matches(self, entity: Entity) -> bool:
        deriva_urls = Setting().get(PluginSettings.DERIVA_EXPORT_URLS)
        ent_val = str(entity.getValue())
        for url in deriva_urls:
            if ent_val.startswith(url):
                return True
        return False

    def lookup(self, entity: Entity) -> DataMap:
        sz = -1
        if 'size' in entity:
            sz = entity['size']
        name = pathlib.Path(urlparse(entity.getValue()).path).with_suffix('').name
        if 'name' in entity:
            name = entity['name']
        return DataMap(entity.getValue(), size=sz, repository='DERIVA', name=name)

    def getDatasetUID(self, doc: object, user: object) -> str:
        if "folderId" in doc:
            path_to_root = Item().parentsToRoot(doc, user=user)
        else:
            path_to_root = Folder().parentsToRoot(doc, user=user)
        # Collection{WT Catalog} / Folder{WT Catalog} / Folder{Deriva ds root}
        if len(path_to_root) == 2:
            return doc["meta"]["identifier"]
        return path_to_root[2]["object"]["meta"]["identifier"]
