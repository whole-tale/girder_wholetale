import json
import os
import tempfile
import time
import zipfile
from pathlib import Path

import bdbag.bdbag_api as bdbag
from girder.models.folder import Folder
from girder.models.item import Item
from tests import base


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.enabledPlugins.append("wt_data_manager")
    base.enabledPlugins.append("virtual_resources")
    base.enabledPlugins.append("wt_versioning")
    base.enabledPlugins.append("wt_home_dir")
    base.startServer(mock=False)

    global JobStatus, Tale, ImageStatus
    from girder.plugins.jobs.constants import JobStatus
    from girder.plugins.wholetale.constants import ImageStatus
    from girder.plugins.wholetale.models.tale import Tale


def tearDownModule():
    base.stopServer()


class BDBagFullTestCase(base.TestCase):
    def setUp(self):
        super(BDBagFullTestCase, self).setUp()
        users = (
            {
                "email": "root@dev.null",
                "login": "admin",
                "firstName": "Root",
                "lastName": "van Klompf",
                "password": "secret",
            },
            {
                "email": "joe@dev.null",
                "login": "joeregular",
                "firstName": "Joe",
                "lastName": "Regular",
                "password": "secret",
            },
        )

        self.authors = [
            {
                "firstName": "Joe",
                "lastName": "Regular",
                "orcid": "https://orcid.org/000-000",
            },
        ]
        self.admin, self.user = [
            self.model("user").createUser(**user) for user in users
        ]

        self.image_admin = self.model("image", "wholetale").createImage(
            name="test admin image", creator=self.admin, public=True
        )

        self.image = self.model("image", "wholetale").createImage(
            name="test my name",
            creator=self.user,
            public=True,
            config=dict(
                template="base.tpl",
                buildpack="SomeBuildPack",
                user="someUser",
                port=8888,
                urlPath="",
                targetMount='/mount',
            ),
        )

    def testBDBagValidation(self):
        from girder.plugins.jobs.models.job import Job

        # Get a datamap for variety of sources (Zenodo, Dataverse, DataONE, http)
        dois = [
            "doi:10.7910/DVN/RLMYMR",
            "doi:10.18739/A23M1P",
            "doi:10.5281/zenodo.6038195",
            "https://www.gw-openscience.org/s/events/BBH_events_v3.json",
        ]

        resp = self.request(
            path="/repository/lookup",
            method="GET",
            user=self.user,
            params={"dataId": json.dumps(dois)},
        )
        self.assertStatus(resp, 200)
        self.assertEqual(
            sorted([_["repository"] for _ in resp.json]),
            sorted(["Dataverse", "DataONE", "Zenodo", "HTTP"]),
        )
        datamap = resp.json

        # Register data
        resp = self.request(
            path="/dataset/register",
            method="POST",
            params={"dataMap": json.dumps(datamap)},
            user=self.user,
        )
        self.assertStatusOk(resp)
        job = resp.json
        for _ in range(600):
            if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                break
            time.sleep(0.5)
            job = Job().load(job["_id"], force=True)
        self.assertEqual(job["status"], JobStatus.SUCCESS)

        # Create dataSet
        dataSet = []
        folder_name = (
            "Karnataka Diet Diversity and Food Security "
            "for Agricultural Biodiversity Assessment"
        )
        folder = Folder().findOne({"name": folder_name})
        dataSet.append(
            {
                "itemId": str(folder["_id"]),
                "mountPath": folder["name"],
                "_modelType": "folder",
            }
        )
        for item_name in ["treatment.html", "BBH_events_v3.json", "bg1314_bpr_a.dat"]:
            item = Item().findOne({"name": item_name})
            dataSet.append(
                {
                    "itemId": str(item["_id"]),
                    "mountPath": item["name"],
                    "_modelType": "item",
                }
            )
    
        # Fake imageInfo
        imageInfo = {
            "digest": "registry.local.wholetale.org/digest123"
        }

        # Create tale (use model directly to set imageInfo)
        from girder.plugins.wholetale.models.tale import Tale
        tale = Tale().createTale(
            image=self.image,
            data=dataSet,
            creator=self.user,
            imageInfo=imageInfo
        )

        # "Upload" something to workspace
        workspace = Folder().load(tale["workspaceId"], force=True)
        workspace_path = Path(workspace["fsPath"])
        with open(workspace_path / "apt.txt", "w") as fp:
            fp.write("vim\n")

        # Export!
        resp = self.request(
            path=f"/tale/{tale['_id']}/export",
            method="GET",
            isJson=False,
            user=self.user,
            params={"taleFormat": "bagit"},
        )
        self.assertStatusOk(resp)
        with tempfile.TemporaryDirectory() as tmpdirname:
            with tempfile.TemporaryFile() as fp:
                for content in resp.body:
                    fp.write(content)
                fp.seek(0)
                zip_archive = zipfile.ZipFile(fp, "r")
                manifest_path = next(
                    (_ for _ in zip_archive.namelist() if _.endswith("manifest.json"))
                )
                version_id = Path(manifest_path).parts[0]


                zip_archive.extractall(tmpdirname)
                zip_archive.close()

            bag_path = os.path.join(tmpdirname, version_id)
            # Fetch data
            self.assertTrue(bdbag.resolve_fetch(bag_path))
            bdbag.validate_bag(bag_path, fast=True)
            bdbag.validate_bag(bag_path, fast=False)

            # Confirm image digest.
            manifest_fs_path = os.path.join(bag_path, "metadata/manifest.json")
            with open(manifest_fs_path, 'r') as fp:
                manifest_json = json.load(fp)
                self.assertEqual(manifest_json["schema:hasPart"][1]["@id"], "images.local.wholetale.org/digest123")

            from server.lib.manifest_parser import ManifestParser
            tale_fields = ManifestParser(manifest_fs_path).get_tale_fields()
            self.assertEqual(tale_fields["imageInfo"]["digest"], "registry.local.wholetale.org/digest123")
