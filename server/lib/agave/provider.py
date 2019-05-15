import os
import re
import json
from typing import Tuple
from html.parser import HTMLParser
from urllib.parse import parse_qs
from urllib.request import OpenerDirector, HTTPSHandler
from agavepy.agave import Agave
from girder.models.item import Item
from girder.models.folder import Folder

from plugins.wholetale.server.lib.file_map import FileMap
from ..import_providers import ImportProvider
from ..resolvers import DOIResolver
from ..entity import Entity
from ..data_map import DataMap
from ..import_item import ImportItem


class DesignSafeImportProvider(ImportProvider):
    def __init__(self):
        super().__init__('DesignSafe')

    @staticmethod
    def create_regex():
        return re.compile(r'^https://www.designsafe-ci.org/data/browser/public/.*')
        # DS example   'https://www.designsafe-ci.org/data/browser/public/designsafe.storage.published/PRJ-1901/#details-7889180989778095640-242ac11e-0001-012'
        # NEES example 'https://www.designsafe-ci.org/data/browser/public/nees.public/NEES-2013-1207.groups/Experiment-15'

    def lookup(self, entity: Entity) -> DataMap:
        doc = self._getDocument(entity.getValue())
        (endpoint, path, doi, title) = self._extractMeta(doc)
        size = -1
        return DataMap(entity.getValue(), size, doi=doi, name=title, repository=self.getName())

    def _getDocument(self, url):
        od = OpenerDirector()
        od.add_handler(HTTPSHandler())
        with od.open(url) as resp:
            if resp.status == 200:
                return resp.read().decode('utf-8')
            elif resp.status == 404:
                raise Exception('Document not found %s' % url)
            else:
                raise Exception('Error fetching document %s: %s' % (url, resp.read()))

    def _extractMeta(self, doc) -> Tuple[str, str, str, str]:
        dp = DocParser()
        dp.feed(doc)
        return dp.getMeta()

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
        doc = self._getDocument(pid)
        (doi, title) = self._extractMeta(doc)
        yield ImportItem(ImportItem.FOLDER, name=title, identifier='doi:' + doi)
        accessToken = user["agaveAccessToken"]
        refreshToken = user["agaveRefreshToken"]
        url = pid.split("https://www.designsafe-ci.org/data/browser/public/", 1)[1].split("/")
        endpoint = url[0]
        path = "/" + url[1]
        ag = Agave(api_server="https://agave.designsafe-ci.org", token=accessToken, refresh_token=refreshToken)
        yield from self._listRecursive2(ag, endpoint, path, progress)
        yield ImportItem(ImportItem.END_FOLDER)

    def _listRecursive2(self, ag, endpoint: str, path: str, progress=None):
        from pudb.remote import set_trace;set_trace(term_size=(120, 40), host='0.0.0.0', port=6900)
        if path[-1] != '/':
            path = path + '/'
        if progress:
            progress.update(increment=1, message='Listing files')
        for entry in ag.files.list(filePath=path, systemId=endpoint):
            if entry['type'] == 'dir' and entry['name'] != '.':
                yield ImportItem(ImportItem.FOLDER, name=entry['name'])
                yield from self._listRecursive2(ag, endpoint, path + entry['name'], progress)
                # yield from self._listRecursive2(ag, endpoint, path + entry['name'], progress)
                yield ImportItem(ImportItem.END_FOLDER)
            elif entry['type'] == 'file':
                yield ImportItem(
                    ImportItem.FILE, entry['name'], size=entry['length'],
                    mimeType='application/octet-stream',
                    url='https://agave.designsafe-ci.org/files/v2/media/system/%s/%s%s' % (endpoint, path, entry['name']))


class DocParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = None
        self.doi = None

    def handle_starttag(self, tag, attrs):
        if tag == 'meta':
            self._handleMetaTag(dict(attrs))

    def _handleMetaTag(self, attrs):
        if 'name' not in attrs:
            return
        if attrs['name'] == 'citation_title':
            self.title = attrs['content']
        elif attrs['name'] == 'citation_doi':
            self.doi = self._extractDOI(attrs['content'])

    def _extractDOI(self, content):
        return DOIResolver.extractDOI(content)

    def getMeta(self):
        return self.doi, self.title
