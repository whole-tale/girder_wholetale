import pathlib
import tempfile
import urllib
import zipfile
from typing import cast, Dict, Optional, Generator
from zipfile import Path

import httpio

from ..import_item import ImportItem
from ..entity import Entity
from ..import_providers import ImportProvider


_COPY_BUFSZ = 64 * 1024


def _text(o: object) -> str:
    if isinstance(o, str):
        return o
    if isinstance(o, bytes):
        return o.decode('UTF-8')
    raise ValueError('Don\'t know how to convert object of type "%s" to string' % type(o))


class _BagTree:
    def __init__(self, name: str, is_dir: bool = False, url: Optional[str] = None,
                 size: int = -1):
        self.name = name
        self._is_dir = is_dir
        self.size = size
        if is_dir:
            self.list = {}  # type: Optional[Dict[str, _BagTree]]
            self.url = None
        else:
            self.list = None
            self.url = url

    def add(self, path: pathlib.Path, url: Optional[str] = None,
            size: Optional[int] = None) -> None:
        self._add(path, url, path, size)

    def is_dir(self) -> bool:
        # the reason for this method is that zipfile.is_dir is a method, not a property, so
        # it can get really confusing to mix x.is_dir with y.is_dir()
        return self._is_dir

    def _add(self, path: pathlib.Path, url: Optional[str], orig_path: pathlib.Path,
             size: int = -1) -> None:
        assert self.list is not None
        name = path.parts[0]
        if len(path.parts) == 1:
            # leaf
            if name in self.list:
                raise ValueError('Duplicate entry: {}'.format(orig_path))
            self.list[name] = _BagTree(name, url=url, size=size)
        else:
            if name not in self.list:
                self.list[name] = _BagTree(name, is_dir=True)
            dir = self.list[name]
            if not dir.is_dir():
                raise ValueError('Attempted to add a file where a directory '
                                 'exists: {}'.format(orig_path))
            dir._add(path.relative_to(name), url, orig_path, size=size)


class BDBagProvider(ImportProvider):
    def __init__(self, name: str = 'BDBag') -> None:
        super().__init__(name)

    def matches(self, entity: Entity) -> bool:
        return str(entity.getValue()).endswith('.zip')

    def _listRecursive(self, user: Dict[str, object], pid: str, name: str,
                       base_url: Optional[str] = None,
                       progress: Optional[object] = None) -> Generator[ImportItem, None, None]:
        # base_url + '/' + name is expected to be a path to a zip file
        if not pid:
            raise ValueError('pid must contain a path to a bag.')
        if pid.startswith('https://'):
            # may need tokens

            # https://pbcconsortium.isrd.isi.edu/chaise/record/#1/Beta_Cell:Dataset/RID=1-882P
            # ->
            # https://pbcconsortium.s3.amazonaws.com/shared/5ad7cdf55b0d5007601015b7ff1ea8d6/2021-11-08_16.50.02/Dataset_1-882P.zip
            fp = httpio.open(pid)
            zip_url = pid
        else:
            # treat as path
            fp = open(pid, 'rb')
            zip_url = 'file://' + pid

        try:
            zf = zipfile.ZipFile(fp)
            with tempfile.TemporaryDirectory() as tmp_dir:
                bag_root = zipfile.Path(zf)
                subdirs = list(bag_root.iterdir())
                if len(subdirs) != 1:
                    raise ValueError('Invalid bag: must have a single entry in root directory')

                dataset_name = subdirs[0].name
                main = subdirs[0]
                root = _BagTree(dataset_name, is_dir=True)

                # we traverse both fetch.txt and the bag to build a tree of all files, whether
                # external or internal to the bag since it's not quite clear that one can traverse
                # a given directory twice and have the rest of the infrastructure be ok with that

                self._read_fetch_txt(root, main)
                self._read_bag_dir(root, main)

                yield ImportItem(ImportItem.FOLDER, name=dataset_name)
                # make a new ZipFile for the same reason that mk_zip_path is necessary since
                # iterdir() triggers the issue
                yield from self._listFolder(root, main, zip_url, tmp_dir)
                yield ImportItem(ImportItem.END_FOLDER)
        finally:
            fp.close()

    def _listFolder(self, branch: _BagTree, bag_path: zipfile.Path,
                    zip_url: str, tmp_dir: str) -> Generator[ImportItem, None, None]:
        assert branch.list is not None
        for k, v in branch.list.items():
            if v.is_dir():
                yield ImportItem(ImportItem.FOLDER, name=k)
                yield from self._listFolder(v, bag_path / k, zip_url, tmp_dir)
                yield ImportItem(ImportItem.END_FOLDER)
            else:
                if v.url:
                    yield ImportItem(ImportItem.FILE, k, size=v.size,
                                     mimeType='application/octet-stream', url=v.url)
                else:
                    # import directly
                    bag_file_path: Path = bag_path.joinpath(k)
                    zip_path = self._path_in_zip(bag_file_path)
                    size = bag_file_path.root.getinfo(str(zip_path)).file_size  # type: ignore

                    # alternatively, we should maybe import the zip file and then refer to
                    # the file inside the zip using the same mechanism as for http(s) zips

                    extracted = None
                    if zip_url.startswith('file://'):
                        extracted = bag_file_path.root.extract(str(zip_path), path=tmp_dir)
                        url = 'file://' + extracted
                    else:
                        url = zip_url + '?path=' + str(zip_path)

                    yield ImportItem(ImportItem.FILE, k,
                                     size=size,
                                     mimeType='application/octet-stream',
                                     url=url)

                    if extracted:
                        pathlib.Path(extracted).unlink()

    def _read_fetch_txt(self, root: _BagTree, main: zipfile.Path) -> None:
        fetch_path = main / 'fetch.txt'
        if fetch_path.exists():
            with fetch_path.open() as f:
                line = _text(f.readline())
                while line:
                    self._parse_fetch_line(root, line.strip())
                    line = _text(f.readline())

    def _parse_fetch_line(self, root: _BagTree, line: str) -> None:
        els = line.split()
        if len(els) != 3:
            raise ValueError('Invalid line in fetch.txt: {}'.format(line))
        url = els[0]  # no need to urldecode this one
        path = urllib.parse.unquote(els[2])
        ppath = pathlib.PurePosixPath(path)
        size = int(els[1])

        root.add(ppath, url, size=size)

    def _read_bag_dir(self, root: _BagTree, main: zipfile.Path) -> None:
        self._scan_dirs(root, main, main)

    def _relative_to(self, path: zipfile.Path, root: zipfile.Path) -> pathlib.Path:
        return pathlib.Path(path.at).relative_to(pathlib.Path(root.at))  # type: ignore

    def _path_in_zip(self, path: zipfile.Path) -> pathlib.Path:
        return pathlib.Path(path.at)  # type: ignore

    def _scan_dirs(self, root: _BagTree, dir: zipfile.Path, strip_path: zipfile.Path) -> None:
        for item in dir.iterdir():
            if item.is_dir():
                self._scan_dirs(root, item, strip_path)
            else:
                root.add(self._relative_to(item, strip_path))
