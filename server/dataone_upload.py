import uuid
import yaml as yaml
import os
import io
import tempfile
from urllib.request import urlopen
from shutil import copyfileobj


from girder import logger
from girder.api.rest import RestException
from girder.models.file import File
from girder.models.notification import \
    Notification, \
    ProgressState
from girder.constants import \
    AccessType, \
    ROOT_DIR
from girder.utility.model_importer import ModelImporter
from girder.utility.path import getResourcePath

from .dataone_package import \
    create_minimum_eml, \
    generate_system_metadata, \
    create_resource_map, \
    create_external_object_structure, \
    transfer_prod_to_dev
from .dataone_register import find_initial_pid
from .utils import \
    check_pid, \
    get_file_item, \
    get_remote_url, \
    is_dataone_url, \
    get_dataone_package_url, \
    extract_user_id, \
    is_in_network, \
    is_dev_url

from .constants import \
    API_VERSION, \
    ExtraFileNames, \
    license_files

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
    except DataONEException as e:
        raise RestException('Error uploading file to DataONE. {0}'.format(str(e)))


def create_upload_eml(tale,
                      client,
                      user,
                      item_ids,
                      license_id,
                      user_id,
                      file_sizes,
                      new_dataone_objects):
    """
    Creates the EML metadata document along with an additional metadata document
    and uploads them both to DataONE. A pid is created for the EML document, and is
    returned so that the resource map can reference it at a later time.

    :param tale: The tale that is being described
    :param client: The client to DataONE
    :param user: The user that is requesting this action
    :param item_ids: The ids of the items that have been uploaded to DataONE
    :param license_id: The ID of the license
    :param user_id: The user that owns this resource
    :param file_sizes: We need to sometimes account for non-data files
     (like tale.yml) .The size needs to be in the EML record so pass them
      in here. The size should be described in bytes
    :param new_dataone_objects:
    :type tale: wholetale.models.tale
    :type client: MemberNodeClient_2_0
    :type user: girder.models.user
    :type item_ids: list
    :type license_id: str
    :type user_id: str
    :type file_sizes: dict
    :type new_dataone_objects: dict
    :return: pid of the EML document
    :rtype: str
    """

    # Create the EML metadata
    eml_pid = str(uuid.uuid4())
    eml_doc = create_minimum_eml(tale,
                                 user,
                                 item_ids,
                                 eml_pid,
                                 file_sizes,
                                 license_id,
                                 user_id,
                                 new_dataone_objects)
    # Create the metadata describing the EML document
    meta = generate_system_metadata(pid=eml_pid,
                                    format_id='eml://ecoinformatics.org/eml-2.1.1',
                                    file_object=eml_doc,
                                    name='science_metadata.xml',
                                    rights_holder=user_id)
    # meta is type d1_common.types.generated.dataoneTypes_v2_0.SystemMetadata
    # Upload the EML document with its metadata
    upload_file(client=client,
                pid=eml_pid,
                file_object=io.BytesIO(eml_doc),
                system_metadata=meta)
    return eml_pid


def create_upload_resmap(res_pid, eml_pid, obj_pids, client, rights_holder):
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
    :param rights_holder: The owner of this object
    :type res_pid: str
    :type eml_pid: str
    :type obj_pids: list
    :type client: MemberNodeClient_2_0
    :type rights_holder: str
    :return: None
    """

    res_map = create_resource_map(res_pid, eml_pid, obj_pids)
    # To view the contents of res_map, call d1_common.xml.serialize_to_transport()
    meta = generate_system_metadata(res_pid,
                                    format_id='http://www.openarchives.org/ore/terms',
                                    file_object=res_map,
                                    name=str(),
                                    rights_holder=rights_holder)

    upload_file(client=client,
                pid=res_pid,
                file_object=io.BytesIO(res_map),
                system_metadata=meta)


def create_upload_object_metadata(client, file_object, rights_holder):
    """
    Takes a file that exists on the filesystem and
        1. Creates metadata describing it
        2. Uploads the file_object with the metadata to DataONE
        3. Returns a pid that is assigned to file_object so that it can
            be added to the resource map later.

    :param client: The client to the DataONE member node
    :param file_object: The file object that will be uploaded
    :param rights_holder: The owner of this object
    :type client: MemberNodeClient_2_0
    :type file_object: girder.models.file
    :type rights_holder: str
    :return: The pid of the object
    :rtype: str
    """

    pid = str(uuid.uuid4())
    assetstore = File().getAssetstoreAdapter(file_object)

    meta = generate_system_metadata(pid,
                                    format_id=file_object['mimeType'],
                                    file_object=file_object,
                                    name=file_object['name'],
                                    is_file=True,
                                    rights_holder=rights_holder)

    upload_file(client=client,
                pid=pid,
                file_object=io.BytesIO(assetstore.open(file_object).read()),
                system_metadata=meta)

    return pid


def filter_items(item_ids, user, member_node):
    """
    Take a list of item ids and determine whether it:
       1. Exists on the local file system
       2. Exists on DataONE
       3. Is linked to a remote location other than DataONE
    :param item_ids: A list of items to be processed
    :param user: The user that is requesting the package creation
    :param member_node: The member node that is being interfaced
    :type item_ids: list
    :type user: girder.models.User
    :type member_node: str
    :return: A dictionary of lists for each file location
    For example,
     {'dataone': ['uuid:123456', 'doi.10x501'],
     'remote_objects: ['url1', 'url2'],
     local: [file_obj1, file_obj2]}
    :rtype: dict
    """

    dataone_objects_out = list()
    dataone_objects_in = list()
    remote_objects = list()
    local_objects = list()

    logger.debug('In filter items')
    for item_id in item_ids:
        logger.debug('Processing item {}'.format(str(item_id)))
        # Check if it points do a dataone objbect
        url = get_remote_url(item_id, user)
        if url is not None:
            logger.debug('URL {}'.format(url))
            if is_dataone_url(url) or is_dev_url(url):
                res = is_in_network(url, member_node)
                if res:
                    logger.debug('File is in network')
                    pid = find_initial_pid(url)
                    dataone_objects_in.append(pid)
                    logger.debug('File is in network')
                    continue
                else:
                    # File is out of network. Need to download and upload it
                    logger.debug('File is out of netowrk')
                    dataone_objects_out.append(item_id)
                    continue
            """
            If there is a url, and it's not pointing to a DataONE resource, then assume
            it's pointing to an external object
            """
            logger.debug('Adding remote object')
            remote_objects.append(item_id)
            continue

        # If the file wasn't linked to a remote location, then it must exist locally. This
        # is a list of girder.models.File objects
        logger.debug('Adding local object')
        local_objects.append(get_file_item(item_id, user))

    return {'dataone_in': dataone_objects_in,
            'dataone_out': dataone_objects_out,
            'remote': remote_objects,
            'local': local_objects}


def create_paths_structure(item_ids):
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

    logger.debug('Recording the file paths for the items in the '
                 'Tale. {}'.format(type(item_ids)))
    for item_id in item_ids:
        logger.info("Item ID: {}  Type: {}".format(item_id, type(item_id)))
        item = ModelImporter.model('item').load(item_id,
                                                level=AccessType.READ,
                                                force=True)
        logger.debug('Loaded item')
        path = getResourcePath('item',
                               item,
                               force=True)
        logger.debug('Got resource path')
        path_file[item['name']] = path
    logger.debug('Leaving create_paths')
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
    logger.debug('Creating tale information structure for package')
    tale_info = dict()
    tale_info['version'] = API_VERSION
    tale_info['identifier'] = str(tale['_id'])
    tale_info['metadata'] = 'Metadata: science_metadata.xml'

    return tale_info


def create_upload_tale_yaml(tale,
                            remote_objects,
                            item_ids,
                            user,
                            client,
                            prov_info,
                            rights_holder):
    """
    The yaml content is represented with Python dicts, and then dumped to
     the yaml object.
    :param tale: The tale that is being published
    :param remote_objects: A lsit of objects that are registered external to WholeTale
    :param item_ids: A list of all of the ids of the files that are being uploaded
    :param user: The user performing the actions
    :param client: The client that interfaces DataONE
    :param prov_info: A dictionary of additional parameters for the file. This information
    is gathered in the UI and passed through the REST endpoint.
    :param rights_holder: The owner of this object
    :type tale: wholetale.models.Tale
    :type remote_objects: list
    :type item_ids: list
    :type user: girder.models.User
    :type client: MemberNodeClient_2_0
    :type prov_info: dict
    :type rights_holder: str
    :return: The pid and the size of the file
    :rtype: tuple
    """

    logger.debug('Creating the tale yaml file')
    # Create the dict that has general information about the package
    tale_info = create_tale_info_structure(tale)

    # Create the dict that holds the file paths
    file_paths = dict()
    file_paths['paths'] = create_paths_structure(item_ids)

    # Create the dict that tracks externally defined objects, if applicable
    external_files = dict()
    if len(remote_objects) > 0:
        logger.debug('Found remote object, creating structure for them')
        external_files['external files'] = create_external_object_structure(remote_objects, user)

    logger.debug('Appending tale yaml')
    # Append all of the information together
    yaml_file = dict(tale_info)
    yaml_file.update(file_paths)

    if bool(external_files):
        logger.debug('External files found. Appending to tale yaml')
        yaml_file.update(external_files)
    if prov_info:
        yaml_file.update(prov_info)
    # Transform the file into yaml from the dict structure
    yaml_file = yaml.dump(yaml_file, default_flow_style=False)

    # Create a pid for the file
    pid = str(uuid.uuid4())
    # Create system metadata for the file
    logger.debug('Generating system metadata for the tale yaml')
    meta = generate_system_metadata(pid=pid,
                                    format_id='text/plain',
                                    file_object=yaml_file,
                                    name=ExtraFileNames.tale_config,
                                    rights_holder=rights_holder)
    # Upload the file
    upload_file(client=client,
                pid=pid,
                file_object=io.StringIO(yaml_file),
                system_metadata=meta)

    # Return the pid
    return pid, len(yaml_file)


def upload_license_file(client, license_id, rights_holder):
    """
    Upload a license file to DataONE.

    :param client: The client that interfaces DataONE
    :param license_id: The ID of the license (see `ExtraFileNames` in constants)
    :param rights_holder: The owner of this object
    :type client: MemberNodeClient_2_0
    :type license_id: str
    :type rights_holder: str
    :return: The pid and size of the license file
    """

    # Holds the license text
    license_text = str()

    # Path to the license file
    license_path = os.path.join(ROOT_DIR,
                                'wholetale',
                                'licenses',
                                license_files[license_id])
    try:
        license_length = os.path.getsize(license_path)
        with open(license_path) as f:
            license_text = f.read()
    except IOError:
        logger.warning('Failed to open license file')
        return None, 0

    # Create a pid for the file
    pid = str(uuid.uuid4())
    # Create system metadata for the file
    meta = generate_system_metadata(pid=pid,
                                    format_id='text/plain',
                                    file_object=license_text,
                                    name=ExtraFileNames.license_filename,
                                    rights_holder=rights_holder)
    # Upload the file
    upload_file(client=client, pid=pid, file_object=license_text, system_metadata=meta)

    # Return the pid and length of the file
    return pid, license_length


def create_upload_repository(tale, client, user, rights_holder):
    """
    Downloads the repository that's pointed to by the recipe and uploads it to the
    node that `client` points to.
    :param tale: The Tale that is being registered
    :param client: The interface to the member node
    :param user: The user that's publishing the tale
    :param rights_holder: The owner of this object
    :type tale: girder.models.tale
    :type client: MemberNodeClient_2_0
    :type user: girder.models.user
    :type rights_holder: str
    :return:
    """
    try:
        image = ModelImporter.model('image', 'wholetale').load(
            tale['imageId'], user=user, level=AccessType.READ, exc=True)
        recipe = ModelImporter.model('recipe', 'wholetale').load(
            image['recipeId'], user=user, level=AccessType.READ, exc=True)
        download_url = recipe['url'] + '/tarball/' + recipe['commitId']

        with tempfile.NamedTemporaryFile() as temp_file:
            src = urlopen(download_url)
            try:
                # Copy the response into the temporary file
                copyfileobj(src, temp_file)
                logger.debug('Copied file, size: {}'.format(temp_file.tell()))

            except IOError as e:
                error_msg = 'Error copying environment file to disk. {}'.format(e)
                logger.warning(error_msg)

                # We should stop if we can't upload the repository
                raise RestException(error_msg)

        # Create a pid for the file
            pid = str(uuid.uuid4())
        # Create system metadata for the file
            temp_file.seek(0)
            meta = generate_system_metadata(pid=pid,
                                            format_id='application/tar+gzip',
                                            file_object=temp_file.read(),
                                            name=ExtraFileNames.environment_file,
                                            rights_holder=rights_holder)
            temp_file.seek(0)
            logger.debug('Uploading repository to DataONE')
            upload_file(client=client,
                        pid=pid,
                        file_object=io.BytesIO(temp_file.read()),
                        system_metadata=meta)

            size = os.path.getsize(temp_file.name)
        return pid, size

    except IOError as e:
        logger.debug('Failed to process repository'.format(e))
    return None, 0


def publish(item_ids,
            tale,
            user,
            repository,
            jwt,
            license_id,
            prov_info):
    """
    Responsible for delegating all of the tasks to take a user's Tale and create a package on
    DataONE.

     There are four cases that need to be handled.
        1. The file  was uploaded directly to Whole Tale and is not a linkFile.
           In this case, a metadata document needs to be generated for each local file. This
           involves hashing the file and extracting information about it such as the name,
           description, etc. The file and associated metadata are uploaded to DataONE
           as a pair, and then referenced in the resource map.

        2. The file was registered from DataONE, and the file record in Whole Tale points to
           its location in DataONE. Since the file is in DataONE, the file can be referenced in
           the resource map, which avoids uploading redundant data. In this case, the only files
           that are created and uploaded are
              1. An EML record with its metadata
              2. A resource map describing the package contents

        3. The file was registered from an external source, such as Globus. More generally,
           this is the case where the file record has a link to a file on an external resource
           other than DataONE. To handle this, the file needs to be brought onto the Whole Tale
           filesystem. Once on the local system, metadata is generated for the file and the pair
           are uploaded to DataONE.

        4. A combination of 1, 2, or 3.

    To handle the different cases, the item_ids are sorted into a dict that serves as a way to
    organize them.

    :param item_ids: A list of items that contain the files that will be uploaded to DataONE
    :param tale: The tale that is being packaged
    :param user: The user that is requesting the upload
    :param repository: The DataONE member node
    :param jwt: The user's JWT from DataONE
    :param license_id: The ID of the license (see `ExtraFileNames` in constants)
    :type item_ids: list
    :type tale: girder.models.tale
    :type user: girder.models.user
    :type repository: str
    :type jwt: str
    :type license_id: str
    :return: The pid of the package's resource map
    """

    # Create a progress notification that can updated to let the user know
    # the state
    progress = Notification().initProgress(user, "Creating DataONE Package")

    client = None

    # create_client can throw DataONEException
    try:
        """
        Create a client object that is used to interface DataONE. This can interact with a
         particular member node by specifying `repository`. The jwt is the jwt token from
         DataONE.
        """
        logger.debug('Creating the DataONE client')
        client = create_client(repository, {
            "headers": {
                "Authorization": "Bearer " + jwt,
                "Connection": "close"},
            "user_agent": "safari"})

    except DataONEException as e:
        logger.warning('Error creating the DataONE Client: {}'.format(e))
        # We'll want to exit if we can't create the client
        raise RestException('Failed to establish connection with DataONE. {}'.format(e))

    elevated_user = ModelImporter.model('user').getAdmins()[0]

    user_id = extract_user_id(jwt)
    if user_id is None:
        # Exit if we can't get the userId from the JWT
        raise RestException('Failed to process your DataONE credentials. Please'
                            ' ensure you are logged into DataONE.')
    """
    Sort all of the input files based on where they are located,
        1. HTTP resource
        2. DataONE resource
        3. Local filesystem object
    """
    filtered_items = filter_items(item_ids, user, repository)

    """
    Any files that exist on DataONE should be transfered to the network that the
    client points to. To do this we download the file, and then upload it to the
    network.
    """
    Notification().updateProgress(progress, message="Uploading Files")
    new_dataone_objects = transfer_prod_to_dev(filtered_items['dataone_out'],
                                               elevated_user,
                                               user_id,
                                               client)

    """
    Iterate through the list of objects that are local (ie files without a `linkUrl`
    and upload them to DataONE. The call to create_upload_object_metadata will
     return a pid that describes the object (not the metadata object). We'll save
        this pid so that we can pass it to the resource map.
    """
    local_file_pids = list()
    for file in filtered_items['local']:
        logger.debug('Processing local files for DataONE upload')
        local_file_pids.append(create_upload_object_metadata(client, file, user_id))

    tale_yaml_pid, tale_yaml_length = create_upload_tale_yaml(tale,
                                                              filtered_items['remote'],
                                                              item_ids,
                                                              elevated_user,
                                                              client,
                                                              prov_info,
                                                              user_id)

    """
    Upload the license file
    """
    logger.debug('Uploading the license file')
    license_pid, license_size = upload_license_file(client, license_id, user_id)

    """
    Upload the repository"""
    repository_pid, repository_size = create_upload_repository(tale, client, user, user_id)

    # Check repository upload status. If failed, we need to exit and let the user know
    Notification().updateProgress(progress, message="Creating Tale Metadata")

    """
    Create an EML document describing the data, and then upload it. Save the
    pid for the resource map.
    """
    file_sizes = {'tale_yaml': tale_yaml_length,
                  'license': license_size,
                  'repository': repository_size}

    """
    Get all of the items, except the ones that were transferred from an external
    source
    """
    eml_items = filtered_items.get('dataone_in') + \
        filtered_items.get('local') + filtered_items.get('remote')

    eml_items = filter(None, eml_items)
    eml_items = list(eml_items)
    logger.debug('Creating DataONE EML record for new Tale')
    eml_pid = create_upload_eml(tale,
                                client,
                                user,
                                eml_items,
                                license_id,
                                extract_user_id(jwt),
                                file_sizes,
                                new_dataone_objects)

    # Check eml file status. If it failed, we need to exit and let the user know
    logger.debug('Finished creating DataONE EML record')

    """
    While transfering the files from DataONE, new pids were assigned to each file
    These need to be added to the resource map.
    """
    new_pids = list()
    for dataone_object in new_dataone_objects:
        new_pids.append(dataone_object['pid'])

    """
    Once all objects are uploaded, create and upload the resource map. This file describes
    the object relations (ie the package). This should be the last file that is uploaded.
    Also filter out any pids that are None, which would have resulted from an error. This
    prevents referencing objects that failed to upload.
    """
    upload_objects = filter(None, filtered_items.get('dataone_in') +
                            local_file_pids + new_pids +
                            [tale_yaml_pid, license_pid, repository_pid, eml_pid])
    resmap_pid = str(uuid.uuid4())

    logger.debug('Creating DataONE resource map')
    create_upload_resmap(resmap_pid,
                         eml_pid,
                         upload_objects,
                         client,
                         user_id)
    logger.debug('Finished creating DataONE resource map')
    package_url = get_dataone_package_url(repository, resmap_pid)

    Notification().updateProgress(progress,
                                  state=ProgressState.SUCCESS,
                                  message='Your Tale was successfully '
                                          'published to DataONE and can '
                                          'be viewed at {}'.format(package_url))

    return package_url
