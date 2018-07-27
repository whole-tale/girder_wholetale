import uuid
import yaml as yaml

from girder import logger
from girder.models.model_base import ValidationException
from girder.api.rest import RestException
from girder.models.file import File
from girder.constants import \
    AccessType
from girder.utility.model_importer import ModelImporter
from girder.utility.path import getResourcePath

from .dataone_package import \
    create_minimum_eml, \
    generate_system_metadata, \
    create_resource_map, \
    create_external_object_structure
from .dataone_register import find_initial_pid
from .utils import \
    check_pid, \
    get_file_item, \
    get_remote_url, \
    is_dataone_url, \
    get_dataone_package_url
from .constants import \
    API_VERSION, \
    ExtraFileNames

from d1_client.mnclient_2_0 import MemberNodeClient_2_0
from d1_common.types.exceptions import DataONEException


def create_client(mn_base_url, auth_token):
    """
    Creates and returns a member node client

    :param mn_base_url: The url of the member node endpoint
    :param auth_token: The auth token for the user that is using the client
    Should be of the form {"headers": { "Authorization": "Bearer <TOKEN>}}
    :type mn_base_url: str
    :type auth_token: dict
    :return: A client for communicating with a DataONE node
    :rtype: MemberNodeClient_2_0
    """
    return MemberNodeClient_2_0(mn_base_url, **auth_token)


def upload_file(client, pid, file_object, system_metadata):
    """
    Uploads two files to a DataONE member node. The first is an object, which is just a data file.
    The second is a metadata file describing the file object.

    :param client: A client for communicating with a member node
    :param pid: The pid of the data object
    :param file_object: The file object that will be uploaded to the member node
    :param system_metadata: The metadata object describing the file object
    :type client: MemberNodeClient_2_0
    :type pid: str
    :type file_object: str
    :type system_metadata: d1_common.types.generated.dataoneTypes_v2_0.SystemMetadata
    """

    pid = check_pid(pid)
    try:
        client.create(pid, file_object, system_metadata)

    except Exception as e:
        raise ValidationException('Error uploading file to DataONE. {0}'.format(str(e)))


def create_upload_eml(tale, client, user, item_ids, file_sizes=dict()):
    """
    Creates the EML metadata document along with an additional metadata document
    and uploads them both to DataONE. A pid is created for the EML document, and is
    returned so that the resource map can reference it at a later time.

    :param tale: The tale that is being described
    :param client: The client to DataONE
    :param user: The user that is requesting this action
    :param item_ids: The ids of the items that have been uploaded to DataONE
    :param file_sizes: We need to sometimes account for non-data files
     (like tale.yml) .The size needs to be in the EML record so pass them
      in here. The size should be described in bytes
    :type tale: wholetale.models.tale
    :type client: MemberNodeClient_2_0
    :type user: girder.models.user
    :type item_ids: list
    :type file_sizes: dict
    :return: pid of the EML document
    :rtype: str
    """

    # Create the EML metadata
    eml_pid = str(uuid.uuid4())
    eml_doc = create_minimum_eml(tale,
                                 user,
                                 item_ids,
                                 eml_pid,
                                 file_sizes)

    # Create the metadata describing the EML document
    meta = generate_system_metadata(pid=eml_pid,
                                    format_id='eml://ecoinformatics.org/eml-2.1.1',
                                    file_object=eml_doc,
                                    name='science_metadata.xml')
    # meta is type d1_common.types.generated.dataoneTypes_v2_0.SystemMetadata
    # Upload the EML document with its metadata
    upload_file(client=client, pid=eml_pid, file_object=eml_doc, system_metadata=meta)
    return eml_pid


def create_upload_resmap(res_pid, eml_pid, obj_pids, client):
    """
    Creates a resource map describing a package and uploads it to DataONE. The
    resource map can be thought of as the glue that holds a package together.

    In order to do this, the following steps are taken.
        1. Create the resource map
        2. Create the metadata document describing the resource map
        3. Upload the pair to DataONE

    :param res_pid: The pid for the resource map
    :param eml_pid: The pid for the metadata document
    :param obj_pids: A list of the pids for each object that was uploaded to DataONE;
     A list of pids that the resource map is documenting.
    :param client: The client to the DataONE member node
    :type res_pid: str
    :type eml_pid: str
    :type obj_pids: list
    :type client: MemberNodeClient_2_0
    :return: None
    """

    res_map = create_resource_map(res_pid, eml_pid, obj_pids)
    # To view the contents of res_map, call d1_common.xml.serialize_to_transport()
    meta = generate_system_metadata(res_pid,
                                    format_id='http://www.openarchives.org/ore/terms',
                                    file_object=res_map,
                                    name=str())

    upload_file(client=client, pid=res_pid, file_object=res_map, system_metadata=meta)


def create_upload_object_metadata(client, file_object):
    """
    Takes a file from girder and
        1. Creates metadata describing it
        2. Uploads the file_object with the metadata to DataONE
        3. Returns a pid that is assigned to file_object so that it can
            be added to the resource map later.

    :param client: The client to the DataONE member node
    :param file_object: The file object that will be uploaded
    :type client: MemberNodeClient_2_0
    :type file_object: girder.models.file
    :return: The pid of the object
    :rtype: str
    """

    pid = str(uuid.uuid4())
    assetstore = File().getAssetstoreAdapter(file_object)

    meta = generate_system_metadata(pid,
                                    format_id=file_object['mimeType'],
                                    file_object=file_object,
                                    name=file_object['name'],
                                    is_file=True)

    upload_file(client=client,
                pid=pid,
                file_object=assetstore.open(file_object).read(),
                system_metadata=meta)

    return pid


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
    For example,
     {'dataone': ['uuid:123456', 'doi.10x501'],
     'remote_objects: ['url1', 'url2'],
     local: [file_obj1, file_obj2]}
    :rtype: dict
    """

    dataone_objects = list()
    remote_objects = list()
    local_objects = list()

    for item_id in item_ids:
        # Check if it points do a file on DataONE
        url = get_remote_url(item_id, user)
        if url is not None and is_dataone_url(url):
            dataone_objects.append(find_initial_pid(url))
            continue
        """
        If there is a url, and it's not pointing to a DataONE resource, then assume
         it's pointing to an external object
        """
        if url is not None:
            remote_objects.append(item_id)
            continue

        # If the file wasn't linked to a remote location, then it must exist locally. This
        # is a list of girder.models.File objects
        local_objects.append(get_file_item(item_id, user))

    return {'dataone': dataone_objects, 'remote': remote_objects, 'local': local_objects}


def create_paths_structure(item_ids, user):
    """
    Creates a file that lists the path that each item is located at.
    :param item_ids: A list of items that are in the tale
    :type item_ids: list
    :return: The dict representing the file structure
    :rtype: dict
    """

    """
    We'll use a dict structure to hold the file contents during creation for
     convenience.
    """
    path_file = dict()

    for item_id in item_ids:
        item = ModelImporter.model('item').load(item_id,
                                                level=AccessType.READ,
                                                user=user)
        path = getResourcePath('item', item, force=True)
        path_file[item['name']] = path

    return path_file


def create_tale_info_structure(tale):
    """
    Any miscellaneous information about the tale can be added here.
    :param tale: The tale that is being published
    :type tale: wholetale.models.Tale
    :return: A dictionary of tale information
    :rtype: dict
    """

    # We'll store the information as a dictionary
    tale_info = dict()
    tale_info['version'] = API_VERSION
    tale_info['identifier'] = str(tale['_id'])
    tale_info['metadata'] = 'Metadata: science_metadata.xml'

    return tale_info


def create_upload_tale_yaml(tale, remote_objects, item_ids, user, client):
    """
    The yaml content is represented with Python dicts, and then dumped to
     the yaml object.
    :param tale: The tale that is being published
    :param remote_objects: A lsit of objects that are registered external to WholeTale
    :param item_ids: A list of all of the ids of the files that are being uploaded
    :param user: The user performing the actions
    :param client: The client that interfaces DataONE
    :type tale: wholetale.models.Tale
    :type remote_objects: list
    :type item_ids: list
    :type user: girder.models.User
    :type client: MemberNodeClient_2_0
    :return: The pid and the size of the file
    :rtype: tuple
    """

    # Create the dict that has general information about the package
    tale_info = create_tale_info_structure(tale)

    # Create the dict that holds the file paths
    file_paths = dict()
    file_paths['paths'] = create_paths_structure(item_ids, user)

    # Create the dict that tracks externally defined objects, if applicable
    external_files = dict()
    if len(remote_objects) > 0:
        external_files['external files'] = create_external_object_structure(remote_objects, user)

    # Append all of the information together
    yaml_file = dict(tale_info)
    yaml_file.update(file_paths)

    if bool(external_files):
        yaml_file.update(external_files)
    # Transform the file into yaml from the dict structure
    yaml_file = yaml.dump(yaml_file, default_flow_style=False)

    # Create a pid for the file
    pid = str(uuid.uuid4())
    # Create system metadata for the file
    meta = generate_system_metadata(pid=pid,
                                    format_id='text/plain',
                                    file_object=yaml_file,
                                    name=ExtraFileNames.tale_config)
    # Upload the file
    upload_file(client=client, pid=pid, file_object=yaml_file, system_metadata=meta)

    # Return the pid
    return pid, len(yaml_file)


def create_upload_package(item_ids, tale, user, repository, jwt):
    """
    Uploads local or remote files to a DataONE repository.
     There are four cases that need to be handled.
        1. The file  was uploaded directly to Whole Tale and physically exists in Girder.
           In this case, a metadata document needs to be generated for each local file. This
           involves hashing the file, and extracting information about it such as the name,
           description, etc. The file and associated metadata record are uploaded to DataONE
           as a pair.

        2. The file was registered from DataONE, and the file record in Whole Tale points to
           its location in DataONE. Since the file is in DataONE, the file can be referenced in
           the resource map, which avoids uploading redundant data. In this case, the only files
           that are created and uploaded are
              1. A pair of an EML record with its metadata
              2. A resource map describing the package contents

        3. The file was registered from an external source, such as Globus. More generally,
           this is the case where the file record has a link to a file on an external resource
           other than DataONE. To handle this, the file needs to be brought onto the Whole Tale
           filesystem. Once on the local system, metadata is generated for the file and the pair
           are uploaded to DataONE. Once uploaded, the file is removed from

        4. A combination of 1, 2, or 3.

    To handle the different cases, the item_ids are sorted into a dict that provides easy access.
    For each file that gets uploaded to DataONE, a pid is created for it. These are saved so that
    we can reference them in the resource map, which is the last object that is uploaded.

    :param item_ids: A list of items that contain the files that will be uploaded to DataONE
    :param tale: The tale that is being packaged
    :param user: The user that is requesting the upload
    :param repository: The DataONE member node
    :type item_ids: list
    :type tale: girder.models.tale
    :type user: girder.models.user
    :type repository: str
    :return: The pid of the package's resource map
    """

    # create_client can throw DataONEException
    try:
        """
        Create a client object that is used to interface DataONE. This can interact with a
         particular member node by specifying `repository`. It also needs an authentication token.
         The auth portion is incomplete, and requires you to paste your token in <TOKEN>.
        """
        client = create_client(repository, {"headers": {
            "Authorization": "Bearer "+jwt}})

        """
        If the client was successfully created, sort all of the items by their type:
          a. Locally on the machine (bytes of the file are on disk)
          b. Pointing to DataONE (The `models.file` has a `linkUrl` that points to an object on
             DataONE).
          c. Pointing to remote file not on DataONE (eg Globus)
        """
        filtered_items = filter_items(item_ids, user)

        """
        Iterate through the list of objects that are local (ie files without a `linkUrl`
         and upload them to DataONE. The call to create_upload_object_metadata will
         return a pid that describes the object (not the metadata object). We'll save
         this pid so that we can pass it to the resource map.
        """
        # List that holds pids that are assigned to any local objects
        local_file_pids = list()
        for file in filtered_items['local']:
            logger.debug('Processing local files for DataONE upload')
            local_file_pids.append(create_upload_object_metadata(client, file))

        tale_yaml_pid, tale_yaml_length = create_upload_tale_yaml(tale,
                                                                  filtered_items['remote'],
                                                                  item_ids,
                                                                  user,
                                                                  client)

        """
        Create an EML document describing the data, and then upload it. Save the
         pid for the resource map.
        """
        file_sizes = {'tale_yaml': tale_yaml_length}
        eml_pid = create_upload_eml(tale,
                                    client,
                                    user,
                                    item_ids,
                                    file_sizes)

        """
        Once all objects are uploaded, create and upload the resource map. This file describes
         the object relations (ie the package). This should be the last file that is uploaded.
        """
        upload_objects = filtered_items['dataone'] + local_file_pids + [tale_yaml_pid]
        resmap_pid = str(uuid.uuid4())
        create_upload_resmap(resmap_pid, eml_pid, upload_objects, client)
        return get_dataone_package_url(repository, resmap_pid)

    except DataONEException as e:
        logger.warning('DataONE Error: {}'.format(e))
        raise RestException('Error uploading file to DataONE. {0}'.format(str(e)))
