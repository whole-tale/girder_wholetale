from girder import logger
from girder.api.rest import RestException
from girder.constants import AccessType
from girder.models.folder import Folder

from . import DataONELocations
from ..import_providers import ImportProvider
from ..data_map import DataMap
from ..file_map import FileMap
from ..import_item import ImportItem
from ..entity import Entity
from .register import \
    D1_lookup, \
    extract_metadata_docs, \
    get_documents, \
    get_package_pid, \
    get_package_list, \
    extract_data_docs, \
    extract_resource_docs, \
    check_multiple_metadata


ALL_LOCATIONS = [DataONELocations.prod_cn, DataONELocations.dev_mn, DataONELocations.dev_cn]


class DataOneImportProvider(ImportProvider):
    def __init__(self):
        super().__init__('DataONE')

    def matches(self, entity: Entity) -> bool:
        url = entity.getValue()
        try:
            package_pid = get_package_pid(url, entity['base_url'])
        except RestException:
            return False
        return package_pid is not None

    def lookup(self, entity: Entity) -> DataMap:
        # just wrap D1_lookup for now
        # this does not seem to properly resolve individual files. If passed something like
        # https://cn.dataone.org/cn/v2/resolve/urn:uuid:9266a118-78b3-48e3-a675-b3dfcc5d0fc4,
        # it returns the parent dataset, which, as a user, I'd be annoyed with
        dm = D1_lookup(entity.getValue(), entity['base_url'])
        dm.setRepository(self.getName())
        return dm

    def listFiles(self, entity: Entity) -> FileMap:
        result = get_package_list(entity.getValue(), entity['base_url'])
        return FileMap.fromDict(result)

    def getDatasetUID(self, doc: object, user: object) -> str:
        # TODO: doesn't work with data in tale's data dir
        if 'folderId' in doc:
            # It's an item, grab the parent which should contain all the info
            doc = Folder().load(doc['folderId'], user=user, level=AccessType.READ)
        # obj is a folder at this point use its meta
        return doc['meta']['identifier']

    def _listRecursive(self, user, pid: str, name: str, base_url: str = DataONELocations.prod_cn,
                       progress=None):
        """Create a package description (Dict) suitable for dumping to JSON."""
        if progress:
            progress.update(increment=1, message='Processing package {}.'.format(pid))

        # query for things in the resource map. At this point, it is assumed that the pid
        # has been correctly identified by the user in the UI.

        docs = get_documents(pid, base_url)

        # Filter the Solr result by TYPE so we can construct the package
        metadata = extract_metadata_docs(docs)
        data = extract_data_docs(docs)
        children = extract_resource_docs(docs)

        # Add in URLs to resolve each metadata/data object by
        self._addResolutionUrls(metadata, base_url)
        self._addResolutionUrls(data, base_url)

        # Determine the folder name. This is usually the title of the metadata file
        # in the package but when there are multiple metadata files in the package,
        # we need to figure out which one is the 'main' or 'documenting' one.
        primary_metadata = [doc for doc in metadata if 'documents' in doc]

        check_multiple_metadata(primary_metadata)

        # Create a Dict to store folders' information
        # the data key is a concatenation of the data and any metadata objects
        # that aren't the main or documenting metadata

        data += [doc for doc in metadata
                 if doc['identifier'] != primary_metadata[0]['identifier']]
        if not name:
            name = primary_metadata[0]['title']

        yield ImportItem(ImportItem.FOLDER, name, identifier=primary_metadata[0]['identifier'])

        for fileObj in data:
            try:
                fileName = fileObj['fileName']
            except KeyError:
                fileName = fileObj['identifier']

            yield ImportItem(ImportItem.FILE, fileName, identifier=fileObj['identifier'],
                             url=fileObj['url'], size=int(fileObj['size']),
                             mimeType=fileObj['formatId'])

        # Recurse and add child packages if any exist
        if children is not None and len(children) > 0:
            for child in children:
                logger.debug('Registering child package, {}'.format(child['identifier']))
                yield from self._listRecursive(
                    user, child['identifier'], None, base_url=base_url, progress=progress)

        yield ImportItem(ImportItem.END_FOLDER)
        logger.debug('Finished registering dataset')

    def _addResolutionUrls(self, docs, base_url):
        """
        Combines the base coordinating node URL with the resolve endpoint and identifier
        :param docs: List of metadata/data objects
        :param base_url: The coordinating node base URL (including the version)
        :return: None
        """
        for d in docs:
            d['url'] = "{}/{}/{}".format(base_url, 'resolve', d['identifier'])
