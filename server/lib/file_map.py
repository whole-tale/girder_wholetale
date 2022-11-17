from typing import Dict, List, Optional

fileMapDoc = {
    "type": "object",
    "description": (
        "A container with a list of filenames and sizes " "from a DataONE repository."
    ),
    "properties": {
        "name": {"type": "string", "description": "The name of the data file."},
        "size": {"type": "integer", "description": "Size of the file in bytes."},
    },
    "required": ["name", "fileList"],
    "example": {
        "Doctoral Dissertation Research: Mapping Community Exposure to Coastal Climate Hazards"
        "in the Arctic: A Case Study in Alaska's North Slope": {
            "fileList": [{"science_metadata.xml": {"size": 8961}}],
            "Arctic Slope Shoreline Change Risk Spatial Data Model, 2015-16": {
                "fileList": [{"science_metadata.xml": {"size": 7577}}]
            },
            "North Slope Borough shoreline change risk WebGIS usability workshop.": {
                "fileList": [{"science_metadata.xml": {"size": 7940}}]
            },
            "Local community verification of shoreline change risks along the Alaskan Arctic Ocean"
            "coast"
            " (North Slope).": {
                "fileList": [{"science_metadata.xml": {"size": 14250}}]
            },
            "Arctic Slope Shoreline Change Susceptibility Spatial Data Model, 2015-16": {
                "fileList": [{"science_metadata.xml": {"size": 10491}}]
            },
        }
    },
}


class FileItem:
    def __init__(self, name: str, size: int):
        self.name = name
        self.size = size

    def toDict(self):
        return {self.name: {"size": self.size}}


class FileList:
    def __init__(self):
        self.list = []

    def addFile(self, fi: FileItem):
        self.list.append(fi)

    def toList(self):
        return sorted([x.toDict() for x in self.list], key=lambda k: list(k))


class ChildList:
    def __init__(self):
        self.list = {}

    def addChild(self, name: str) -> "FileMap":
        child = FileMap(name)
        self.list[name] = child
        return child

    def getChild(self, name: str) -> "FileMap":
        return self.list[name]

    def names(self):
        return self.list.keys()


class FileMap:
    def __init__(self, name: str):
        self.name = name
        self.children = None
        self.fileList = None

    def getName(self):
        return self.name

    def setName(self, name: str):
        self.name = name

    def addChild(self, name: str) -> "FileMap":
        if self.children is None:
            self.children = ChildList()
        return self.children.addChild(name)

    def addFile(self, name: str, size: int):
        if self.fileList is None:
            self.fileList = FileList()
        self.fileList.addFile(FileItem(name, size))

    def getFileList(self) -> FileList:
        return self.fileList

    def getChild(self, name: str) -> Optional["FileMap"]:
        if self.children is None:
            return None
        else:
            return self.children.getChild(name)

    def toDict(self, root=True):
        d = {}
        if self.fileList is not None:
            d["fileList"] = self.fileList.toList()
        if self.children is not None:
            for name in self.children.names():
                d[name] = self.getChild(name).toDict(root=False)
        if root:
            return {self.name: d}
        else:
            return d

    @staticmethod
    def fromDict(d: Dict):
        (name, value) = FileMap._checkSingleEntryDict(d)
        fm = FileMap(name)
        FileMap._fromDict1(fm, value)
        return fm

    @staticmethod
    def _checkSingleEntryDict(d: Dict, expectedKey: str = None):
        if len(d) > 1:
            raise Exception(
                "Invalid data. Dictionary %s should have only one element" % d
            )
        key = next(iter(d.keys()))
        if (expectedKey is not None) and (key != expectedKey):
            raise Exception(
                "Invalid data. Unexpected key %s in dictionary %s" % (key, d)
            )
        return (key, d[key])

    @staticmethod
    def _fromDict1(fm: "FileMap", d: Dict):
        for key in d.keys():
            if key == "fileList":
                FileMap._addFiles(fm, d[key])
            else:
                FileMap._addChild(fm, key, d[key])

    @staticmethod
    def _addFiles(fm: "FileMap", _list: List[Dict[str, Dict[str, object]]]):
        # can this list ever have more than 1 element?
        if len(_list) == 0:
            return
        _dict = _list[0]
        for name in _dict.keys():
            (_, size) = FileMap._checkSingleEntryDict(_dict[name], "size")
            fm.addFile(name, size)

    @staticmethod
    def _addChild(fm: "FileMap", key: str, d: Dict):
        fm = fm.addChild(key)
        FileMap._fromDict1(fm, d)
