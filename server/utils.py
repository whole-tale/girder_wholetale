from girder.utility.model_importer import ModelImporter
from girder import logger
from girder.models.item import Item
from girder.models.folder import Folder
from girder.constants import AccessType

from .dataone_register import find_initial_pid


def getOrCreateRootFolder(name):
    collection = ModelImporter.model('collection').createCollection(
        name, public=True, reuseExisting=True)
    folder = ModelImporter.model('folder').createFolder(
        collection, name, parentType='collection', public=True, reuseExisting=True)
    return folder


def get_tale_artifacts(tale, user):
    """
    Gets meta files that describe the tale. This includes config files
    and the docker file. child_items holds the files that are in the tale
    folder-and needs to be sorted through to locate the config files.
    DEVNOTE: This currently jsut returns all of the files in the
    tale folder. This will be modified when we start saving the dockerfile.

    :param tale: The tale whose contents are to be retrieved
    :param user: The user accessing the filder
    :type tale: girder.models.Tale
    :type user: girder.models.User
    :return: A list of items that are in the folder
    :rtype list(girder.models.Item)
    """
    logger.debug('Entered get_tale_artifacts')
    folder = Folder().load(
        id=tale['folderId'],
        user=user,
        level=AccessType.READ,
        exc=True)
    child_items = Folder().childItems(folder=folder)
    logger.debug('Leaving get_tale_artifacts')
    return child_items


def get_file_item(item_id, user):
    """
    Gets the file out of an item.

    :param item_id: The item that has the file inside
    :param user: The user that is accessing the file
    :type: item_id: str
    :type user: girder.models.User
    :return: The file object or None
    :rtype: girder.models.file
    """
    logger.debug('Entered get_file_item')
    doc = Item().load(item_id, level=AccessType.ADMIN, user=user)

    if doc is None:
        logger.debug('Failed to load Item. Leaving get_file_item')
        return None
    child_files = Item().childFiles(doc)

    if bool(child_files):
        # We follow a rule of there only being one file per item, so return the 0th element
        logger.debug('Leaving get_file_item')
        return child_files[0]

    logger.debug('Failed to find a file. Leaving get_file_item')
    return None


def get_file_format(item_id, user):
    """
    Gets the format for a file from an item id

    :param item_id: The item that has the file inside.
    :param user: The user that is requesting the file format
    :type: item_id: str
    :type user: girder.models.user
    :return: The file's extension
    :rtype: str
    """
    logger.debug('Entered get_file_format')
    doc = Item().load(item_id, level=AccessType.ADMIN, user=user)

    if doc is None:
        logger.debug('Failed to load Item. Leaving get_file_item')
        return None
    child_files = Item().childFiles(doc)

    if bool(child_files):
        # We follow a rule of there only being one file per item, so return the 0th element
        logger.debug('Leaving get_file_item')
        return child_files[0].get('mimeType', '')

    logger.debug('Failed to find a file. Leaving get_file_format')
    return None


def get_tale_description(tale):
    """
    If a tale description is empty, it holds the value, 'null'. To avoid passing it
    to the UI, check if it is null, and return an empty string

    :param tale: The tale whose description is requested
    :type tale:  wholetale.models.tale
    :return: The tale description or str()
    :rtype: str
    """
    desc = tale['description']
    if desc is None:
        return str()
    return desc


def get_dataone_url(item_id, user):
    """
    Checks whether the file is linked externally to DataONE. If it is, it
    will return the url that the file links to.
    DEVNOTE: We may have to modify this to check for member nodes that don't
    have dataone in the url.

    :param item_id: The id of the item containing the file in question
    :param user: The user requesting the url
    :type item_id: str
    :type user: girder.models.user
    :return: The object's path in DataONE, None otherwise
    :rtype: str, None
    """
    logger.debug('Entered check_in_dataone')
    url = get_file_item(item_id, user).get('linkUrl')
    if url is not None:
        if url.find('dataone.org'):
            logger.debug('Leaving check_in_dataone')
            return url

    logger.debug('Leaving check_in_dataone')
    return None


def check_pid(pid):
    """
    Check that a pid is of type str. Pids are generated as uuid4, and this
    check is done to make sure the programmer has converted it to a str before
    attempting to use it with the DataONE client.

    :param pid: The pid that is being checked
    :type pid: str, int
    :return: Returns the pid as a str, or just the pid if it was already a str
    :rtype: str
    """
    logger.debug('Entered check_pid')
    if not isinstance(pid, str):
        logger.debug('Warning: PID was passed that is not a str')
        logger.debug('Leaving check_pid')
        return str(pid)
    else:
        logger.debug('Leaving check_pid')
        return pid


def get_remote_url(item_id, user):
    """
    Checks if a file has a link url and returns the url if it does. This is less
     restrictive than thecget_dataone_url in that we aren't restricting the link
      to a particular domain.

    :param item_id:
    :param user:
    :return: The url that points to the object
    :rtype: str or None
    """
    url = get_file_item(item_id, user).get('linkUrl')
    if url is not None:
        return url


def filter_items(item_ids, user):
    """
    Take a list of item ids and determine whether it:
       1. Exists on the local file system
       2. Exists on DataONE
       3. Is linked to a remote location other than DataONE

    :param item_ids: A list of items to be processed
    :param user: The user that is requesting the package creation
    :type item_ids: list
    :type user: girder.models.User
    :return: A dictionary of lists for each file location
    :rtype: dict
    """

    logger.debug('Entered filter_input_items')
    dataone_objects = list()
    remote_objects = list()
    local_objects = list()

    for item_id in item_ids:
        # Check if it points do a file on DataONE
        url = get_dataone_url(item_id, user)
        if url is not None:
            dataone_objects.append(find_initial_pid(url))
            continue

        # If the file wasn't linked to a remote location, then it must exist locally. This
        # is a list of girder.models.File objects
        local_objects.append(get_file_item(item_id, user))

    logger.debug('Leaving filter_input_items')
    return {'dataone': dataone_objects, 'remote': remote_objects, 'local': local_objects}
