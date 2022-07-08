import os
import pathlib
import re
import requests
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

from girder.models.folder import Folder
from girder.models.item import Item
from girder.models.setting import Setting

from ..import_providers import ImportProvider
from ..data_map import DataMap
from ..file_map import FileMap
from ..import_item import ImportItem
from ..entity import Entity
from ... import constants
from ...models.tale import Tale
from . import ZenodoNotATaleError


class ZenodoImportProvider(ImportProvider):
    def __init__(self):
        super().__init__("Zenodo")
        # TODO: add 'data.caltech.edu'
        # however it's totally different in terms of storing data...
        self.base_targets = ["https://zenodo.org/record/"]

    def create_regex(self):
        urls = self.get_extra_hosts_setting() + self.base_targets

        locations = []
        for url in urls:
            entry = urlparse(url)
            locations.append(entry.netloc + entry.path)

        return re.compile("^http(s)?://(" + "|".join(locations) + ").*$")

    @staticmethod
    def get_extra_hosts_setting():
        return Setting().get(constants.PluginSettings.ZENODO_EXTRA_HOSTS)

    def getDatasetUID(self, doc: object, user: object) -> str:
        try:
            identifier = doc["meta"]["identifier"]  # if root of ds, it should have it
        except (KeyError, TypeError):
            if "folderId" in doc:
                path_to_root = Item().parentsToRoot(doc, user=user)
            else:
                path_to_root = Folder().parentsToRoot(doc, user=user)
            # Collection{WT Catalog} / Folder{WT Catalog} / Folder{Zenodo ds root}
            identifier = path_to_root[2]["object"]["meta"]["identifier"]
        return identifier

    def _get_record(self, raw_url):
        url = urlparse(raw_url)
        record_id = url.path.rsplit("/", maxsplit=1)[1]
        req = requests.get(
            urlunparse(url._replace(path="/api/records/" + record_id)),
            headers={
                "accept": "application/vnd.zenodo.v1+json",
                "User-Agent": "Whole Tale",
            },
        )
        return req.json()

    @staticmethod
    def _is_tale(record):
        has_tale_keyword = "Tale" in record["metadata"].get("keywords", [])
        files = record["files"]
        only_one_file = len(files) == 1
        return has_tale_keyword and only_one_file

    @staticmethod
    def _get_doi_from_record(record):
        return "doi:" + record["doi"]

    def import_tale(self, data_map, user, force=False):
        # dataId in this case == record["links"]["record_html"]
        dataId = data_map.dataId
        record = self._get_record(dataId)
        existing_tale_id = Tale().findOne(
            query={
                "creatorId": user["_id"],
                "publishInfo.pid": {"$eq": self._get_doi_from_record(record)},
            },
            fields={"_id"},
        )
        if existing_tale_id and not force:
            return Tale().load(existing_tale_id["_id"], user=user)

        if not self._is_tale(record):
            raise ZenodoNotATaleError(record)

        file_ref = record["files"][0]
        if file_ref["type"] != "zip":
            raise ValueError("Not a zipfile")

        file_url = file_ref["links"]["self"]

        def stream_zipfile(chunk_size):
            with urlopen(file_url) as src:
                while True:
                    data = src.read(chunk_size)
                    if not data:
                        break
                    yield data

        publishInfo = [
            {
                "pid": self._get_doi_from_record(record),
                "uri": record["links"]["doi"],
                "date": record["created"],
                "repository_id": str(record["id"]),
                "repository": urlparse(dataId).netloc,
            }
        ]

        relatedIdentifiers = [
            {
                "relation": "IsDerivedFrom",
                "identifier": self._get_doi_from_record(record),
            }
        ]
        return Tale().createTaleFromStream(
            stream_zipfile,
            user=user,
            publishInfo=publishInfo,
            relatedIdentifiers=relatedIdentifiers,
        )

    @staticmethod
    def _get_title_from_record(record):
        try:
            version = record["metadata"]["version"]
        except KeyError:
            try:
                version = record["metadata"]["relations"]["version"][0]["index"] + 1
            except (KeyError, IndexError):
                version = record["id"]
        return record["metadata"]["title"] + "_ver_{}".format(version)

    def lookup(self, entity: Entity) -> DataMap:
        record = self._get_record(entity.getValue())
        size = sum((file_obj["size"] for file_obj in record["files"]))
        return DataMap(
            entity.getValue(),
            size,
            doi=self._get_doi_from_record(record),
            name=self._get_title_from_record(record),
            repository=self.name,
            tale=self._is_tale(record),
        )

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

    @staticmethod
    def _files_to_hierarchy(files):
        hierarchy = {"+files+": []}

        for file_obj in files:
            temp = hierarchy
            for subdir in pathlib.Path(file_obj["key"]).parts[:-1]:
                if subdir not in temp:
                    temp[subdir] = {"+files+": []}
                temp = temp[subdir]
            temp["+files+"].append(
                {
                    "size": file_obj["size"],
                    "name": file_obj["key"].rsplit("/", maxsplit=1)[-1],
                    "url": file_obj["links"]["self"],
                    "mimeType": "application/octet-stream",
                    "checksum": file_obj["checksum"],
                }
            )
        return hierarchy

    def _listRecursive(
        self, user, pid: str, name: str, base_url: str = None, progress=None
    ):
        record = self._get_record(pid)
        doi = self._get_doi_from_record(record)

        def _recurse_hierarchy(hierarchy, prefix="/"):
            files = hierarchy.pop("+files+")
            for obj in files:
                rel_path = os.path.join(prefix, obj["name"])
                alg, checksum = obj["checksum"].split(":")
                yield ImportItem(
                    ImportItem.FILE,
                    obj["name"],
                    size=obj["size"],
                    mimeType=obj["mimeType"],
                    url=obj["url"],
                    identifier=doi,
                    meta={"checksum": {alg: checksum}, "dsRelPath": rel_path},
                )
            for folder in hierarchy.keys():
                rel_path = os.path.join(prefix, folder)
                meta = {"dsRelPath": rel_path}
                yield ImportItem(ImportItem.FOLDER, name=folder, identifier=doi, meta=meta)
                yield from _recurse_hierarchy(hierarchy[folder], prefix=rel_path)
                yield ImportItem(ImportItem.END_FOLDER)

        meta = {k: record.get(k, "") for k in ["conceptdoi", "conceptrecid"]}
        meta["subProvider"] = urlparse(pid).netloc

        yield ImportItem(
            ImportItem.FOLDER,
            name=self._get_title_from_record(record),
            identifier=doi,
            meta=meta,
        )
        yield from _recurse_hierarchy(self._files_to_hierarchy(record["files"]))
        yield ImportItem(ImportItem.END_FOLDER)
