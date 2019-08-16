import re
import requests
import json
from typing import Tuple
from agavepy.agave import Agave
import urllib.parse

from plugins.wholetale.server.lib.file_map import FileMap
from ..import_providers import ImportProvider
from ..entity import Entity
from ..data_map import DataMap
from ..import_item import ImportItem


class CyVerseImportProvider(ImportProvider):
    def __init__(self):
        super().__init__('CyVerse')

    @staticmethod
    def create_regex():
        return re.compile(r'^http://datacommons.cyverse.org/browse/iplant/home/.*')

    def lookup(self, entity: Entity) -> DataMap:
        (doi, title) = self._extractMeta(entity.getValue())
        size = -1
        return DataMap(entity.getValue(), size, doi=doi, name=title, repository=self.getName())

    def _extractMeta(self, url) -> Tuple[str, str]:
        path = url.split("http://datacommons.cyverse.org/browse")[1]
        args = {"djng_url_name": "api_stat", "djng_url_kwarg_path": path}
        encoded = urllib.parse.urlencode(args)
        resp = self._getDocument(
            "http://datacommons.cyverse.org/angular/reverse/?%s" % encoded)
        projectId = resp["id"]
        resp = self._getDocument(
            "http://datacommons.cyverse.org/angular/reverse/"
            "?djng_url_name=api_metadata&djng_url_kwarg_item_id=%s" % projectId)
        doi = None
        title = None
        for meta in resp["sorted_meta"]:
            if meta["key"] == "DOI":
                doi = meta["value"].lstrip()
            if meta["key"] == "Title":
                title = meta["value"]
            if doi and title:
                break
        return doi, title

    def _getDocument(self, url):
        resp = requests.get(url)
        if resp.status_code == 200:
            return json.loads(resp.text)
        elif resp.status_code == 404:
            raise Exception('Document not found %s' % url)
        else:
            raise Exception('Error fetching document %s: %s' % (url, resp.content))

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
        (doi, title) = self._extractMeta(pid)
        yield ImportItem(ImportItem.FOLDER, name=title, identifier='doi:' + doi)
        accessToken = user["agaveAccessToken"]
        refreshToken = user["agaveRefreshToken"]
        path = pid.split("http://datacommons.cyverse.org/browse/iplant/home", 1)[1]
        endpoint = "data.iplantcollaborative.org"
        ag = Agave(api_server="https://agave.iplantc.org", token=accessToken,
                   refresh_token=refreshToken)
        yield from self._listRecursive2(ag, endpoint, path, progress)
        yield ImportItem(ImportItem.END_FOLDER)

    def _listRecursive2(self, ag, endpoint: str, path: str, progress=None):
        if path[-1] != '/':
            path = path + '/'
        if progress:
            progress.update(increment=1, message='Listing files')
        for entry in ag.files.list(filePath=path, systemId=endpoint):
            if entry['type'] == 'dir' and entry['name'] != '.':
                yield ImportItem(ImportItem.FOLDER, name=entry['name'])
                yield from self._listRecursive2(ag, endpoint, path + entry['name'], progress)
                yield ImportItem(ImportItem.END_FOLDER)
            elif entry['type'] == 'file':
                yield ImportItem(
                    ImportItem.FILE, entry['name'], size=entry['length'],
                    mimeType='application/octet-stream',
                    url='https://agave.iplantc.org/files/v2/media/system/%s/%s%s' %
                        (endpoint, path, entry['name']))
