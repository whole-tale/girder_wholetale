from dataclasses import dataclass
from typing import Dict, List


dataMapDoc = {
    "type": "object",
    "description": (
        "A container with a basic information about "
        "a set of external data resources."
    ),
    "properties": {
        "dataId": {
            "type": "string",
            "description": "External dataset identificator, such as URL.",
        },
        "repository": {
            "type": "string",
            "description": "Name of a data repository holding the dataset.",
        },
        "doi": {"type": "string", "description": "Digital Object Identifier"},
        "name": {
            "type": "string",
            "description": (
                "A user-friendly name. Defaults to the name "
                "provided by an external repository."
            ),
        },
        "size": {"type": "integer", "description": "Size of the dataset in bytes."},
        "tale": {
            "type": "boolean",
            "description": "If True, external data resource is a Tale",
        },
        "base_url": {
            "type": "string",
            "description": "Optional CN url for DataONE datasets",
        },
    },
    "required": ["dataId", "repository", "doi", "name", "size"],
    "example": {
        "base_url": "https://cn.dataone.org/cn/v2",
        "dataId": "urn:uuid:42969280-e11c-41a9-92dc-33964bf785c8",
        "doi": "10.5063/F1Z899CZ",
        "name": (
            "Data from a dynamically downscaled projection of past and "
            "future microclimates covering North America from 1980-1999 "
            "and 2080-2099"
        ),
        "repository": "DataONE",
        "size": 178679,
        "tale": False,
    },
}


@dataclass
class DataMap:
    dataId: str
    size: int
    doi: str = None
    name: str = None
    repository: str = None
    tale: bool = False
    base_url: str = None

    def toDict(self) -> Dict:
        ret = {
            "dataId": self.dataId,
            "size": self.size,
            "repository": self.repository,
            "doi": self.doi,
            "name": self.name,
            "tale": self.tale,
        }
        if self.base_url:
            ret["base_url"] = self.base_url
        return ret

    @staticmethod
    def fromDict(d: Dict):
        return DataMap(
            d["dataId"],
            d.get("size", 0),
            repository=d["repository"],
            doi=d.get("doi"),
            name=d.get("name", "Unknown Dataset"),
            tale=d.get("tale", False),
            base_url=d.get("base_url"),
        )

    @staticmethod
    def fromList(d: List[Dict]):
        return [DataMap.fromDict(x) for x in d]
