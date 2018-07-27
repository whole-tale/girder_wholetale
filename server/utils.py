from girder.utility.model_importer import ModelImporter
from girder import logger
from girder.models.item import Item
from girder.models.folder import Folder
from girder.constants import \
    AccessType, \
    AssetstoreType
from girder.api.rest import RestException

from .constants import DataONELocations


def getOrCreateRootFolder(name, description=str()):
    collection = ModelImporter.model('collection').createCollection(
        name, public=True, reuseExisting=True)
    folder = ModelImporter.model('folder').createFolder(
        collection, name, parentType='collection', public=True,
        reuseExisting=True, description=description)
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

    folder = Folder().load(
        id=tale['folderId'],
        user=user,
        level=AccessType.READ,
        exc=True)
    child_items = Folder().childItems(folder=folder)
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

    doc = Item().load(item_id, level=AccessType.READ, user=user)

    if doc is None:
        logger.warning('Failed to load item {}. Leaving get_file_item'.format(str(item_id)))
        return None
    child_files = Item().childFiles(doc)

    if bool(child_files.count()):
        # Return the first item
        return child_files.next()

    logger.warning('Failed to find a file for item {}. Leaving get_file_item'.format(str(item_id)))
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

    file = get_file_item(item_id, user)
    if file is not None:
        return file.get('mimeType', '')


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

    file = get_file_item(item_id, user)
    if file is None:
        file_error = 'Failed to find the file with ID {}'.format(item_id)
        logger.warning(file_error)
        raise RestException(file_error)
    url = file.get('linkUrl')
    if url is not None:
        if is_dataone_url(url):
            return url


def is_dataone_url(url):
    """
    Checks if a url has dataone in it
    :param url: The url in question
    :return: True if it does, False otherwise
    """

    res = url.find('dataone.org')
    if res is not -1:
        return True
    else:
        return False


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

    if not isinstance(pid, str):
        return str(pid)
    else:
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

    file = get_file_item(item_id, user)
    if file is None:
        file_error = 'Failed to find the file with ID {}'.format(item_id)
        logger.warning(file_error)
        raise RestException(file_error)
    url = file.get('linkUrl')
    if url is not None:
        return url


def get_tale_files(tale, user):
    """
    Gets the tale artifacts and creates a list of files.
    :param tale: The tale whose artifacts are being extracted
    :param user: The user that is requesting the artifacts
    :type tale: wholetale.models.Tale
    :type user: girder.models.User
    :return: A list of the files
    :rtype list
    """
    artifact_items = get_tale_artifacts(tale, user)
    files = list()
    for item in artifact_items:
        files.append(get_file_item(item['_id'], user))
    return files


def create_repository_file(recipe):
    """
    Creates a file that holds the recipe repository. Instead of
     doing the collection,folder,item,file creation in the celery worker,
     we'll do it here. We let the worker know which file to use by sending it
     the file id returned from this function

    :param recipe: The recipe whose repository is being saved
    :type recipe: wholetale.models.recipe
    :return: The file id or None
    :rtype: str, NoneType
    """

    # Name for the folder & collection that will hold the repositories
    folder_name = 'repository_bank'
    folder_description = "Holds items that represent archived repositories"

    """
    Get all of the assetstores and retrieve GridFS. The reason we're using this
     assetstore is that we don't want this folder in the user's home directory.
    """
    store = ModelImporter.model('assetstore').findOne({'type': AssetstoreType.GRIDFS})
    if store is None:
        logger.warning('No GridFS assetstore found')
        return None

    admin_user = ModelImporter.model('user').getAdmins()[0]

    parent_folder = getOrCreateRootFolder(folder_name, folder_description)

    item_name = 'Repository: {}'.format(recipe['name'])
    item_description = "Item that holds the repository used in recipe {}".format(recipe['_id'])
    repo_item = ModelImporter.model('item').createItem(name=item_name,
                                                       creator=admin_user,
                                                       folder=parent_folder,
                                                       description=item_description,
                                                       reuseExisting=True)

    repo_file = ModelImporter.model('file').createFile(creator=admin_user,
                                                       item=repo_item,
                                                       name=str(recipe['_id']),
                                                       size=0,
                                                       assetstore=store,
                                                       mimeType='application/tar+gzip',
                                                       reuseExisting=True)
    return str(repo_file['_id'])


def get_dataone_package_url(repository, pid):
    """
    Given a repository url and a pid, construct a url that should
     be the package's landing page.

    :param repository: The repository that the package is on
    :param pid: The package pid
    :return: The package landing page
    """
    if repository in DataONELocations.prod_cn:
        return str('https://search.dataone.org/#view/'+pid)
    elif repository in DataONELocations.dev_mn:
        return str('https://dev.nceas.ucsb.edu/#view/'+pid)
