import six.moves.urllib as urllib

from girder.utility.model_importer import ModelImporter


def getOrCreateRootFolder(name, description=str()):
    collection = ModelImporter.model('collection').createCollection(
        name, public=True, reuseExisting=True)
    folder = ModelImporter.model('folder').createFolder(
        collection, name, parentType='collection', public=True,
        reuseExisting=True, description=description)
    return folder


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


def esc(value):
    """
    Escape a string so it can be used in a Solr query string
    :param value: The string that will be escaped
    :type value: str
    :return: The escaped string
    :rtype: str
    """
    return urllib.parse.quote_plus(value)


def create_tree_record(object_id, name, model, parent_id):
    """
    Node records make up the jsTree, and are added to the 'children'
    attribute. This method takes the needed parameters to make a
    full node. The icon attribute maps to an icon in the dashboard,
    which is why we append icon to the end. The possibilites are
    'folder icon', 'file icon', and 'linkify icon' (for the data directory)

    :param object_id: The ID of the node
    :param name: The name of the node
    :param model: The node's model
    :param parent_id: The potential parent
    :return: A record describing a node
    """
    if model == 'item':
        model = 'file'
    record = {
        'id': object_id,
        'text': name,
        'icon': model + ' icon',
        'state': {
            'opened': False,
            'disabled': False,
            'selected': True
        },
        'children': [],
        'li_attr': {},
        'a_attr': {}
    }

    if parent_id:
        record['parent'] = parent_id
    return record


def create_tree_from_root(root, user, model_type, is_root=False):
    """
    Recursively constructs a tree conforming to jsTree's JSON format
    :param root: The root node that the tree starts at
    :param user: The logged in user
    :param model_type: The type of object being described
    :param model_type: The type of object being described
    :param is_root: Set to true when there shouldn't be a parent node
    :return: A record for a node
    """

    record = create_tree_record(str(root['_id']),
                                root['name'],
                                model_type,
                                None if is_root else str(root['parentId']))
    records = list()
    records.append(record)
    folders = ModelImporter.model('folder').childFolders(root,
                                                         parentType='folder',
                                                         user=user)
    for folder in folders:
        record['children'].append(create_tree_from_root(folder,
                                                        user,
                                                        'folder'))
    child_files = ModelImporter.model('folder').childItems(folder=root, user=user)
    for child_file in child_files:
        file_record = create_tree_record(str(child_file['_id']),
                                         child_file['name'],
                                         'file',
                                         str(child_file['folderId']))
        record['children'].append(file_record)
    return record
