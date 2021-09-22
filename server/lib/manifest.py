import json
import os
from urllib.parse import quote

from girder import logger
from girder.models.item import Item
from girder.models.folder import Folder
from girder.models.user import User
from girder.utility import JsonEncoder
from girder.utility.model_importer import ModelImporter
from girder.exceptions import ValidationException
from girder.constants import AccessType
from gwvolman.constants import REPO2DOCKER_VERSION

from .license import WholeTaleLicense
from . import IMPORT_PROVIDERS
from ..constants import RAW_DATA_PROVIDERS


class Manifest:
    """
    Class that represents the manifest file.
    Methods that add information to the manifest file have the form
    add_<someProperty>
    while methods that create chunks of the manifest have the form
    create<someProperty>
    """

    def __init__(self, tale, user, expand_folders=True, versionId=None):
        """
        Initialize the manifest document with base variables
        :param tale: The Tale whose data is being serialized
        :param user: The user requesting the manifest document
        :param expand_folders: If True, when encountering a folder
            in the external data, return all child items recursively.
        """
        self.tale = tale
        self.user = user
        if versionId is not None:
            version = Folder().load(
                versionId, user=self.user, level=AccessType.READ, exc=True
            )
            version = Folder().filter(version, user)  # to get _modelType
        else:
            version = tale
            version["_modelType"] = "tale"
            version["name"] = tale["title"]
        self.version = version
        self.expand_folders = expand_folders

        self.validate()
        self.manifest = dict()
        # Create a set that represents any external data packages
        self.datasets = set()

        self.imageModel = ModelImporter.model("image", "wholetale")
        self.userModel = ModelImporter.model("user")

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
        self.add_version_info()
        self.add_run_info()

    publishers = {
        "DataONE": {
            "@id": "https://www.dataone.org/",
            "@type": "Organization",
            "legalName": "DataONE",
            "Description": "A federated data network allowing access to science data",
        },
        "Globus": {
            "@id": "https://www.materialsdatafacility.org/",
            "@type": "Organization",
            "legalName": "Materials Data Facility",
            "Description": "A simple way to publish, discover, and access materials datasets",
        },
    }

    def validate(self):
        """
        Checks for the presence of required tale information so
        that we can fail early.
        """
        try:
            # Check that each author has an ORCID, first name, and last name
            for author in self.tale["authors"]:
                if not len(author["orcid"]):
                    raise ValueError("A Tale author is missing an ORCID")
                if not len(author["firstName"]):
                    raise ValueError("A Tale author is missing a first name")
                if not len(author["lastName"]):
                    raise ValueError("A Tale author is missing a last name")
        except KeyError:
            raise ValueError("A Tale author is missing an ORCID")

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
            "wt:hasRecordedRuns": list(),
        }

    def add_tale_creator(self):
        """
        Adds basic information about the Tale author
        """

        tale_user = self.userModel.load(
            self.tale["creatorId"], user=self.user, force=True
        )
        self.manifest["createdBy"] = {
            "@id": f"mailto:{tale_user['email']}",
            "@type": "schema:Person",
            "schema:givenName": tale_user.get("firstName", ""),
            "schema:familyName": tale_user.get("lastName", ""),
            "schema:email": tale_user.get("email", ""),
        }

    def create_author_record(self):
        """
        Creates records for authors that are associated with a Tale
        :return: A dictionary listing of the authors
        """
        return {
            "schema:author": [
                {
                    "@id": author["orcid"],
                    "@type": "schema:Person",
                    "schema:givenName": author["firstName"],
                    "schema:familyName": author["lastName"],
                }
                for author in self.tale["authors"]
            ]
        }

    def create_repo2docker_version(self):
        # TODO: We shouldn't be publishing a Tale that was never built...
        image_info = self.tale.get("imageInfo", {})
        image_info.setdefault("repo2docker_version", REPO2DOCKER_VERSION)
        return {
            "schema:hasPart": [
                {
                    "@id": "https://github.com/whole-tale/repo2docker_wholetale",
                    "@type": "schema:SoftwareApplication",
                    "schema:softwareVersion": image_info["repo2docker_version"],
                }
            ]
        }

    def create_related_identifiers(self):
        def derive_id_type(identifier):
            if identifier.lower().startswith("doi"):
                return "datacite:DOI"
            elif identifier.lower().startswith("http"):
                return "datacite:URL"
            elif identifier.lower().startswith("urn"):
                return "datacite:URN"

        return {
            "datacite:relatedIdentifiers": [
                {
                    "datacite:relatedIdentifier": {
                        "@id": rel_id["identifier"],
                        "datacite:relationType": "datacite:" + rel_id["relation"],
                        "datacite:relatedIdentifierType": derive_id_type(
                            rel_id["identifier"]
                        ),
                    }
                }
                for rel_id in self.tale["relatedIdentifiers"]
            ]
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
                {"datacite": "https://schema.datacite.org/meta/kernel-4.3/#"},
                {"wt": "https://vocabularies.wholetale.org/wt/1.0/"},
                {"@base": f"arcp://uid,{self.version['_id']}/data/"},
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
            provider = folder["meta"]["provider"]
            if self.is_external(provider):
                return None
            identifier = folder["meta"]["identifier"]
            return {
                "@id": identifier,
                "@type": "schema:Dataset",
                "schema:name": folder["name"],
                "schema:identifier": identifier,
                # "publisher": self.publishers[provider]
            }

        except (KeyError, TypeError, ValidationException):
            msg = 'While creating a manifest for Tale "{}" '.format(
                str(self.tale["_id"])
            )
            msg += "encountered a following error:\n"
            logger.warning(msg)
            raise  # We don't want broken manifests, do we?

    def create_aggregation_record(
        self, uri, bundle=None, parent_dataset_identifier=None
    ):
        """
        Creates an aggregation record. Externally defined aggregations should include
        a bundle and a parent_dataset if it belongs to one
        :param uri: The item's URI in the manifest, typically it's path
        :param bundle: An optional bundle that's needed for externally defined data
        :param parent_dataset_identifier: The ID of an optional parent dataset
        :return: Dictionary representing an aggregated file
        """
        aggregation = dict()
        aggregation["uri"] = uri
        if bundle:
            aggregation["bundledAs"] = bundle
        # TODO: in case parent_dataset_id == uri do something special?
        if parent_dataset_identifier and parent_dataset_identifier != uri:
            aggregation["schema:isPartOf"] = parent_dataset_identifier
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
                    self.manifest["aggregates"].append({"uri": "./workspace/" + wfile})

        # Handle raw data in data/ folder
        def walkdir(folder, path):
            logger.warning(f"walkdir({folder['_id']}, {path})")
            for item in Folder().childItems(folder):
                yield item, path
            for child_folder in Folder().childFolders(folder, "folder", user=self.user):
                logger.warning(f"here, {child_folder['name']}, {child_folder['_id']}")
                yield from walkdir(
                    child_folder, os.path.join(path, child_folder["name"])
                )

        current_data_dir = self._get_data_dir()
        for (item, path) in walkdir(current_data_dir, ""):
            logger.warning(item)
            if item["meta"].get("provider", "unknown") in RAW_DATA_PROVIDERS:
                self.manifest["aggregates"].append(
                    {"uri": os.path.join("./data", path, item["name"])}
                )

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
                {"meta.identifier": identifier}, limit=1, user=self.user
            ):
                self.datasets.add(folder["_id"])

        # Add records for the remote files that exist under a folder: "aggregates"
        for obj in external_objects:
            # Grab identifier of a parent folder
            if obj["_modelType"] == "item":
                bundle = self.create_bundle(obj["relpath"], obj["name"])
            else:
                bundle = self.create_bundle(obj["name"], None)
            record = self.create_aggregation_record(
                obj["uri"], bundle, obj["dataset_identifier"]
            )
            record["wt:size"] = obj["size"]
            record["wt:identifier"] = obj["wt:identifier"]
            self.manifest["aggregates"].append(record)

        # Add records for files in each recorded_run
        for run in Folder().find({'parentId': self.tale['runsRootId'], 'parentCollection': 'folder',
                                  'runVersionId': self.version['_id']}):
            run_rootpath = run["fsPath"]
            if not run_rootpath.endswith("/"):
                run_rootpath += "/"
            run_rootpath += "/workspace/"

            for curdir, _, files in os.walk(run_rootpath):
                for fname in files:
                    rfile = os.path.join(curdir, fname).replace(run_rootpath, run['name'] + "/")
                    rinfo = {
                        'uri': './runs/' + rfile,
                        'wt:isPartOfRun': (
                            "https://data.wholetale.org/api/v1/"
                            f"folder/{run['_id']}"
                        )
                    }
                    self.manifest['aggregates'].append(rinfo)

    @staticmethod
    def is_external(provider):
        return provider.upper() in {"HTTP", "HTTPS"} | {
            _.upper() for _ in RAW_DATA_PROVIDERS
        }

    def _parse_dataSet(self, relpath="", data_dir=None):
        """
        Get the basic info about the contents of `dataSet`

        Returns:
            external_objects: A list of objects that represent externally defined data
            dataset_top_identifiers: A set of DOIs for top-level packages that contain
                objects from external_objects

        """

        if data_dir is None:
            data_dir = self._get_data_dir()
        dataset_top_identifiers = set()
        external_objects = []

        for item in Folder().childItems(folder=data_dir):
            provider_name = item["meta"]["provider"]
            if self.is_external(provider_name):
                continue
            provider = IMPORT_PROVIDERS.providerMap[provider_name]
            if top_identifier := provider.getDatasetUID(item, self.user):
                dataset_top_identifiers.add(top_identifier)

            fileObj = Item().childFiles(item)[0]
            external_objects.append(
                {
                    "dataset_identifier": top_identifier,
                    "provider": provider_name,
                    "_modelType": "item",
                    "relpath": relpath,
                    "wt:identifier": str(item["_id"]),
                    "name": fileObj["name"],
                    "uri": fileObj["linkUrl"],
                    "size": fileObj["size"],
                }
            )

        for folder in Folder().childFolders(data_dir, "folder", user=self.user):
            provider_name = folder["meta"]["provider"]
            if self.is_external(provider_name):
                continue
            provider = IMPORT_PROVIDERS.providerMap[provider_name]
            if top_identifier := provider.getDatasetUID(folder, self.user):
                dataset_top_identifiers.add(top_identifier)
            try:
                is_root_folder = folder["meta"].get("identifier") == top_identifier

                if is_root_folder:
                    uri = top_identifier
                else:
                    uri = provider.getURI(folder, self.user)
            except NotImplementedError:
                uri = None

            if uri is None and self.expand_folders and not is_root_folder:
                child_external_objects, child_top_ids = self._parse_dataSet(
                    relpath=os.path.join(relpath, folder["name"]), data_dir=folder
                )
                dataset_top_identifiers |= child_top_ids
                external_objects += child_external_objects
                continue

            total_size = 0
            for _, f in Folder().fileList(
                folder, user=self.user, subpath=False, data=False
            ):
                total_size += f["size"]

            external_objects.append(
                {
                    "dataset_identifier": top_identifier,
                    "provider": provider_name,
                    "_modelType": "folder",
                    "relpath": relpath,
                    "wt:identifier": str(folder["_id"]),
                    "name": folder["name"],
                    "uri": uri or "undefined",
                    "size": total_size,
                }
            )

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
        if not folder.endswith("/"):
            folder += "/"
        bundle = dict(folder=folder)
        if filename:
            bundle["filename"] = quote(filename)
        return bundle

    def add_license_record(self):
        """
        Adds a record for the License file. When exporting to a bag, this gets placed
        in their data/ folder.
        """
        license = self.tale.get("licenseSPDX", WholeTaleLicense.default_spdx())
        self.manifest["aggregates"].append(
            {"uri": "./LICENSE", "schema:license": license}
        )

    def add_version_info(self):
        """Adds version metadata."""
        user = self.userModel.load(self.version["creatorId"], force=True)
        self.manifest["dct:hasVersion"] = {
            "@id": (
                "https://data.wholetale.org/api/v1/"
                f"{self.version['_modelType']}/{self.version['_id']}"
            ),
            "@type": "wt:TaleVersion",
            "schema:name": self.version["name"],
            "schema:dateModified": self.version[
                "created"
            ],  # FIXME: should it be updated?
            "schema:creator": {
                "@id": f"mailto:{user['email']}",
                "@type": "schema:Person",
                "schema:givenName": user["firstName"],
                "schema:familyName": user["lastName"],
                "schema:email": user["email"],
            },
        }

    def add_run_info(self):
        """Adds recorded run metadata."""

        for run in Folder().find({'parentId': self.tale['runsRootId'], 'parentCollection': 'folder',
                                  'runVersionId': self.version['_id']}):
            creator = User().load(run["creatorId"], force=True)
            run = {
                "@id": (
                    "https://data.wholetale.org/api/v1/"
                    f"folder/{run['_id']}"
                ),
                "@type": "wt:RecordedRun",
                "schema:name": run["name"],
                "schema:dateModified": run["created"],
                "schema:creator": {
                    "@id": f"mailto:{creator['email']}",
                    "@type": "schema:Person",
                    "schema:givenName": creator["firstName"],
                    "schema:familyName": creator["lastName"],
                    "schema:email": creator["email"],
                }
            }
            self.manifest['wt:hasRecordedRuns'].append(run)

    def dump_manifest(self, **kwargs):
        return json.dumps(
            self.manifest, cls=JsonEncoder, sort_keys=True, allow_nan=False, **kwargs
        )

    def get_environment(self):
        image = self.imageModel.load(
            self.tale["imageId"], user=self.user, level=AccessType.READ
        )
        # Filter, but keep in mind it removes extra keywords, so we need to add
        # extra stuff like 'taleConfig' afterwards.
        image = self.imageModel.filter(image, self.user)
        image["taleConfig"] = self.tale.get("config", {})
        return image

    def dump_environment(self, **kwargs):
        return json.dumps(
            self.get_environment(),
            cls=JsonEncoder,
            sort_keys=True,
            allow_nan=False,
            **kwargs,
        )

    def _get_data_dir(self):
        data_dir = Folder().load(
            self.tale["dataDirId"], user=self.user, level=AccessType.READ
        )
        try:
            return Folder().childFolders(
                data_dir, "folder", user=self.user, filters={"name": str(self.version["_id"])}
            )[0]
        except IndexError:  # No version yet...
            return Folder().childFolders(
                data_dir, "folder", user=self.user, filters={"name": "current"}
            )[0]


def get_folder_identifier(folder_id, user):
    """
    Gets the 'identifier' field out of a folder. If it isn't present in the
    folder, it will navigate to the folder above until it reaches the collection
    :param folder_id: The ID of the folder
    :param user: The user that is creating the manifest
    :return: The identifier of a dataset
    """
    try:
        folder = ModelImporter.model("folder").load(
            folder_id, user=user, level=AccessType.READ, exc=True
        )
        if "originalId" in folder["meta"]:
            get_folder_identifier(folder["meta"]["originalId"], user)

        meta = folder.get("meta")
        if meta:
            if meta["provider"] in {"HTTP", "HTTPS"}:
                return None
            identifier = meta.get("identifier")
            if identifier:
                return identifier

        get_folder_identifier(folder["parentId"], user)

    except (ValidationException, KeyError):
        pass
