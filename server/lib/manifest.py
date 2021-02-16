import json
import os
from urllib.parse import quote

from girder import logger
from girder.models.folder import Folder
from girder.utility import JsonEncoder
from girder.utility.model_importer import ModelImporter
from girder.exceptions import ValidationException
from girder.constants import AccessType
from gwvolman.constants import REPO2DOCKER_VERSION

from .license import WholeTaleLicense
from . import IMPORT_PROVIDERS


class Manifest:
    """
    Class that represents the manifest file.
    Methods that add information to the manifest file have the form
    add_<someProperty>
    while methods that create chunks of the manifest have the form
    create<someProperty>
    """

    def __init__(self, tale, user, expand_folders=True):
        """
        Initialize the manifest document with base variables
        :param tale: The Tale whose data is being serialized
        :param user: The user requesting the manifest document
        :param expand_folders: If True, when encountering a folder
            in the external data, return all child items recursively.
        """
        self.tale = tale
        self.user = user
        self.expand_folders = expand_folders

        self.validate()
        self.manifest = dict()
        # Create a set that represents any external data packages
        self.datasets = set()

        self.imageModel = ModelImporter.model("image", "wholetale")
        self.itemModel = ModelImporter.model('item')
        self.userModel = ModelImporter.model('user')

        self.manifest.update(self.create_context())
        self.manifest.update(self.create_basic_attributes())
        self.add_tale_creator()
        self.manifest.update(self.create_author_record())
        self.manifest.update(self.create_related_identifiers())
        self.manifest.update(self.create_repo2docker_version())
        self.add_tale_records()
        # Add any external datasets to the manifest
        self.add_dataset_records()
        self.add_license_record()

    publishers = {
        "DataONE":
            {
                "@id": "https://www.dataone.org/",
                "@type": "Organization",
                "legalName": "DataONE",
                "Description": "A federated data network allowing access to science data"
            },
        "Globus":
            {
                "@id": "https://www.materialsdatafacility.org/",
                "@type": "Organization",
                "legalName": "Materials Data Facility",
                "Description": "A simple way to publish, discover, and access materials datasets"
            }
    }

    def validate(self):
        """
        Checks for the presence of required tale information so
        that we can fail early.
        """
        try:
            # Check that each author has an ORCID, first name, and last name
            for author in self.tale['authors']:
                if not len(author['orcid']):
                    raise ValueError('A Tale author is missing an ORCID')
                if not len(author['firstName']):
                    raise ValueError('A Tale author is missing a first name')
                if not len(author['lastName']):
                    raise ValueError('A Tale author is missing a last name')
        except KeyError:
            raise ValueError('A Tale author is missing an ORCID')

    def create_basic_attributes(self):
        """
        Returns a portion of basic attributes in the manifest
        :return: Basic information about the Tale
        """

        return {
            "@id": f"https://data.wholetale.org/api/v1/tale/{self.tale['_id']}",
            "@type": "wt:Tale",
            "createdOn": str(self.tale["created"]),
            "schema:keywords": self.tale["category"],
            "schema:description": self.tale.get("description", ""),
            "wt:identifier": str(self.tale["_id"]),
            "schema:image": self.tale["illustration"],
            "schema:name": self.tale["title"],
            "schema:schemaVersion": self.tale["format"],
            "aggregates": list(),
            "wt:usesDataset": list(),
        }

    def add_tale_creator(self):
        """
        Adds basic information about the Tale author
        """

        tale_user = self.userModel.load(self.tale['creatorId'],
                                        user=self.user,
                                        force=True)
        self.manifest['createdBy'] = {
            "@id": f"mailto:{tale_user['email']}",
            "@type": "schema:Person",
            "schema:givenName": tale_user.get('firstName', ''),
            "schema:familyName": tale_user.get('lastName', ''),
            "schema:email": tale_user.get('email', '')
        }

    def create_author_record(self):
        """
        Creates records for authors that are associated with a Tale
        :return: A dictionary listing of the authors
        """
        return {
            'schema:author': [
                {
                    "@id": author["orcid"],
                    "@type": "schema:Person",
                    "schema:givenName": author["firstName"],
                    "schema:familyName": author["lastName"]
                }
                for author in self.tale['authors']
            ]
        }

    def create_repo2docker_version(self):
        # TODO: We shouldn't be publishing a Tale that was never built...
        image_info = self.tale.get("imageInfo", {})
        image_info.setdefault("repo2docker_version", REPO2DOCKER_VERSION)
        return {
            'schema:hasPart': [{
                '@id': 'https://github.com/whole-tale/repo2docker_wholetale',
                '@type': 'schema:SoftwareApplication',
                'schema:softwareVersion': image_info['repo2docker_version']
            }]
        }

    def create_related_identifiers(self):
        def derive_id_type(identifier):
            if identifier.lower().startswith("doi"):
                return "dc:DOI"
            elif identifier.lower().startswith("http"):
                return "dc:URL"
            elif identifier.lower().startswith("urn"):
                return "dc:URN"

        return {
            "dc:relatedIdentifiers": [
                {
                    "dc:relatedIdentifier": {
                        "@id": rel_id["identifier"],
                        "dc:relationType": "dc:" + rel_id["relation"],
                        "dc:relatedIdentifierType": derive_id_type(rel_id["identifier"]),
                    }
                }
                for rel_id in self.tale["relatedIdentifiers"]
            ],
        }

    def create_context(self):
        """
        Creates the manifest namespace. When a new vocabulary is used, it should
        get added here.
        :return: A structure defining the used vocabularies
        """
        return {
            "@context": [
                "https://w3id.org/bundle/context",
                {"schema": "http://schema.org/"},
                {"dc": "http://datacite.org/schema/kernel-4"},
                {"wt": "https://vocabularies.wholetale.org/wt/1.0/wt#"},
            ]
        }

    def create_dataset_record(self, folder_id):
        """
        Creates a record that describes a Dataset
        :param folder_id: Folder that represents a dataset
        :return: Dictionary that describes a dataset
        """
        try:
            folder = Folder().load(
                folder_id, user=self.user, exc=True, level=AccessType.READ
            )
            provider = folder['meta']['provider']
            if provider in {'HTTP', 'HTTPS'}:
                return None
            identifier = folder['meta']['identifier']
            return {
                "@id": identifier,
                "@type": "schema:Dataset",
                "schema:name": folder['name'],
                "schema:identifier": identifier,
                # "publisher": self.publishers[provider]
            }

        except (KeyError, TypeError, ValidationException):
            msg = 'While creating a manifest for Tale "{}" '.format(str(self.tale['_id']))
            msg += 'encountered a following error:\n'
            logger.warning(msg)
            raise  # We don't want broken manifests, do we?

    def create_aggregation_record(self, uri, bundle=None, parent_dataset_identifier=None):
        """
        Creates an aggregation record. Externally defined aggregations should include
        a bundle and a parent_dataset if it belongs to one
        :param uri: The item's URI in the manifest, typically it's path
        :param bundle: An optional bundle that's needed for externally defined data
        :param parent_dataset_identifier: The ID of an optional parent dataset
        :return: Dictionary representing an aggregated file
        """
        aggregation = dict()
        aggregation['uri'] = uri
        if bundle:
            aggregation['bundledAs'] = bundle
        # TODO: in case parent_dataset_id == uri do something special?
        if parent_dataset_identifier and parent_dataset_identifier != uri:
            aggregation['schema:isPartOf'] = parent_dataset_identifier
        return aggregation

    def add_tale_records(self):
        """
        Creates and adds file records to the internal manifest object for an entire Tale.
        """

        # Handle the files in the workspace
        workspace = Folder().load(
            self.tale["workspaceId"], user=self.user, level=AccessType.READ
        )
        if workspace and "fsPath" in workspace:
            workspace_rootpath = workspace["fsPath"]
            if not workspace_rootpath.endswith("/"):
                workspace_rootpath += "/"

            for curdir, _, files in os.walk(workspace_rootpath):
                for fname in files:
                    wfile = os.path.join(curdir, fname).replace(workspace_rootpath, "")
                    self.manifest['aggregates'].append({'uri': './workspace/' + wfile})

        """
        Handle objects that are in the dataSet, ie files that point to external sources.
        Some of these sources may be datasets from publishers. We need to save information
        about the source so that they can added to the wt:usesDataset section.
        """
        external_objects, dataset_top_identifiers = self._parse_dataSet()

        # Add records of all top-level dataset identifiers that were used in the Tale:
        # "wt:usesDataset"
        for identifier in dataset_top_identifiers:
            # Assuming Folder model implicitly ignores "datasets" that are
            # single HTTP files which is intended behavior
            for folder in Folder().findWithPermissions(
                    {'meta.identifier': identifier}, limit=1, user=self.user
            ):
                self.datasets.add(folder['_id'])

        # Add records for the remote files that exist under a folder: "aggregates"
        for obj in external_objects:
            # Grab identifier of a parent folder
            if obj['_modelType'] == 'item':
                bundle = self.create_bundle(obj["relpath"], obj["name"])
            else:
                bundle = self.create_bundle(obj["name"], None)
            record = self.create_aggregation_record(obj['uri'], bundle, obj['dataset_identifier'])
            record["wt:size"] = obj["size"]
            record["wt:identifier"] = obj["wt:identifier"]
            self.manifest['aggregates'].append(record)

    def _expand_folder_into_items(self, folder, user, relpath=''):
        """
        Recursively handle data folder and return all child items as ext objs

        In a perfect world there should be a better place for this...
        """
        curpath = os.path.join(relpath, folder['name'])
        dataSet = []
        ext = []
        for item in Folder().childItems(folder, user=user):
            dataSet.append({
                'itemId': item['_id'],
                '_modelType': 'item',
                'mountPath': os.path.join(curpath, item['name'])
            })

        if dataSet:
            ext, _ = self._parse_dataSet(dataSet=dataSet, relpath=curpath)

        for subfolder in Folder().childFolders(
            folder, parentType='folder', user=user
        ):
            ext += self._expand_folder_into_items(subfolder, user, relpath=curpath)
        return ext

    def _parse_dataSet(self, dataSet=None, relpath=''):
        """
        Get the basic info about the contents of `dataSet`

        Returns:
            external_objects: A list of objects that represent externally defined data
            dataset_top_identifiers: A set of DOIs for top-level packages that contain
                objects from external_objects

        """
        if dataSet is None:
            dataSet = self.tale['dataSet']

        dataset_top_identifiers = set()
        external_objects = []
        for obj in dataSet:
            try:
                doc = ModelImporter.model(obj['_modelType']).load(
                    obj['itemId'], user=self.user, level=AccessType.READ, exc=True)
                provider_name = doc['meta']['provider']
                if provider_name.startswith('HTTP'):
                    provider_name = 'HTTP'  # TODO: handle HTTPS to make it unnecessary
                provider = IMPORT_PROVIDERS.providerMap[provider_name]
                top_identifier = provider.getDatasetUID(doc, self.user)
                if top_identifier:
                    dataset_top_identifiers.add(top_identifier)

                ext_obj = {
                    'dataset_identifier': top_identifier,
                    'provider': provider_name,
                    '_modelType': obj['_modelType'],
                    'relpath': relpath,
                    "wt:identifier": str(doc["_id"]),
                }

                if obj['_modelType'] == 'folder':
                    is_root_folder = doc['meta'].get('identifier') == top_identifier
                    try:
                        if is_root_folder:
                            uri = top_identifier
                        else:
                            uri = provider.getURI(doc, self.user)
                    except NotImplementedError:
                        uri = None

                    if uri is None and self.expand_folders and not is_root_folder:
                        external_objects += self._expand_folder_into_items(doc, self.user)
                        continue

                    ext_obj['uri'] = uri or "undefined"
                    ext_obj['name'] = doc['name']
                    ext_obj['size'] = 0
                    for _, f in Folder().fileList(
                        doc, user=self.user, subpath=False, data=False
                    ):
                        ext_obj['size'] += f['size']

                elif obj['_modelType'] == 'item':
                    fileObj = self.itemModel.childFiles(doc)[0]
                    ext_obj.update({
                        'name': fileObj['name'],
                        'uri': fileObj['linkUrl'],
                        'size': fileObj['size']
                    })
                external_objects.append(ext_obj)
            except (ValidationException, KeyError):
                msg = 'While creating a manifest for Tale "{}" '.format(str(self.tale['_id']))
                msg += 'encountered a following error:\n'
                logger.warning(msg)
                raise  # We don't want broken manifests, do we?

        return external_objects, dataset_top_identifiers

    def add_dataset_records(self):
        """
        Adds dataset records to the manifest document
        :return: None
        """
        for folder_id in self.datasets:
            dataset_record = self.create_dataset_record(folder_id)
            if dataset_record:
                self.manifest["wt:usesDataset"].append(dataset_record)

    def create_bundle(self, folder, filename):
        """
        Creates a bundle for an externally referenced file
        :param folder: The name of the folder that the file is in
        :param filename:  The name of the file
        :return: A dictionary record of the bundle
        """
        folder = quote(os.path.join("./data", folder))
        # Add a trailing slash to the path if there isn't one (RO spec)
        if not folder.endswith('/'):
            folder += '/'
        bundle = dict(folder=folder)
        if filename:
            bundle['filename'] = quote(filename)
        return bundle

    def add_license_record(self):
        """
        Adds a record for the License file. When exporting to a bag, this gets placed
        in their data/ folder.
        """
        license = self.tale.get('licenseSPDX', WholeTaleLicense.default_spdx())
        self.manifest['aggregates'].append(
            {'uri': './LICENSE', 'schema:license': license}
        )

    def dump_manifest(self, **kwargs):
        return json.dumps(
            self.manifest,
            cls=JsonEncoder,
            sort_keys=True,
            allow_nan=False,
            **kwargs
        )

    def dump_environment(self, **kwargs):
        image = self.imageModel.load(
            self.tale["imageId"], user=self.user, level=AccessType.READ
        )
        image["taleConfig"] = self.tale.get("config", {})
        return json.dumps(
            self.imageModel.filter(image, self.user),
            cls=JsonEncoder,
            sort_keys=True,
            allow_nan=False,
            **kwargs
        )


def get_folder_identifier(folder_id, user):
    """
    Gets the 'identifier' field out of a folder. If it isn't present in the
    folder, it will navigate to the folder above until it reaches the collection
    :param folder_id: The ID of the folder
    :param user: The user that is creating the manifest
    :return: The identifier of a dataset
    """
    try:
        folder = ModelImporter.model('folder').load(folder_id,
                                                    user=user,
                                                    level=AccessType.READ,
                                                    exc=True)

        meta = folder.get('meta')
        if meta:
            if meta['provider'] in {'HTTP', 'HTTPS'}:
                return None
            identifier = meta.get('identifier')
            if identifier:
                return identifier

        get_folder_identifier(folder['parentID'], user)

    except (ValidationException, KeyError):
        pass
