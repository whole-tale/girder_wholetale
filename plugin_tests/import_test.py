import json
import os
import shutil
import tarfile
import tempfile
import time
import zipfile
from datetime import datetime

import mock
import vcr
from bson import ObjectId
from fs.copy import copy_fs
from fs.osfs import OSFS
from girder import config
from girder.models.folder import Folder
from girder.utility.path import lookUpPath
from tests import base

from .tests_helpers import event_types, get_events

DATA_PATH = os.path.join(
    os.path.dirname(os.environ["GIRDER_TEST_DATA_PREFIX"]),
    "data_src",
    "plugins",
    "wholetale",
)


JobStatus = None
ImageStatus = None
Tale = None
os.environ["GIRDER_PORT"] = os.environ.get("GIRDER_TEST_PORT", "20200")
config.loadConfig()  # Must reload config to pickup correct port


class FakeAsyncResult(object):
    def __init__(self, tale_id=None):
        self.task_id = "fake_id"
        self.tale_id = tale_id

    def get(self, timeout=None):
        return {
            "image_digest": "digest123",
            "repo2docker_version": 1,
            "last_build": 123,
        }


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


class ImportTaleTestCase(base.TestCase):
    def setUp(self):
        super(ImportTaleTestCase, self).setUp()
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
                "firstName": "Charles",
                "lastName": "Darwmin",
                "orcid": "https://orcid.org/000-000",
            },
            {
                "firstName": "Thomas",
                "lastName": "Edison",
                "orcid": "https://orcid.org/111-111",
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
            ),
        )

        from girder.plugins.wt_home_dir import HOME_DIRS_APPS

        self.homeDirsApps = HOME_DIRS_APPS  # nopep8
        self.clearDAVAuthCache()

    def clearDAVAuthCache(self):
        # need to do this because the DB is wiped on every test, but the dav domain
        # controller keeps a cache with users/tokens
        for e in self.homeDirsApps.entries():
            e.app.config["domaincontroller"].clearCache()

    @vcr.use_cassette(os.path.join(DATA_PATH, "tale_import_data.txt"))
    def testTaleImport(self):
        image = self.model("image", "wholetale").createImage(
            name="Jupyter Classic",
            creator=self.user,
            public=True,
            config=dict(
                template="base.tpl",
                buildpack="PythonBuildPack",
                user="someUser",
                port=8888,
                urlPath="",
            ),
        )

        from girder.plugins.wholetale.constants import InstanceStatus

        class fakeInstance(object):
            _id = "123456789"

            def createInstance(self, tale, user, /, *, spawn=False):
                return {"_id": self._id, "status": InstanceStatus.LAUNCHING}

            def load(self, instance_id, user=None):
                assert instance_id == self._id
                return {"_id": self._id, "status": InstanceStatus.RUNNING}

        since = datetime.utcnow().isoformat()
        with mock.patch(
            "girder.plugins.wholetale.models.instance.Instance", fakeInstance
        ):
            resp = self.request(
                path="/tale/import",
                method="POST",
                user=self.user,
                params={
                    "url": (
                        "https://dataverse.harvard.edu/dataset.xhtml?"
                        "persistentId=doi:10.7910/DVN/3MJ7IR"
                    ),
                    "spawn": True,
                    "imageId": self.image["_id"],
                    "asTale": False,
                },
            )

            self.assertStatusOk(resp)
            tale = resp.json

            from girder.plugins.jobs.models.job import Job

            job = Job().findOne({"type": "wholetale.import_binder"})
            self.assertEqual(json.loads(job["kwargs"])["taleId"]["$oid"], tale["_id"])

            for _ in range(600):
                if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                    break
                time.sleep(0.1)
                job = Job().load(job["_id"], force=True)
            self.assertEqual(job["status"], JobStatus.SUCCESS)

        tale = Tale().load(tale["_id"], force=True)
        count = 0
        while not tale["dataSetCitation"]:
            time.sleep(0.5)
            tale = Tale().load(tale["_id"], force=True)
            count += 1
            if count > 10:
                break

        self.assertEqual(
            tale["dataSetCitation"],
            [
                (
                    "Rangel, M. A. and Vogl, T. (2018) “Replication Data for: ‘Agricultural "
                    "Fires and Health at Birth.’” Harvard Dataverse. doi: 10.7910/DVN/3MJ7IR."
                )
            ],
        )
        self.assertEqual(len(tale["dataSet"]), 1)

        # Confirm notifications
        events = get_events(self, since)
        self.assertEqual(
            {
                "wt_tale_created",
                "wt_import_started",
                "wt_tale_updated",
                "wt_import_completed",
            },
            event_types(events, {"taleId": str(tale["_id"])}),
        )
        self.model("image", "wholetale").remove(image)

    def testTaleImportBinder(self):
        since = datetime.utcnow().isoformat()

        def before_record_cb(request):
            if request.host == "localhost":
                return None
            return request

        my_vcr = vcr.VCR(before_record_request=before_record_cb)
        with my_vcr.use_cassette(os.path.join(DATA_PATH, "tale_import_binder.txt")):
            image = self.model("image", "wholetale").createImage(
                name="Jupyter Classic",
                creator=self.user,
                public=True,
                config=dict(
                    template="base.tpl",
                    buildpack="PythonBuildPack",
                    user="someUser",
                    port=8888,
                    urlPath="",
                ),
            )

            from girder.plugins.wholetale.constants import InstanceStatus

            class fakeInstance(object):
                _id = "123456789"

                def createInstance(self, tale, user, /, *, spawn=False):
                    return {"_id": self._id, "status": InstanceStatus.LAUNCHING}

                def load(self, instance_id, user=None):
                    assert instance_id == self._id
                    return {"_id": self._id, "status": InstanceStatus.RUNNING}

            with mock.patch(
                "girder.plugins.wholetale.models.instance.Instance", fakeInstance
            ):
                resp = self.request(
                    path="/tale/import",
                    method="POST",
                    user=self.user,
                    params={
                        "url": (
                            "https://dataverse.harvard.edu/dataset.xhtml?"
                            "persistentId=doi:10.7910/DVN/HOLVXA"
                        ),
                        "spawn": True,
                        "imageId": self.image["_id"],
                        "asTale": True,
                    },
                )

                self.assertStatusOk(resp)
                tale = resp.json

                from girder.plugins.jobs.models.job import Job

                job = Job().findOne({"type": "wholetale.import_binder"})
                self.assertEqual(
                    json.loads(job["kwargs"])["taleId"]["$oid"], tale["_id"]
                )

                for _ in range(600):
                    if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                        break
                    time.sleep(0.1)
                    job = Job().load(job["_id"], force=True)
                self.assertEqual(job["status"], JobStatus.SUCCESS)

        resp = self.request(
            path="/item",
            method="GET",
            user=self.user,
            params={"folderId": tale["workspaceId"]},
        )
        self.assertStatusOk(resp)
        self.assertEqual(
            sorted([_["name"] for _ in resp.json]),
            [
                "requirements.txt",
                "rnr-report-wordcloud.ipynb",
                "rnr.txt",
            ],
        )

        # Confirm notifications
        time.sleep(1)
        events = get_events(self, since)
        self.assertEqual(
            {"wt_tale_created", "wt_import_started", "wt_import_completed"},
            event_types(events, {"taleId": str(tale["_id"])}),
        )
        self.model("image", "wholetale").remove(image)

    @vcr.use_cassette(os.path.join(DATA_PATH, "tale_import_zip.txt"))
    @mock.patch("girder.plugins.wholetale.lib.manifest.ImageBuilder")
    def testTaleImportZip(self, mock_builder):
        mock_builder.return_value.container_config.repo2docker_version = \
            "craigwillis/repo2docker:latest"
        mock_builder.return_value.get_tag.return_value = \
            "some_image_digest"
        image = self.model("image", "wholetale").createImage(
            name="Jupyter Notebook",
            creator=self.user,
            public=True,
            config=dict(
                template="base.tpl",
                buildpack="PythonBuildPack",
                user="someUser",
                port=8888,
                urlPath="",
            ),
        )

        since = datetime.utcnow().isoformat()
        with open(
            os.path.join(DATA_PATH, "604126f45f6bb2c4c997e967.zip"), "rb"
        ) as fp:
            resp = self.request(
                path="/tale/import",
                method="POST",
                user=self.user,
                type="application/zip",
                body=fp.read(),
            )

        self.assertStatusOk(resp)
        tale = resp.json

        from girder.plugins.jobs.models.job import Job

        job = Job().findOne(
            {"type": "wholetale.import_tale", "taleId": ObjectId(tale["_id"])}
        )
        self.assertEqual(
            json.loads(job["kwargs"])["taleId"]["$oid"], tale["_id"]
        )
        for _ in range(600):
            if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                break
            time.sleep(0.1)
            job = Job().load(job["_id"], force=True)
        self.assertEqual(job["status"], JobStatus.SUCCESS)
        # TODO: make it more extensive...
        tale = Tale().load(tale["_id"], force=True)
        self.assertTrue(tale is not None)
        self.assertEqual(
            [(obj["_modelType"], obj["mountPath"]) for obj in tale["dataSet"]],
            [("item", "usco2005.xls")],
        )
        self.assertEqual(
            tale["imageInfo"]["repo2docker_version"],
            "wholetale/repo2docker_wholetale:latest"
        )

        events = get_events(self, since)
        self.assertEqual(
            {
                "wt_tale_created",
                "wt_import_started",
                "wt_tale_updated",
                "wt_import_completed",
            },
            event_types(events, {"taleId": str(tale["_id"])}),
        )
        self.model("image", "wholetale").remove(image)

    @vcr.use_cassette(os.path.join(DATA_PATH, "tale_import_rrzip.txt"))
    @mock.patch("girder.plugins.wholetale.lib.manifest.ImageBuilder")
    def testTaleImportZipWithRuns(self, mock_builder):
        mock_builder.return_value.container_config.repo2docker_version = \
            "craigwillis/repo2docker:latest"
        mock_builder.return_value.get_tag.return_value = \
            "some_image_digest"
        image = self.model("image", "wholetale").createImage(
            name="Jupyter Notebook",
            creator=self.user,
            public=True,
            config=dict(
                template="base.tpl",
                buildpack="PythonBuildPack",
                user="someUser",
                port=8888,
                urlPath="",
            ),
        )

        since = datetime.utcnow().isoformat()
        with open(
            os.path.join(DATA_PATH, "61f18414fdfd5791fbb61b7b.zip"), "rb"
        ) as fp:
            resp = self.request(
                path="/tale/import",
                method="POST",
                user=self.user,
                type="application/zip",
                body=fp.read(),
            )

        self.assertStatusOk(resp)
        tale = resp.json

        from girder.plugins.jobs.models.job import Job

        job = Job().findOne({"type": "wholetale.import_tale"})
        self.assertEqual(
            json.loads(job["kwargs"])["taleId"]["$oid"], tale["_id"]
        )
        for _ in range(600):
            if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                break
            time.sleep(0.1)
            job = Job().load(job["_id"], force=True)
        self.assertEqual(job["status"], JobStatus.SUCCESS)
        # TODO: make it more extensive...
        tale = Tale().load(tale["_id"], force=True)
        self.assertEqual(tale["status"], 1)
        resp = self.request(
            path="/version",
            method="GET",
            user=self.user,
            params={"taleId": tale["_id"]}
        )
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 1)

        resp = self.request(
            path="/run",
            method="GET",
            user=self.user,
            params={"taleId": tale["_id"]}
        )
        self.assertStatusOk(resp)
        runs = resp.json
        self.assertEqual(len(runs), 3)
        self.assertEqual([_["runStatus"] for _ in runs], [4, 3, 3])

        events = get_events(self, since)
        self.assertEqual(
            {
                "wt_tale_created",
                "wt_import_started",
                "wt_tale_updated",
                "wt_import_completed"
            },
            event_types(events, {"taleId": str(tale["_id"])})
        )
        self.model("image", "wholetale").remove(image)

    def test_binder_heuristics(self):
        from girder.plugins.wholetale.tasks.import_binder import sanitize_binder

        tale = Tale().createTale(self.image, [], creator=self.user, title="Binder")
        tmpdir = tempfile.mkdtemp()

        with open(tmpdir + "/i_am_a_binder", "w") as fobj:
            fobj.write("but well hidden!")

        with tarfile.open(tmpdir + "/tale.tar.gz", "w:gz") as tar:
            tar.add(tmpdir + "/i_am_a_binder", arcname="dir_in_tar/i_am_a_binder")
        os.remove(tmpdir + "/i_am_a_binder")

        with zipfile.ZipFile(tmpdir + "/tale.zip", "w") as myzip:
            myzip.write(tmpdir + "/tale.tar.gz", arcname="dir_in_zip/tale.tar.gz")
        os.remove(tmpdir + "/tale.tar.gz")
        os.makedirs(tmpdir + "/hidden_binder")
        os.rename(tmpdir + "/tale.zip", tmpdir + "/hidden_binder" + "/tale.zip")

        workspace = Folder().load(tale["workspaceId"], force=True)
        with OSFS(workspace["fsPath"]) as destination_fs, OSFS(tmpdir) as source_fs:
            copy_fs(source_fs, destination_fs)
            sanitize_binder(destination_fs)
            self.assertEqual(list(destination_fs.listdir("/")), ["i_am_a_binder"])

        shutil.rmtree(tmpdir)
        Tale().remove(tale)

    def test_bdbag_import(self):
        with open(
            os.path.join(DATA_PATH, "Reporter_Cell_Line_14-3QDC.zip"), "rb"
        ) as fp:
            resp = self.request(
                path="/dataset/importBag",
                method="POST",
                user=self.user,
                type="application/zip",
                body=fp.read(),
            )

            self.assertStatusOk(resp)
            job = resp.json

            from girder.plugins.jobs.models.job import Job

            for _ in range(600):
                if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                    break
                time.sleep(0.1)
                job = Job().load(job["_id"], force=True)
            self.assertEqual(job["status"], JobStatus.SUCCESS)

        base = (
            "/collection/WholeTale Catalog/WholeTale Catalog/Reporter_Cell_Line_14-3QDC"
        )
        obj = lookUpPath(os.path.join(base, "fetch.txt"))
        self.assertEqual(obj["model"], "item")
        self.assertEqual(obj["document"]["size"], 416)
        obj = lookUpPath(os.path.join(base, "data"))
        self.assertEqual(obj["model"], "folder")
        self.assertEqual(obj["document"]["size"], 2720)

    def test_dsRootPath(self):
        from girder.plugins.jobs.models.job import Job

        image = self.model("image", "wholetale").createImage(
            name="Jupyter Classic",
            creator=self.user,
            public=True,
            config=dict(
                template="base.tpl",
                buildpack="PythonBuildPack",
                user="someUser",
                port=8888,
                urlPath="",
            ),
        )

        def before_record_cb(request):
            if request.host == "localhost":
                return None
            return request

        def import_request(ds_root="", asTale=True):
            resp = self.request(
                path="/tale/import",
                method="POST",
                user=self.user,
                params={
                    "url": (
                        "https://dataverse.harvard.edu/dataset.xhtml?"
                        "persistentId=doi:10.7910/DVN/5WTSUZ"
                    ),
                    "spawn": False,
                    "imageId": self.image["_id"],
                    "asTale": asTale,
                    "dsRootPath": ds_root,
                },
            )
            self.assertStatusOk(resp)
            tale = resp.json
            job = Job().findOne(
                {"type": "wholetale.import_binder", "taleId": ObjectId(tale["_id"])}
            )
            self.assertEqual(json.loads(job["kwargs"])["taleId"]["$oid"], tale["_id"])

            for _ in range(600):
                if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                    break
                time.sleep(0.1)
                job = Job().load(job["_id"], force=True)
            self.assertEqual(job["status"], JobStatus.SUCCESS)
            return tale

        my_vcr = vcr.VCR(before_record_request=before_record_cb)
        with my_vcr.use_cassette(os.path.join(DATA_PATH, "tale_import_dsRootPath.txt")):
            tale = import_request(ds_root="", asTale=False)

        tale = Tale().load(tale["_id"], force=True)
        self.assertEqual(
            {_["mountPath"] for _ in tale["dataSet"]},
            {
                (
                    "Replication Data for Anchor Management A Field Experiment to "
                    "Encourage Families to Meet Critical Program Deadlines"
                )
            },
        )
        Tale().remove(tale)

        with my_vcr.use_cassette(os.path.join(DATA_PATH, "tale_import_dsRootPath.txt")):
            tale = import_request(ds_root="/", asTale=False)

        tale = Tale().load(tale["_id"], force=True)
        self.assertEqual(
            {_["mountPath"] for _ in tale["dataSet"]},
            {"00-README.md", "DHS-TANFRecertification-Public"},
        )
        Tale().remove(tale)

        with my_vcr.use_cassette(os.path.join(DATA_PATH, "tale_import_dsRootPath.txt")):
            tale = import_request(
                ds_root="/DHS-TANFRecertification-Public/data", asTale=False
            )
        tale = Tale().load(tale["_id"], force=True)
        self.assertEqual(
            {_["mountPath"] for _ in tale["dataSet"]},
            {"df_replication_anonymized.csv", "df_replication_anonymized.tab"},
        )
        Tale().remove(tale)
        self.model("image", "wholetale").remove(image)

    def tearDown(self):
        self.model("user").remove(self.user)
        self.model("user").remove(self.admin)
        self.model("image", "wholetale").remove(self.image)
        super(ImportTaleTestCase, self).tearDown()
