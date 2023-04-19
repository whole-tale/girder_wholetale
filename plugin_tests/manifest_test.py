import mock
import copy
import json
from operator import itemgetter
import os
import pytest
from tests import base
from bson import ObjectId
from girder.exceptions import AccessException, ValidationException
from girder.utility.path import lookUpPath


def setUpModule():
    base.enabledPlugins.append("virtual_resources")
    base.enabledPlugins.append("wholetale")
    base.enabledPlugins.append("wt_home_dir")
    base.enabledPlugins.append("wt_versioning")
    base.startServer()


def tearDownModule():
    base.stopServer()


DATA_PATH = os.path.join(
    os.path.dirname(os.environ["GIRDER_TEST_DATA_PREFIX"]),
    "data_src",
    "plugins",
    "wholetale",
)


class ManifestTestCase(base.TestCase):
    def setUp(self):
        super(ManifestTestCase, self).setUp()
        global catalog_ready
        self.users = (
            {
                "email": "root@dev.null",
                "login": "admin",
                "firstName": "Root",
                "lastName": "van Klompf",
                "password": "secret",
                "admin": True,
            },
            {
                "email": "joe@dev.null",
                "login": "joeregular",
                "firstName": "Joe",
                "lastName": "Regular",
                "password": "secret",
            },
            {
                "email": "henry@dev.null",
                "login": "henryCoolLogin",
                "firstName": "Henry",
                "lastName": "CoolLast",
                "password": "secret1",
            },
        )
        self.admin, self.user, self.userHenry = [
            self.model("user").createUser(**user) for user in self.users
        ]

        self.new_authors = [
            {
                "firstName": self.admin["firstName"],
                "lastName": self.admin["lastName"],
                "orcid": "https://orcid.org/1234",
            },
            {
                "firstName": self.user["firstName"],
                "lastName": self.user["lastName"],
                "orcid": "https://orcid.org/9876",
            },
        ]

        data_collection = self.model("collection").createCollection(
            "WholeTale Catalog", public=True, reuseExisting=True
        )
        catalog = self.model("folder").createFolder(
            data_collection,
            "WholeTale Catalog",
            parentType="collection",
            public=True,
            reuseExisting=True,
        )
        # Tale map of values to check against in tests

        def restore_catalog(parent, current):
            for folder in current["folders"]:
                resp = self.request(
                    path="/folder",
                    method="POST",
                    user=self.admin,
                    params={
                        "parentId": parent["_id"],
                        "name": folder["name"],
                        "metadata": json.dumps(folder["meta"]),
                    },
                )
                folderObj = resp.json
                restore_catalog(folderObj, folder)

            for obj in current["files"]:
                resp = self.request(
                    path="/item",
                    method="POST",
                    user=self.admin,
                    params={
                        "folderId": parent["_id"],
                        "name": obj["name"],
                        "metadata": json.dumps(obj["meta"]),
                    },
                )
                item = resp.json
                self.request(
                    path="/file",
                    method="POST",
                    user=self.admin,
                    params={
                        "parentType": "item",
                        "parentId": item["_id"],
                        "name": obj["name"],
                        "size": obj["size"],
                        "mimeType": obj["mimeType"],
                        "linkUrl": obj["linkUrl"],
                    },
                )

        with open(os.path.join(DATA_PATH, "manifest_mock_catalog.json"), "r") as fp:
            data = json.load(fp)
            restore_catalog(catalog, data)
        catalog_ready = True
        dataSet = []
        data_paths = [
            "Humans and Hydrology at High Latitudes: Water Use Information",  # D1 folder
            "Humans and Hydrology at High Latitudes: Water Use Information/usco2005.xls",  # D1 file
            "Twin-mediated Crystal Growth: an Enigma Resolved/data/D_whites_darks_AJS.hdf",  # Globus file
            "A Machine Learning Approach for  Engineering Bulk Metallic Glass Alloys/data/Dmax",  # Globus folder
            "gwosc.org/s/events/BBH_events_v3.json",  # HTTP file
            "gwosc.org/s/events/GW170104",  # HTTP folder
        ]
        root = "/collection/WholeTale Catalog/WholeTale Catalog"
        for path in data_paths:
            obj = lookUpPath(os.path.join(root, path))
            dataSet.append(
                {
                    "itemId": obj["document"]["_id"],
                    "mountPath": obj["document"]["name"],
                    "_modelType": obj["model"],
                }
            )

        self.tale_info = {
            "_id": ObjectId(),
            "name": "Main Tale",
            "description": "Tale Desc",
            "authors": self.new_authors,
            "creator": self.user,
            "public": True,
            "data": dataSet,
            "illustration": "linkToImage",
        }

        self.tale = self.model("tale", "wholetale").createTale(
            {"_id": self.tale_info["_id"]},
            data=self.tale_info["data"],
            creator=self.tale_info["creator"],
            title=self.tale_info["name"],
            public=self.tale_info["public"],
            description=self.tale_info["description"],
            authors=self.tale_info["authors"],
        )

        self.tale["imageInfo"] = {
            "digest": (
                "registry.local.wholetale.org/5c8fe826da39aa00013e9609/1552934951@"
                "sha256:4f604e6fab47f79e28251657347ca20ee89b737b4b1048c18ea5cf2fe9a9f098"
            ),
            "jobId": ObjectId("5c9009deda39aa0001d702b7"),
            "last_build": 1552943449,
            "repo2docker_version": "craigwillis/repo2docker:latest",
            "status": 3
        }
        self.model('tale', 'wholetale').save(self.tale)

        self.tale2 = self.model("tale", "wholetale").createTale(
            {"_id": self.tale_info["_id"]},
            data=[],
            creator=self.tale_info["creator"],
            title=self.tale_info["name"],
            public=self.tale_info["public"],
            description=self.tale_info["description"],
            authors=self.tale_info["authors"],
        )

    @mock.patch("gwvolman.build_utils.ImageBuilder")
    def testManifest(self, mock_builder):
        mock_builder.return_value.container_config.repo2docker_version = "craigwillis/repo2docker:latest"
        mock_builder.return_value.get_tag.return_value = \
            self.tale['imageInfo']['digest'].replace('registry', 'images', 1)
        self._testCreateBasicAttributes()
        self._testAddTaleCreator()
        self._testCreateContext()
        self._testCreateAggregationRecord()
        self._testGetFolderIdentifier()
        self._testDataSet()
        self._test_different_user()
        self._testWorkspace()
        self._testRelatedIdentifiers()
        self._testValidate()
        self._test_create_image_info()

    def _testRelatedIdentifiers(self):
        from server.lib.manifest import Manifest
        from girder.plugins.wholetale.models.tale import Tale

        tale = copy.deepcopy(self.tale)
        tale.pop("_id")
        tale["relatedIdentifiers"] = [
            {"identifier": "urn:some_urn", "relation": "cites"}
        ]
        with pytest.raises(ValidationException) as exc:
            tale = Tale().save(tale)
        self.assertTrue(str(exc.value).startswith("'cites' is not one of"))

        tale["relatedIdentifiers"] = [
            {"identifier": "urn:some_urn", "relation": "Cites"},
            {"identifier": "doi:some_doi", "relation": "IsDerivedFrom"},
            {"identifier": "https://some.url", "relation": "IsIdenticalTo"},
        ]
        tale = Tale().save(tale)
        manifest = Manifest(tale, self.user)
        attrs = manifest.create_related_identifiers()
        self.assertIn("datacite:relatedIdentifiers", attrs)
        self.assertEqual(
            attrs["datacite:relatedIdentifiers"],
            [
                {
                    "datacite:relatedIdentifier": {
                        "@id": "urn:some_urn",
                        "datacite:relationType": "datacite:Cites",
                        "datacite:relatedIdentifierType": "datacite:URN",
                    }
                },
                {
                    "datacite:relatedIdentifier": {
                        "@id": "doi:some_doi",
                        "datacite:relationType": "datacite:IsDerivedFrom",
                        "datacite:relatedIdentifierType": "datacite:DOI",
                    }
                },
                {
                    "datacite:relatedIdentifier": {
                        "@id": "https://some.url",
                        "datacite:relationType": "datacite:IsIdenticalTo",
                        "datacite:relatedIdentifierType": "datacite:URL",
                    }
                },
            ],
        )
        Tale().remove(tale)

    def _testCreateBasicAttributes(self):
        # Test that the basic attributes are correct
        from server.lib.manifest import Manifest

        manifest_doc = Manifest(self.tale, self.user)

        attributes = manifest_doc.create_basic_attributes()
        self.assertEqual(attributes["wt:identifier"], str(self.tale["_id"]))
        self.assertEqual(attributes["schema:name"], self.tale["title"])
        self.assertEqual(attributes["schema:description"], self.tale["description"])
        self.assertEqual(attributes["schema:keywords"], self.tale["category"])
        self.assertEqual(attributes["schema:schemaVersion"], self.tale["format"])
        self.assertEqual(attributes["schema:image"], self.tale["illustration"])

    def _testAddTaleCreator(self):
        from server.lib.manifest import Manifest

        manifest_doc = Manifest(self.tale, self.user)
        manifest_creator = manifest_doc.manifest["createdBy"]
        self.assertEqual(manifest_creator["schema:givenName"], self.user["firstName"])
        self.assertEqual(manifest_creator["schema:familyName"], self.user["lastName"])
        self.assertEqual(manifest_creator["schema:email"], self.user["email"])
        self.assertEqual(manifest_creator["@id"], self.tale["authors"])

    def _testCreateContext(self):
        # Rather than check the contents of the context (subject to change), check that we
        # get a dict back
        from server.lib.manifest import Manifest

        manifest_doc = Manifest(self.tale, self.user)
        context = manifest_doc.create_context()
        self.assertEqual(type(context), type(dict()))

    def _testCreateAggregationRecord(self):
        from server.lib.manifest import Manifest

        # Test without a bundle
        manifest_doc = Manifest(self.tale, self.user)
        uri = "doi:xx.xxxx.1234"
        agg = manifest_doc.create_aggregation_record(uri)
        self.assertEqual(agg["uri"], uri)

        # Test with a bundle
        folder_name = "research_data"
        filename = "data.csv"
        bundle = {"folder": folder_name, "filename": filename}

        agg = manifest_doc.create_aggregation_record(uri, bundle)
        self.assertEqual(agg["uri"], uri)
        self.assertEqual(agg["bundledAs"]["folder"], folder_name)
        self.assertEqual(agg["bundledAs"]["filename"], filename)

        # Test with a parent dataset
        parent_dataset = "urn:uuid:100.99.xx"
        agg = manifest_doc.create_aggregation_record(uri, bundle, parent_dataset)
        self.assertEqual(agg["schema:isPartOf"], parent_dataset)

    def _testAddTaleCreator(self):
        from server.lib.manifest import Manifest

        manifest_doc = Manifest(self.tale, self.user)
        self.assertTrue(len(manifest_doc.manifest["schema:author"]))

    def _testGetFolderIdentifier(self):
        from server.lib.manifest import get_folder_identifier

        folder_identifier = get_folder_identifier(
            self.tale["dataSet"][0]["itemId"], self.user
        )
        self.assertEqual(folder_identifier, "doi:10.5065/D6862DM8")

    def _testWorkspace(self):
        from server.lib.manifest import Manifest
        workspace = self.model("folder").load(self.tale["workspaceId"], force=True)
        fspath = workspace["fsPath"]
        with open(os.path.join(fspath, "file1.csv"), "w") as f:
            f.write("1,2,3,4\n")

        manifest_doc = Manifest(self.tale, self.user)
        aggregates_section = manifest_doc.manifest["aggregates"]

        # Search for workspace file1.csv
        expected_path = "./workspace/" + "file1.csv"
        file_check = any(x for x in aggregates_section if (x["uri"] == expected_path))
        self.assertTrue(file_check)
        os.remove(os.path.join(fspath, "file1.csv"))

    def _testDataSet(self):
        from server.lib.manifest import Manifest

        # Test that all of the files in the dataSet are added
        with open(os.path.join(DATA_PATH, "reference_dataset.json"), "r") as fp:
            reference_aggregates = json.load(fp)

        reference_aggregates = sorted(reference_aggregates, key=itemgetter("uri"))
        for d in reference_aggregates:
            if "wt:identifier" in d:
                d.pop("wt:identifier")
        manifest_doc = Manifest(self.tale, self.user, expand_folders=True)
        tale_dataset_ids = {str(_["itemId"]) for _ in self.tale["dataSet"]}
        for i, aggregate in enumerate(
            sorted(manifest_doc.manifest["aggregates"], key=itemgetter("uri"))
        ):
            if "wt:identifier" in aggregate:
                aggregate.pop("wt:identifier")
            self.assertDictEqual(aggregate, reference_aggregates[i])

        # Check the datasets
        reference_datasets = [
            {
                "@id": "doi:10.18126/M2662X",
                "@type": "schema:Dataset",
                "schema:name": "A Machine Learning Approach for  Engineering Bulk Metallic Glass Alloys",
                "schema:identifier": "doi:10.18126/M2662X",
            },
            {
                "@id": "doi:10.18126/M2301J",
                "@type": "schema:Dataset",
                "schema:name": "Twin-mediated Crystal Growth: an Enigma Resolved",
                "schema:identifier": "doi:10.18126/M2301J",
            },
            {
                "@id": "doi:10.5065/D6862DM8",
                "@type": "schema:Dataset",
                "schema:name": "Humans and Hydrology at High Latitudes: Water Use Information",
                "schema:identifier": "doi:10.5065/D6862DM8",
            },
        ]

        reference_datasets = sorted(reference_datasets, key=itemgetter("@id"))
        for i, dataset in enumerate(
            sorted(manifest_doc.manifest["wt:usesDataset"], key=itemgetter("@id"))
        ):
            self.assertDictEqual(dataset, reference_datasets[i])

    def _test_different_user(self):
        from server.lib.manifest import Manifest

        try:
            Manifest(self.tale, self.userHenry)
        except AccessException:
            self.assertFalse(1)

    def _testValidate(self):
        from server.lib.manifest import Manifest

        missing_orcid = {"firstName": "Lord", "lastName": "Kelvin"}
        blank_orcid = {"firstName": "Isaac", "lastName": "Newton", "orcid": ""}

        tale_missing_orcid = self.model("tale", "wholetale").createTale(
            {"_id": self.tale_info["_id"]},
            data=[],
            creator=self.tale_info["creator"],
            title=self.tale_info["name"],
            public=self.tale_info["public"],
            description=self.tale_info["description"],
            authors=[missing_orcid],
        )

        with self.assertRaises(ValueError):
            Manifest(tale_missing_orcid, self.user)

        tale_blank_orcid = self.model("tale", "wholetale").createTale(
            {"_id": self.tale_info["_id"]},
            data=[],
            creator=self.tale_info["creator"],
            title=self.tale_info["name"],
            public=self.tale_info["public"],
            description=self.tale_info["description"],
            authors=[blank_orcid],
        )
        with self.assertRaises(ValueError):
            Manifest(tale_blank_orcid, self.user)

    def _test_create_image_info(self):
        from server.lib.manifest import Manifest

        manifest = Manifest(self.tale, self.user).manifest
        self.assertTrue(len(manifest['schema:hasPart']))

        r2d_block = manifest['schema:hasPart'][0]
        self.assertEqual(r2d_block['schema:softwareVersion'],
                             self.tale["imageInfo"]['repo2docker_version'])
        self.assertEqual(r2d_block['@id'], 'https://github.com/whole-tale/repo2docker_wholetale')
        self.assertEqual(r2d_block['@type'], 'schema:SoftwareApplication')

        digest_block = manifest['schema:hasPart'][1]
        self.assertEqual(digest_block['@id'], self.tale['imageInfo']['digest'].replace('registry', 'images', 1))
        self.assertEqual(digest_block['schema:applicationCategory'], 'DockerImage')
        self.assertEqual(digest_block['@type'], 'schema:SoftwareApplication')

    def test_dataset_roundtrip(self):
        from server.lib.manifest_parser import ManifestParser
        from server.lib.manifest import Manifest
        manifest = Manifest(self.tale, self.user).manifest
        dataset = ManifestParser(manifest).get_dataset()
        self.assertEqual(
            [_["itemId"] for _ in dataset],
            [str(_["itemId"]) for _ in self.tale["dataSet"]]
        )

        # test it still works if schema:identifier is not present
        aggregates = []
        for obj in manifest["aggregates"]:
            if "schema:identifier" in obj:
                obj.pop("schema:identifier")
            aggregates.append(obj)
        manifest["aggregates"] = aggregates
        dataset = ManifestParser(manifest).get_dataset()
        self.assertEqual(
            [_["itemId"] for _ in dataset],
            [str(_["itemId"]) for _ in self.tale["dataSet"]]
        )

    def tearDown(self):
        self.model("user").remove(self.user)
        self.model("user").remove(self.admin)
        super(ManifestTestCase, self).tearDown()
