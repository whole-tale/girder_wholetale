import textwrap

from girder import logger
from girder.utility.model_importer import ModelImporter

from .entity import Entity
from .data_map import DataMap
from .file_map import FileMap
from .import_item import ImportItem


class ImportProvider:
    _regex = None

    def __init__(self, name):
        self.name = name
        self.folderModel = ModelImporter.model('folder')
        self.itemModel = ModelImporter.model('item')
        self.fileModel = ModelImporter.model('file')

    @property
    def regex(self):
        """Regular expression used to determine if provider matches url"""
        if not self._regex:
            self._regex = self.create_regex()
        if not isinstance(self._regex, list):
            self._regex = [self._regex]
        return self._regex

    def create_regex(self):
        """Create and initialize regular expression used for matching"""
        raise NotImplementedError()

    def getName(self) -> str:
        return self.name

    def matches(self, entity: Entity) -> bool:
        return any(regex.match(entity.getValue()) for regex in self.regex)

    def lookup(self, entity: Entity) -> DataMap:
        raise NotImplementedError()

    def listFiles(self, entity: Entity) -> FileMap:
        raise NotImplementedError()

    def getDatasetUID(self, doc: object, user: object) -> str:
        """Given a registered object, return dataset DOI"""
        raise NotImplementedError()

    def getURI(self, doc: object, user: object) -> str:
        """Given a registered object, return a URI for it"""
        raise NotImplementedError()

    def import_tale(self, dataId: str, user: object, force=False) -> object:
        """Given a dataId import dataset as Tale"""
        raise NotImplementedError()

    def proto_tale_from_datamap(self, dataMap: DataMap, user: object, asTale: bool) -> object:
        if asTale:
            relation = "IsDerivedFrom"
        else:
            relation = "Cites"

        related_id = [
            {
                "relation": relation,
                "identifier": dataMap.doi or dataMap.dataId
            }
        ]

        long_name = dataMap.name
        long_name = long_name.replace('-', ' ').replace('_', ' ')
        shortened_name = textwrap.shorten(text=long_name, width=30)
        return {
            "relatedIdentifiers": related_id,
            "title": f"A Tale for \"{shortened_name}\"",
            "category": "science",
        }

    def register(self, parent: object, parentType: str, progress, user, dataMap: DataMap,
                 base_url: str = None):
        stack = [(parent, parentType)]
        pid = dataMap.dataId
        name = dataMap.name
        rootObj = None
        rootType = None

        for item in self._listRecursive(user, pid, name, base_url, progress=progress):
            if item.type == ImportItem.FOLDER:
                (obj, objType) = self._registerFolder(stack, item, user)
            elif item.type == ImportItem.END_FOLDER:
                stack.pop()
            elif item.type == ImportItem.FILE:
                (obj, objType) = self._registerFile(stack, item, user)
            else:
                raise Exception('Unknown import item type: %s' % item.type)
            if rootObj is None:
                rootObj = obj
                rootType = objType

        return rootType, rootObj

    def _registerFolder(self, stack, item: ImportItem, user):
        (parent, parentType) = stack[-1]
        folder = self.folderModel.createFolder(parent, item.name, description='',
                                               parentType=parentType, creator=user,
                                               reuseExisting=True)
        meta = {
            "identifier": item.identifier,
            "provider": self.name,
        }
        if item.meta:
            meta.update(item.meta)
        folder = self.folderModel.setMetadata(folder, meta)
        stack.append((folder, 'folder'))
        return (folder, 'folder')

    def _registerFile(self, stack, item: ImportItem, user):
        (parent, parentType) = stack[-1]
        gitem = self.itemModel.createItem(item.name, user, parent, reuseExisting=True)
        if self.fileModel.findOne({"itemId": gitem["_id"]}):
            logger.info(f"Item ({gitem['_id']=}, {gitem['name']=}) already has a file.")
            return (gitem, 'item')
        meta = {'provider': self.name}
        if item.identifier:
            meta['identifier'] = item.identifier
        if item.meta:
            meta.update(item.meta)
        gitem = self.itemModel.setMetadata(gitem, meta)

        if item.url and item.url.startswith('file://'):
            with open(item.url[len('file://'):], 'rb') as f:
                ModelImporter.model('upload').uploadFromFile(f, item.size, item.name, parent=gitem,
                                                             parentType='item', user=user,
                                                             mimeType=item.mimeType)
        else:
            # girder does not allow anything else than http and https. So we need a better
            # mechanism here to communicate relevant information to WTDM
            self.fileModel.createLinkFile(item.name, url=item.url, parent=gitem, parentType='item',
                                          creator=user, size=item.size, mimeType=item.mimeType,
                                          reuseExisting=True)
        return (gitem, 'item')

    def _listRecursive(self, user, pid: str, name: str, base_url: str = None, progress=None):
        raise NotImplementedError()

    def check_auth(self, user):
        pass


class ImportProviders:
    def __init__(self):
        self.providers = []
        self.providerMap = {}

    def addProvider(self, provider: ImportProvider):
        self.providers.append(provider)
        self.providerMap[provider.name] = provider

    def getProvider(self, entity: Entity) -> ImportProvider:
        for provider in self.providers:
            if provider.matches(entity):
                return provider
        raise Exception('Could not find suitable provider for entity %s' % entity)

    def getFromDataMap(self, dataMap: DataMap) -> ImportProvider:
        return self.providerMap[dataMap.repository]
