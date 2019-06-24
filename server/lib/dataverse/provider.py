import json
import re
import os
import pathlib
from urllib.parse import urlparse, urlunparse, parse_qs
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from girder import events, logger
from girder.constants import AccessType
from girder.models.folder import Folder
from girder.models.setting import Setting

from ..import_providers import ImportProvider
from ..data_map import DataMap
from ..file_map import FileMap
from ..import_item import ImportItem
from ..entity import Entity
from ... import constants

_DOI_REGEX = re.compile(r'(10.\d{4,9}/[-._;()/:A-Z0-9]+)', re.IGNORECASE)
_QUOTES_REGEX = re.compile(r'"(.*)"')
_CNTDISP_REGEX = re.compile(r'filename="(.*)"')


def _query_dataverse(search_url):
    resp = urlopen(search_url).read()
    data = json.loads(resp.decode('utf-8'))['data']
    if data['count_in_response'] != 1:
        raise ValueError
    item = data['items'][0]
    files = [{
        'filename': item['name'],
        'mimeType': item['file_content_type'],
        'filesize': item['size_in_bytes'],
        'id': item['file_id'],
        'doi': item.get('filePersistentId')  # https://github.com/IQSS/dataverse/issues/5339
    }]
    title = item['name']
    title_search = _QUOTES_REGEX.search(item['dataset_citation'])
    if title_search is not None:
        title = title_search.group().strip('"')
    doi = None
    doi_search = _DOI_REGEX.search(item['dataset_citation'])
    if doi_search is not None:
        doi = doi_search.group()
    return title, files, doi


def _get_attrs_via_head(obj, url):
    name = obj['filename']
    size = obj['filesize']
    try:
        req = Request(url)
        req.get_method = lambda: 'HEAD'
        resp = urlopen(req)
    except HTTPError as err:
        logger.debug(str(err))
        return name, size

    content_disposition = resp.getheader('Content-Disposition')
    if content_disposition:
        fname = _CNTDISP_REGEX.search(content_disposition)
        if fname:
            name = fname.groups()[0]

    content_length = resp.getheader('Content-Length')
    if content_length:
        size = int(content_length)

    return name, size


class DataverseImportProvider(ImportProvider):
    _dataverse_regex = None

    def __init__(self):
        super().__init__('Dataverse')
        events.bind('model.setting.save.after', 'wholetale', self.setting_changed)

    @property
    def dataverse_regex(self):
        if not self._dataverse_regex:
            self._dataverse_regex = self.create_dataverse_regex()
        return self._dataverse_regex

    @staticmethod
    def get_base_url_setting():
        return Setting().get(constants.PluginSettings.DATAVERSE_URL)

    @staticmethod
    def get_extra_hosts_setting():
        return Setting().get(constants.PluginSettings.DATAVERSE_EXTRA_HOSTS)

    def create_dataverse_regex(self):
        url = self.get_base_url_setting()
        if not url.endswith('installations-json'):
            url = urlunparse(
                urlparse(url)._replace(path='/api/info/version')
            )
        try:
            resp = urlopen(url, timeout=1)
            resp_body = resp.read()
            data = json.loads(resp_body.decode('utf-8'))
            if 'installations' in data:
                urls = [_['url'] for _ in data['installations']]
            else:
                urls = [self.get_base_url_setting()]
        except Exception:
            logger.warn('[dataverse] failed to generate regex')
            urls = []

        urls += self.get_extra_hosts_setting()
        if urls:
            return re.compile("^" + "|".join(urls) + ".*$")
        else:
            return re.compile("^$")

    def getDatasetUID(self, doc: object, user: object) -> str:
        if 'folderId' in doc:
            # It's an item, grab the parent which should contain all the info
            doc = Folder().load(doc['folderId'], user=user, level=AccessType.READ)
        # obj is a folder at this point use its meta
        return doc['meta']['identifier']

    def setting_changed(self, event):
        triggers = {
            constants.PluginSettings.DATAVERSE_URL, constants.PluginSettings.DATAVERSE_EXTRA_HOSTS
        }
        if not hasattr(event, "info") or event.info.get('key', '') not in triggers:
            return
        self._dataverse_regex = None

    def matches(self, entity: Entity) -> bool:
        url = entity.getValue()
        return self.dataverse_regex.match(url) is not None

    @staticmethod
    def _parse_dataset(url):
        """Extract title, file, doi from Dataverse resource.

        Handles: {siteURL}/dataset.xhtml?persistentId={persistentId}
        """
        url = urlunparse(
            url._replace(path='/api/datasets/:persistentId')
        )
        resp = urlopen(url).read()
        data = json.loads(resp.decode('utf-8'))
        meta = data['data']['latestVersion']['metadataBlocks']['citation']['fields']
        title = next(_['value'] for _ in meta if _['typeName'] == 'title')
        doi = '{authority}/{identifier}'.format(**data['data'])
        files = []
        for obj in data['data']['latestVersion']['files']:
            files.append({
                'filename': obj['dataFile']['filename'],
                'filesize': obj['dataFile']['filesize'],
                'mimeType': obj['dataFile']['contentType'],
                'id': obj['dataFile']['id'],
                'doi': obj['dataFile']['persistentId'],
                'directoryLabel': obj.get('directoryLabel', ''),
            })

        return title, files, doi

    @staticmethod
    def _files_to_hierarchy(files):
        hierarchy = {'+files+': []}

        for fobj in files:
            temp = hierarchy
            for subdir in pathlib.Path(fobj.get('directoryLabel', '')).parts:
                if subdir not in temp:
                    temp[subdir] = {'+files+': []}
                temp = temp[subdir]
            temp['+files+'].append(fobj)

        return hierarchy

    @staticmethod
    def _parse_file_url(url):
        """Extract title, file, doi from Dataverse resource.

        Handles:
            {siteURL}/file.xhtml?persistentId={persistentId}&...
            {siteURL}/api/access/datafile/:persistentId/?persistentId={persistentId}
        """
        qs = parse_qs(url.query)
        try:
            full_doi = qs['persistentId'][0]
        except (KeyError, ValueError):
            # fail here in a meaningful way...
            raise

        file_persistent_id = os.path.basename(full_doi)
        doi = os.path.dirname(full_doi)
        if doi.startswith('doi:'):
            doi = doi[4:]

        search_url = urlunparse(
            url._replace(path='/api/search', query='q=filePersistentId:' + file_persistent_id)
        )
        title, files, _ = _query_dataverse(search_url)
        return title, files, doi

    @staticmethod
    def _parse_access_url(url):
        """Extract title, file, doi from Dataverse resource.

        Handles: {siteURL}/api/access/datafile/{fileId}
        """
        fileId = os.path.basename(url.path)
        search_url = urlunparse(
            url._replace(path='/api/search', query='q=entityId:' + fileId)
        )
        return _query_dataverse(search_url)

    @staticmethod
    def _sanitize_files(url, files):
        """Sanitize files metadata since results from search queries are inaccurate.

        File size is wrong: https://github.com/IQSS/dataverse/issues/5321
        URL doesn't point to original format, by default.
        """

        def _update_attrs(url, obj, query):
            access_url = urlunparse(
                url._replace(path='/api/access/datafile/' + fileId,
                             query=query)
            )
            name, size = _get_attrs_via_head(obj, access_url)
            obj['filesize'] = size
            obj['filename'] = name
            obj['url'] = access_url
            return obj

        for obj in files:
            fileId = str(obj['id'])
            # Register original too
            if obj['mimeType'] == 'text/tab-separated-values':
                yield _update_attrs(url, obj.copy(), 'format=original')
                yield _update_attrs(url, obj.copy(), '')
            else:
                obj['url'] = urlunparse(
                    url._replace(path='/api/access/datafile/' + fileId,
                                 query='')
                )
                yield obj

    def parse_pid(self, pid: str, sanitize: bool = False):
        url = urlparse(pid)
        if url.path.endswith('file.xhtml') or \
                url.path.startswith('/api/access/datafile/:persistentId'):
            parse_method = self._parse_file_url
        elif url.path.startswith('/api/access/datafile'):
            parse_method = self._parse_access_url
        else:
            parse_method = self._parse_dataset
        title, files, doi = parse_method(url)

        if sanitize:
            files = list(self._sanitize_files(url, files))
        return title, files, doi

    def lookup(self, entity: Entity) -> DataMap:
        title, files, doi = self.parse_pid(entity.getValue())
        size = sum(_['filesize'] for _ in files)
        return DataMap(entity.getValue(), size, doi=doi, name=title,
                       repository=self.getName())

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

    def _listRecursive(self, user, pid: str, name: str, base_url: str = None,
                       progress=None):

        def _recurse_hierarchy(hierarchy):
            files = hierarchy.pop('+files+')
            for obj in files:
                yield ImportItem(
                    ImportItem.FILE, obj['filename'],
                    size=obj['filesize'],
                    mimeType=obj.get('mimeType', 'application/octet-stream'),
                    url=obj['url'],
                    identifier=obj.get('doi') or doi
                )
            for folder in hierarchy.keys():
                yield ImportItem(ImportItem.FOLDER, name=folder)
                yield from _recurse_hierarchy(hierarchy[folder])
                yield ImportItem(ImportItem.END_FOLDER)

        title, files, doi = self.parse_pid(pid, sanitize=True)
        hierarchy = self._files_to_hierarchy(files)
        yield ImportItem(ImportItem.FOLDER, name=title, identifier=doi)
        yield from _recurse_hierarchy(hierarchy)
        yield ImportItem(ImportItem.END_FOLDER)
