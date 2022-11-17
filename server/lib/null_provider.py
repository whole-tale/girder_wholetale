from girder.exceptions import RestException

from .data_map import DataMap
from .entity import Entity
from .file_map import FileMap
from .import_providers import ImportProvider


class NullImportProvider(ImportProvider):
    def __init__(self):
        super().__init__("null")

    def matches(self, entity: Entity) -> bool:
        return True

    def lookup(self, entity: Entity) -> DataMap:
        raise RestException(
            'Failed to interpret "%s" in any meaningful way' % entity.getValue()
        )

    def listFiles(self, entity: Entity) -> FileMap:
        raise RestException(
            'Failed to interpret "%s" in any meaningful way' % entity.getValue()
        )
