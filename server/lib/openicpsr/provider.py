from bs4 import BeautifulSoup
import functools
import os
import pathlib
import re
import requests
import tempfile
from typing import Generator
from urllib.parse import urlparse, urlunparse, parse_qs
import zipfile

from girder.models.assetstore import Assetstore
from girder.utility import assetstore_utilities

from ..import_providers import ImportProvider
from ..bdbag.bdbag_provider import _FileTree
from ..data_map import DataMap
from ..file_map import FileMap
from ..import_item import ImportItem
from ..entity import Entity


class OpenICPSRImportProvider(ImportProvider):
    def __init__(self):
        super().__init__("OpenICPSR")
        self.base_url = "https://www.openicpsr.org"

    def create_regex(self):
        return re.compile(f"^{self.base_url}/.*view$")

    def getDatasetUID(self, doc: object, user: object) -> str:
        return doc["meta"]["identifier"]

    @staticmethod
    def _is_tale(record):
        return False

    def _get_landing_page(self, url):
        r = requests.get(url)
        soup = BeautifulSoup(r.text, "html.parser")
        # metadata = json.loads(soup.find("script", {"type": "application/ld+json"}).text.strip())
        doi = (
            soup.find("meta", attrs={"name": "DC.identifier"}).attrs["content"].strip()
        )
        if not doi.startswith("doi:"):
            doi = "doi:" + doi
        download_href = soup.find("a", attrs={"id": "downloadButton"}).attrs["href"]
        terms_url = urlparse(self.base_url + download_href)
        q = parse_qs(terms_url.query)
        download_url = terms_url._replace(
            path=terms_url.path.replace("terms", q["type"][0]),
            params="",
            query=f"dirPath={q['path'][0]}",
        )
        return {
            "doi": doi,
            "size": -1,
            "name": soup.find("meta", attrs={"name": "DC.title"}).attrs["content"],
            "download_url": urlunparse(download_url),
        }

    def lookup(self, entity: Entity) -> DataMap:
        record = self._get_landing_page(entity.getValue())
        return DataMap(
            entity.getValue(),
            record["size"],
            doi=record["doi"],
            name=record["name"],
            repository=self.getName(),
            tale=self._is_tale(record),
        )

    def listFiles(self, entity: Entity) -> FileMap:
        raise NotImplementedError()

    def _listFolder(
        self, branch: _FileTree, path: pathlib.Path, relpath: pathlib.Path, doi: str
    ) -> Generator[ImportItem, None, None]:
        assert branch.list is not None
        for k, v in branch.list.items():
            if v.is_dir():
                yield ImportItem(
                    ImportItem.FOLDER,
                    name=k,
                    identifier=doi,
                    meta={"dsRelPath": (relpath / k).as_posix()},
                )
                yield from self._listFolder(v, path / k, relpath / k, doi)
                yield ImportItem(ImportItem.END_FOLDER)
            else:
                if v.url:
                    yield ImportItem(
                        ImportItem.FILE,
                        k,
                        size=v.size,
                        mimeType="application/octet-stream",
                        url=v.url,
                    )
                else:
                    # import directly
                    file_path = path / k
                    yield ImportItem(
                        ImportItem.FILE,
                        name=k,
                        identifier=doi,
                        meta={"dsRelPath": (relpath / k).as_posix()},
                        size=file_path.stat().st_size,
                        mimeType="application/octet-stream",
                        url="file://{}".format(file_path.absolute()),
                    )

    def _scan_dirs(
        self, root: _FileTree, dir: pathlib.Path, strip_path: pathlib.Path
    ) -> None:
        for item in dir.iterdir():
            if item.is_dir():
                self._scan_dirs(root, item, strip_path)
            else:
                root.add(item.relative_to(strip_path))

    @staticmethod
    def _get_user_pass(user):
        try:
            for token in user["otherTokens"]:
                if token["resource_server"] == "www.openicpsr.org":
                    return token["access_token"]
        except KeyError:
            return  # Raise error?

    def _get_payload(self, data_url, user):
        assetstore = Assetstore().getCurrent()
        adapter = assetstore_utilities.getAssetstoreAdapter(assetstore)
        tempDir = adapter.tempDir

        resp = requests.get(
            data_url, cookies={"JSESSIONID": self._get_user_pass(user)}, stream=True
        )
        if resp.headers.get("Content-Encoding") in ("gzip",):
            resp.raw.read = functools.partial(resp.raw.read, decode_content=True)

        disp = resp.headers["Content-Disposition"]
        fname = re.findall("filename=(.+)", disp)[0].strip('"')
        zfname = os.path.join(tempDir, fname)
        with open(zfname, "wb") as fp:
            for chunk in resp.raw:
                fp.write(chunk)

        return zfname

    def _listRecursive(
        self, user, pid: str, name: str, base_url: str = None, progress=None
    ):
        record = self._get_landing_page(pid)
        zfname = self._get_payload(record["download_url"], user)

        with zipfile.ZipFile(zfname) as zf:
            with tempfile.TemporaryDirectory() as tmp_dir:
                zf.extractall(tmp_dir)
                zip_root = pathlib.Path(tmp_dir)
                subdirs = [_.is_dir() for _ in zip_root.iterdir()]
                if len(subdirs) != 1 or not subdirs[0]:
                    dataset_name = os.path.basename(zf.fp.name)
                    main = zip_root
                else:
                    main = next(zip_root.iterdir())
                    dataset_name = main.name
                root = _FileTree(dataset_name, is_dir=True)
                self._scan_dirs(root, main, main)

                yield ImportItem(
                    ImportItem.FOLDER,
                    name=dataset_name,
                    identifier=record["doi"],
                    meta={"dsRelPath": "/"},
                )
                yield from self._listFolder(root, main, pathlib.Path("/"), record["doi"])
                yield ImportItem(ImportItem.END_FOLDER)

    def check_auth(self, user):
        if not self._get_user_pass(user):
            raise ValueError("Authentication required.")
