import pathlib
import tempfile
import urllib
import zipfile
from typing import cast, Dict, Optional, Generator

from ..import_item import ImportItem
from ..entity import Entity
from ..import_providers import ImportProvider


_COPY_BUFSZ = 64 * 1024


class _BagTree:
    def __init__(self, name: str, is_dir: bool = False, url: Optional[str] = None,
                 size: Optional[int] = None):
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
             size: Optional[int] = None) -> None:
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
    def __init__(self) -> None:
        super().__init__('BDBag')

    def matches(self, entity: Entity) -> bool:
        return False

    def _listRecursive(self, user: Dict[str, object], pid: str, name: str,
                       base_url: Optional[str] = None,
                       progress: Optional[object] = None) -> Generator[ImportItem, None, None]:
        # base_url + '/' + name is expected to be a path to a zip file
        if not pid:
            raise ValueError('pid must contain a path to a bag.')
        with zipfile.ZipFile(pid) as zf:
            with tempfile.TemporaryDirectory() as tmp_dir:
                zf.extractall(tmp_dir)

                bag_root = pathlib.Path(tmp_dir)
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
                yield from self._listFolder(root, main)
                yield ImportItem(ImportItem.END_FOLDER)

    def _listFolder(self, branch: _BagTree,
                    bag_path: pathlib.Path) -> Generator[ImportItem, None, None]:
        assert branch.list is not None
        for k, v in branch.list.items():
            if v.is_dir():
                yield ImportItem(ImportItem.FOLDER, name=k)
                yield from self._listFolder(v, bag_path / k)
                yield ImportItem(ImportItem.END_FOLDER)
            else:
                if v.url:
                    yield ImportItem(ImportItem.FILE, k, size=v.size,
                                     mimeType='application/octet-stream', url=v.url)
                else:
                    # import directly
                    bag_file_path = bag_path / k
                    yield ImportItem(ImportItem.FILE, k,
                                     size=bag_file_path.stat().st_size,
                                     mimeType='application/octet-stream',
                                     url='file://{}'.format(bag_file_path.absolute()))

    def _get_zip_file(self, entity: Entity) -> zipfile.ZipFile:
        if not isinstance(entity.getValue(), zipfile.ZipFile):
            raise ValueError('Entity value must be a ZipFile')
        return cast(zipfile.ZipFile, entity.getValue())

    def _read_fetch_txt(self, root: _BagTree, main: pathlib.Path) -> None:
        fetch_path = main / 'fetch.txt'
        if fetch_path.exists():
            with fetch_path.open() as f:
                line = f.readline()
                while line:
                    self._parse_fetch_line(root, line.strip())
                    line = f.readline()

    def _parse_fetch_line(self, root: _BagTree, line: str) -> None:
        els = line.split()
        if len(els) != 3:
            raise ValueError('Invalid line in fetch.txt: {}'.format(line))
        url = els[0]  # no need to urldecode this one
        path = urllib.parse.unquote(els[2])
        ppath = pathlib.PurePosixPath(path)
        size = int(els[1])

        root.add(ppath, url, size=size)

    def _read_bag_dir(self, root: _BagTree, main: pathlib.Path) -> None:
        self._scan_dirs(root, main, main)

    def _scan_dirs(self, root: _BagTree, dir: pathlib.Path, strip_path: pathlib.Path) -> None:
        for item in dir.iterdir():
            if item.is_dir():
                self._scan_dirs(root, item, strip_path)
            else:
                root.add(item.relative_to(strip_path))
