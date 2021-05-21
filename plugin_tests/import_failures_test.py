import mock
import os
import json
import time
from tests import base
from girder import config
from girder.models.folder import Folder


JobStatus = None
ImageStatus = None
Tale = None
DATA_PATH = os.path.join(
    os.path.dirname(os.environ["GIRDER_TEST_DATA_PREFIX"]),
    "data_src",
    "plugins",
    "wholetale",
)
os.environ["GIRDER_PORT"] = os.environ.get("GIRDER_TEST_PORT", "20200")
config.loadConfig()  # Must reload config to pickup correct port


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.enabledPlugins.append("wt_home_dir")
    base.startServer()

    global JobStatus, Tale, ImageStatus, TaleStatus, Job, Image
    from girder.plugins.jobs.constants import JobStatus
    from girder.plugins.jobs.models.job import Job
    from girder.plugins.wholetale.models.image import Image
    from girder.plugins.wholetale.models.tale import Tale
    from girder.plugins.wholetale.constants import ImageStatus, TaleStatus


def tearDownModule():
    base.stopServer()


class TaskFailTestCase(base.TestCase):
    def setUp(self):
        super(TaskFailTestCase, self).setUp()
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

        self.image = Image().createImage(
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

    def testTaleImportBinderFail(self):
        with mock.patch("girder.plugins.wholetale.lib.pids_to_entities") as mock_pids:
            mock_pids.side_effect = ValueError
            resp = self.request(
                path="/tale/import",
                method="POST",
                user=self.user,
                params={
                    "url": "http://use.yt/upload/ef4cd901",
                    "spawn": False,
                    "imageId": self.image["_id"],
                    "asTale": True,
                    "taleKwargs": json.dumps({"title": "tale should fail"}),
                },
            )
            self.assertStatusOk(resp)
            tale = resp.json

            job = Job().findOne({"type": "wholetale.import_binder"})
            self.assertEqual(
                json.loads(job["kwargs"])["taleId"]["$oid"], tale["_id"]
            )

            for i in range(300):
                if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                    break
                time.sleep(0.1)
                job = Job().load(job["_id"], force=True)
            self.assertEqual(job["status"], JobStatus.ERROR)
            Job().remove(job)
        tale = Tale().load(tale["_id"], force=True)
        self.assertEqual(tale["status"], TaleStatus.ERROR)
        Tale().remove(tale)

    def testTaleImportZipFail(self):
        image = Image().createImage(
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
        with mock.patch("girder.plugins.wholetale.lib.pids_to_entities") as mock_pids:
            mock_pids.side_effect = ValueError
            with open(
                os.path.join(DATA_PATH, "5c92fbd472a9910001fbff72.zip"), "rb"
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

            job = Job().findOne({"type": "wholetale.import_tale"})
            self.assertEqual(
                json.loads(job["kwargs"])["taleId"]["$oid"], tale["_id"]
            )
            for i in range(300):
                if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                    break
                time.sleep(0.1)
                job = Job().load(job["_id"], force=True)
            self.assertEqual(job["status"], JobStatus.ERROR)
            Job().remove(job)
        tale = Tale().load(tale["_id"], force=True)
        self.assertEqual(tale["status"], TaleStatus.ERROR)
        Tale().remove(tale)
        Image().remove(image)

    def testCopyWorkspaceFail(self):
        tale = Tale().createTale(
            self.image,
            [],
            creator=self.admin,
            title="tale one",
            public=True,
            config={"memLimit": "2g"},
        )
        new_tale = Tale().createTale(
            self.image,
            [],
            creator=self.admin,
            title="tale one (copy)",
            public=True,
            config={"memLimit": "2g"},
        )
        new_workspace = Folder().load(new_tale["workspaceId"], force=True)
        Folder().remove(new_workspace)  # oh no!
        job = Job().createLocalJob(
            title='Copy "{title}" workspace'.format(**tale),
            user=self.user,
            type="wholetale.copy_workspace",
            public=False,
            _async=True,
            module="girder.plugins.wholetale.tasks.copy_workspace",
            args=(tale, new_tale),
        )
        Job().scheduleJob(job)
        for i in range(300):
            if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                break
            time.sleep(0.1)
            job = Job().load(job["_id"], force=True)
        self.assertEqual(job["status"], JobStatus.ERROR)
        Job().remove(job)
        new_tale = Tale().load(new_tale["_id"], force=True)
        self.assertEqual(new_tale["status"], TaleStatus.ERROR)
        Tale().remove(tale)
        Tale().remove(new_tale)

    def tearDown(self):
        self.model("user").remove(self.user)
        self.model("user").remove(self.admin)
        self.model("image", "wholetale").remove(self.image)
        super(TaskFailTestCase, self).tearDown()
