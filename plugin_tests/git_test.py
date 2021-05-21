import git
import mock
import os
import pymongo
import time
import tempfile
import shutil
from datetime import datetime
from tests import base
from .tests_helpers import get_events

from girder.models.folder import Folder
from girder.models.user import User


Tale = None
Image = None
Job = None
JobStatus = None
ImageStatus = None


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.enabledPlugins.append("wt_home_dir")
    base.enabledPlugins.append("virtual_resources")
    base.startServer()

    global JobStatus, Tale, ImageStatus, Image, Job
    from girder.plugins.jobs.constants import JobStatus
    from girder.plugins.jobs.models.job import Job
    from girder.plugins.wholetale.models.tale import Tale
    from girder.plugins.wholetale.models.image import Image
    from girder.plugins.wholetale.constants import ImageStatus


def tearDownModule():
    base.stopServer()


class GitImportTestCase(base.TestCase):
    def setUp(self):
        super(GitImportTestCase, self).setUp()
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

        self.admin, self.user = [User().createUser(**user) for user in users]
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

        self.git_repo_dir = tempfile.mkdtemp()
        self.git_file_name = "hello.txt"
        self.git_file_on_branch = "on_branch.txt"
        r = git.Repo.init(self.git_repo_dir)
        with open(os.path.join(self.git_repo_dir, self.git_file_name), "w") as fp:
            fp.write("World!")
        r.index.add([self.git_file_name])
        r.index.commit("initial commit")
        feature = r.create_head("feature")
        r.head.reference = feature
        with open(os.path.join(self.git_repo_dir, self.git_file_on_branch), "w") as fp:
            fp.write("MAGIC!")
        r.index.add([self.git_file_on_branch])
        r.index.commit("Commit on a branch")
        r.head.reference = r.refs["master"]
        r.head.reset(index=True, working_tree=True)

    def _import_git_repo(self, tale, url):
        resp = self.request(
            path=f"/tale/{tale['_id']}/git",
            method="PUT",
            user=self.user,
            params={"url": url},
        )
        self.assertStatusOk(resp)

        job = (
            Job()
            .find({"type": "wholetale.import_git_repo"})
            .sort([("created", pymongo.DESCENDING)])
            .limit(1)
            .next()
        )

        for i in range(10):
            time.sleep(0.5)
            job = Job().load(job["_id"], force=True, includeLog=True)
            if job["status"] >= JobStatus.SUCCESS:
                break

        return job

    def _import_from_git_repo(self, url):
        resp = self.request(
            path="/tale/import",
            method="POST",
            user=self.user,
            params={
                "url": url,
                "git": True,
                "imageId": str(self.image["_id"]),
                "spawn": True,
            },
        )
        self.assertStatusOk(resp)
        tale = resp.json

        job = (
            Job()
            .find({"type": "wholetale.import_git_repo"})
            .sort([("created", pymongo.DESCENDING)])
            .limit(1)
            .next()
        )

        for i in range(60):
            time.sleep(0.5)
            job = Job().load(job["_id"], force=True, includeLog=True)
            if job["status"] >= JobStatus.SUCCESS:
                break
        tale = Tale().load(tale["_id"], user=self.user)
        return tale, job

    def testImportGitAsTale(self):
        from girder.plugins.wholetale.constants import InstanceStatus, TaleStatus

        class fakeInstance(object):
            _id = "123456789"

            def createInstance(self, tale, user, /, *, spawn=False):
                return {"_id": self._id, "status": InstanceStatus.LAUNCHING}

            def load(self, instance_id, user=None):
                assert instance_id == self._id
                return {"_id": self._id, "status": InstanceStatus.RUNNING}

        with mock.patch(
            "girder.plugins.wholetale.tasks.import_git_repo.Instance", fakeInstance
        ):
            since = datetime.utcnow().isoformat()
            # Custom branch
            tale, job = self._import_from_git_repo(
                f"file://{self.git_repo_dir}@feature"
            )
            workspace = Folder().load(tale["workspaceId"], force=True)
            workspace_path = workspace["fsPath"]
            self.assertEqual(job["status"], JobStatus.SUCCESS)
            self.assertTrue(
                os.path.isfile(os.path.join(workspace["fsPath"], self.git_file_name))
            )
            self.assertTrue(
                os.path.isfile(
                    os.path.join(workspace["fsPath"], self.git_file_on_branch)
                )
            )
            # Confirm events
            events = get_events(self, since)
            self.assertEqual(len(events), 3)
            self.assertEqual(events[0]['data']['event'], 'wt_tale_created')
            self.assertEqual(events[1]['data']['event'], 'wt_import_started')
            self.assertEqual(events[2]['data']['event'], 'wt_import_completed')
            shutil.rmtree(workspace_path)
            os.mkdir(workspace_path)
            Tale().remove(tale)

        # Invalid url
        since = datetime.utcnow().isoformat()
        tale, job = self._import_from_git_repo("blah")
        workspace = Folder().load(tale["workspaceId"], force=True)
        workspace_path = workspace["fsPath"]
        self.assertEqual(job["status"], JobStatus.ERROR)
        self.assertTrue("does not appear to be a git repo" in job["log"][0])
        self.assertEqual(tale["status"], TaleStatus.ERROR)
        # Confirm events
        events = get_events(self, since)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]['data']['event'], 'wt_tale_created')
        self.assertEqual(events[1]['data']['event'], 'wt_import_started')
        self.assertEqual(events[2]['data']['event'], 'wt_import_failed')
        Tale().remove(tale)

    def testGitImport(self):
        tale = Tale().createTale(self.image, [], creator=self.user, public=True)
        workspace = Folder().load(tale["workspaceId"], force=True)
        workspace_path = workspace["fsPath"]

        # Invalid path
        since = datetime.utcnow().isoformat()
        job = self._import_git_repo(tale, "blah")
        self.assertEqual(job["status"], JobStatus.ERROR)
        self.assertTrue("does not appear to be a git repo" in job["log"][0])
        if os.path.isdir(os.path.join(workspace_path, ".git")):
            shutil.rmtree(os.path.join(workspace_path, ".git"))
        # Confirm events
        events = get_events(self, since)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]['data']['event'], 'wt_import_started')
        self.assertEqual(events[1]['data']['event'], 'wt_import_failed')

        # Default branch (master)
        since = datetime.utcnow().isoformat()
        job = self._import_git_repo(tale, f"file://{self.git_repo_dir}")
        self.assertEqual(job["status"], JobStatus.SUCCESS)
        self.assertTrue(
            os.path.isfile(os.path.join(workspace["fsPath"], self.git_file_name))
        )
        self.assertFalse(
            os.path.isfile(os.path.join(workspace["fsPath"], self.git_file_on_branch))
        )
        # Confirm events
        events = get_events(self, since)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]['data']['event'], 'wt_import_started')
        self.assertEqual(events[1]['data']['event'], 'wt_import_completed')
        shutil.rmtree(workspace_path)
        os.mkdir(workspace_path)

        # Custom branch
        job = self._import_git_repo(tale, f"file://{self.git_repo_dir}@feature")
        self.assertEqual(job["status"], JobStatus.SUCCESS)
        self.assertTrue(
            os.path.isfile(os.path.join(workspace["fsPath"], self.git_file_name))
        )
        self.assertTrue(
            os.path.isfile(os.path.join(workspace["fsPath"], self.git_file_on_branch))
        )
        shutil.rmtree(workspace_path)
        os.mkdir(workspace_path)
        Tale().remove(tale)

    def tearDown(self):
        User().remove(self.user)
        User().remove(self.admin)
        Image().remove(self.image)
        shutil.rmtree(self.git_repo_dir)
        super(GitImportTestCase, self).tearDown()
