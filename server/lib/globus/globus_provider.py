import os
import re
from typing import Tuple
from urllib.parse import urlparse
import requests

from girder.models.item import Item
from girder.models.folder import Folder

from plugins.wholetale.server.lib.file_map import FileMap
from ..import_providers import ImportProvider
from ..entity import Entity
from ..data_map import DataMap
from ..import_item import ImportItem
from ...utils import deep_get

from girder.plugins.globus_handler.clients import Clients


TRANSFER_URL_PREFIX_REGEX = re.compile('^https://app.globus.org/file-manager')


class GlobusImportProvider(ImportProvider):
    def __init__(self):
        super().__init__('Globus')
        self.index_id = "1a57bbe5-5272-477f-9d31-343b8258b7a5"
        self.clients = Clients()

    def create_regex(self):
        return re.compile(r'^https://.*petrel.*/mdf/detail.*')

    def lookup(self, entity: Entity) -> DataMap:
        endpoint, path, doi, title = self._extractMeta(entity.getValue())
        # Don't compute size here. The recursive traversal of typical directory structures
        # in a datase takes ages and we want the lookup method to quickly identify whether
        # a repository has a dataset or not.
        # tc = self.clients.getUserTransferClient(entity.getUser())
        # size = self._computeSize(tc, endpoint, path, entity.getUser())
        size = -1
        return DataMap(entity.getValue(), size, doi=doi, name=title, repository=self.getName())

    def _extractMeta(self, raw_url) -> Tuple[str, str, str, str]:
        url = urlparse(raw_url)
        if not url.path.startswith('/mdf/detail'):
            raise Exception("Not an MDF resource page")

        globus_id = url.path[11:].strip("/")  # There's no other way...
        headers = {"Content-Type": "application/json"}
        data = {
            "@datatype": "GSearchRequest",
            "q": '"{}"'.format(globus_id),
            "advanced": False,
        }
        req = requests.post(
            f"https://search.api.globus.org/v1/index/{self.index_id}/search",
            json=data,
            headers=headers
        )
        req.raise_for_status()
        globus_meta = req.json()
        if globus_meta['count'] != 1:
            raise Exception("Found %i results for '%s'" % (globus_meta['count'], globus_id))
        meta_prefix = "gmeta.0.entries.0.content"
        globus_uri = deep_get(globus_meta, f"{meta_prefix}.data.endpoint_path")
        globus_url = urlparse(globus_uri)
        identifier = deep_get(globus_meta, f"{meta_prefix}.dc.identifier.identifier")
        identifier_type = deep_get(globus_meta, f"{meta_prefix}.dc.identifier.identifierType")
        doi = f"{identifier_type.lower()}:{identifier}"
        title = deep_get(globus_meta, f"{meta_prefix}.dc.titles.0.title")
        return globus_url.netloc, globus_url.path, doi, title

    def _computeSize(self, tc, endpoint, path, user):
        sz = 0
        for item in self._listRecursive2(tc, endpoint, path):
            if item.type == ImportItem.FILE:
                sz += item.size
        return sz

    def listFiles(self, entity: Entity) -> FileMap:
        stack = []
        top = None
        for item in self._listRecursive(entity.getUser(), entity.getValue(), None):
            if item.type == ImportItem.FOLDER:
                if len(stack) == 0:
                    fm = FileMap(item.name)
                else:
                    fm = stack[-1].addChild(item.name)
                stack.append(fm)
            elif item.type == ImportItem.END_FOLDER:
                top = stack.pop()
            elif item.type == ImportItem.FILE:
                stack[-1].addFile(item.name, item.size)
        return top

    def _listRecursive(self, user, pid: str, name: str, base_url: str = None, progress=None):
        endpoint, path, doi, title = self._extractMeta(pid)
        yield ImportItem(ImportItem.FOLDER, name=title, identifier='doi:' + doi)
        tc = self.clients.getUserTransferClient(user)
        yield from self._listRecursive2(tc, endpoint, path, progress)
        yield ImportItem(ImportItem.END_FOLDER)

    def _listRecursive2(self, tc, endpoint: str, path: str, progress=None):
        if path[-1] != '/':
            path = path + '/'
        if progress:
            progress.update(increment=1, message='Listing files')
        for entry in tc.operation_ls(endpoint, path=path):
            if entry['type'] == 'dir':
                yield ImportItem(ImportItem.FOLDER, name=entry['name'])
                yield from self._listRecursive2(tc, endpoint, path + entry['name'], progress)
                yield ImportItem(ImportItem.END_FOLDER)
            elif entry['type'] == 'file':
                yield ImportItem(
                    ImportItem.FILE, entry['name'], size=entry['size'],
                    mimeType='application/octet-stream',
                    url='globus://%s/%s%s' % (endpoint, path, entry['name']))

    def getDatasetUID(self, doc, user):
        try:
            identifier = doc['meta']['identifier']  # if root of ds, it should have it
        except (KeyError, TypeError):
            if 'folderId' in doc:
                path_to_root = Item().parentsToRoot(doc, user=user)
            else:
                path_to_root = Folder().parentsToRoot(doc, user=user)
            # Collection{WT Catalog} / Folder{WT Catalog} / Folder{Globus ds root}
            identifier = path_to_root[2]['object']['meta']['identifier']
        return identifier

    def getURI(self, doc, user):
        if 'folderId' in doc:
            fileObj = Item().childFiles(doc)[0]
            return fileObj['linkUrl']
        else:
            path_to_root = Folder().parentsToRoot(doc, user=user)
            root_folder = path_to_root[2]
            # There's always 'globus_metadata.json'...
            item = Folder().childItems(root_folder['object'], user=user)[0]
            fileObj = Item().childFiles(item)[0]
            root_path = os.path.dirname(fileObj['linkUrl'])
            for path in path_to_root[3:]:
                root_path = os.path.join(root_path, path['object']['name'])
            return os.path.join(root_path, doc['name'])
