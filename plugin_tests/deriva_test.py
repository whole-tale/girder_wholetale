from bson import ObjectId
import httmock
import json
import mock
import os
import tempfile
import time
from tests import base
from urllib.parse import urlparse, parse_qs
from girder.exceptions import GirderException
from girder.models.assetstore import Assetstore


DATA_PATH = os.path.join(
    os.path.dirname(os.environ["GIRDER_TEST_DATA_PREFIX"]),
    "data_src",
    "plugins",
    "wholetale",
)

EXAMPLE_URL = (
    "https://pbcconsortium.s3.amazonaws.com/wholetale/5ad7cdf55b0d"
    "5007601015b7ff1ea8d6/2021-11-09_21.47.58/Dataset_1-882P.zip"
)


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.startServer()
    try:
        assetstore = Assetstore().getCurrent()
    except GirderException:
        assetstore = Assetstore().createFilesystemAssetstore("test", tempfile.mkdtemp())
        assetstore["current"] = True
        Assetstore().save(assetstore)


def tearDownModule():
    Assetstore().remove(Assetstore().getCurrent())
    base.stopServer()


def fake_remote_bag_open(url):
    fname = os.path.join(DATA_PATH, "Dataset_1-882P.zip")
    return open(fname, "rb")


@httmock.all_requests
def mock_other_request(url, request):
    raise Exception("Unexpected url %s" % str(request.url))


@httmock.urlmatch(
    scheme="https",
    netloc="^identifiers.fair-research.org$",
    path="^/hdl:20.500.12633/11RHwdYqWNBZL$",
    method="GET",
)
def minid_request(url, request):
    return httmock.response(
        status_code=200,
        content={
            "active": True,
            "admins": [
                "urn:globus:auth:identity:aff007b5-7995-4be9-b2b8-41d468d77d6f",
                "urn:globus:groups:id:160bf3be-07ef-11ea-bc96-0ebedcdf7b97",
                "urn:globus:auth:identity:e8d08e61-4e1e-45c0-a583-613db806b468",
                "urn:globus:auth:identity:aa3f6d52-d274-11e5-aba5-638c4674ab86",
            ],
            "checksums": [
                {
                    "function": "sha256",
                    "value": "26a41d7d5de7918a7f3987e30e9ea9b3a97698a31eaa543f6916959685e04738",
                }
            ],
            "created": "2021-11-10T05:47:59.583365",
            "identifier": "hdl:20.500.12633/11RHwdYqWNBZL",
            "landing_page": "https://identifiers.fair-research.org/hdl:20.500.12633/11RHwdYqWNBZL",
            "location": [EXAMPLE_URL],
            "metadata": {
                "created_by": "Mihael Hategan",
                "length": 150794,
                "title": "Dataset_1-882P.zip",
            },
            "updated": "2021-11-10T05:47:59.583365",
            "visible_to": ["public"],
        },
        headers={
            "Server": "Apache/2.4.46 (Fedora) OpenSSL/1.1.1g mod_wsgi/4.6.6 Python/3.7",
            "Content-Length": 993,
            "Content-Type": "application/json",
        },
        reason=None,
        elapsed=1,
        request=request,
        stream=False,
    )


def fake_urlopen(url):
    fname = os.path.join(DATA_PATH, "5c92fbd472a9910001fbff72.zip")
    return open(fname, "rb")


class DerivaHarversterTestCase(base.TestCase):
    def setUp(self):
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
        self.admin, self.user = [
            self.model("user").createUser(**user) for user in users
        ]
        from girder.plugins.wholetale.models.image import Image

        self.image = Image().createImage(
            name="Jupyter Classic",
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

    def testLookup(self):
        resolved_lookup = {
            "dataId": (
                "https://pbcconsortium.s3.amazonaws.com/wholetale/5ad7cdf55b0d5007601015"
                "b7ff1ea8d6/2021-11-09_21.47.58/Dataset_1-882P.zip"
            ),
            "doi": "hdl:20.500.12633/11RHwdYqWNBZL",
            "name": "Dataset_1-882P.zip",
            "repository": "DERIVA",
            "size": 150794,
            "tale": False,
        }

        url = "https://identifiers.fair-research.org/hdl:20.500.12633/11RHwdYqWNBZL"

        with httmock.HTTMock(minid_request, mock_other_request):
            resp = self.request(
                path="/repository/lookup",
                method="GET",
                user=self.user,
                params={"dataId": json.dumps([url])},
            )
            self.assertStatus(resp, 200)
        self.assertEqual(resp.json, [resolved_lookup])

        return  # not implemented yet
        resolved_listFiles = ["notImplemented"]
        resp = self.request(
            path="/repository/listFiles",
            method="GET",
            user=self.user,
            params={"dataId": json.dumps([url])},
        )
        self.assertStatus(resp, 200)
        self.assertEqual(resp.json, resolved_listFiles)

    def test_integration(self):
        # Doesn't do much at this point...
        resp = self.request(
            path="/integration/deriva",
            method="GET",
            user=self.user,
            params={"url": EXAMPLE_URL},
            isJson=False,
        )

        self.assertTrue("Location" in resp.headers)
        location = urlparse(resp.headers["Location"])
        self.assertEqual(location.netloc, "dashboard.wholetale.org")
        qs = parse_qs(location.query)
        self.assertEqual(qs["uri"][0], EXAMPLE_URL)

    def testImportBDBagFromDeriva(self):
        from girder.plugins.jobs.models.job import Job
        from girder.plugins.jobs.constants import JobStatus
        from girder.plugins.wholetale.models.tale import Tale

        with mock.patch("httpio.open", side_effect=fake_remote_bag_open):
            with httmock.HTTMock(minid_request, mock_other_request):
                resp = self.request(
                    path="/tale/import",
                    method="POST",
                    user=self.user,
                    params={
                        "git": False,
                        "url": EXAMPLE_URL,
                        "spawn": False,
                        "imageId": str(self.image["_id"]),
                        "dsRootPath": "/data",
                    },
                )
                self.assertStatusOk(resp)
                tale = resp.json
                job = Job().findOne(
                    {"type": "wholetale.import_binder", "taleId": ObjectId(tale["_id"])}
                )
                for _ in range(600):
                    if job["status"] in {JobStatus.SUCCESS, JobStatus.ERROR}:
                        break
                    time.sleep(0.1)
                    job = Job().load(job["_id"], force=True)
                self.assertEqual(job["status"], JobStatus.SUCCESS)

        tale = Tale().load(tale["_id"], force=True)
        self.assertEqual(
            {_["mountPath"] for _ in tale["dataSet"]},
            {
                "Biosample.csv",
                "Image Data.csv",
                "Dataset.csv",
                "Experiment.csv",
                "assets",
                "Mesh Data.csv",
                "Derived Image Data.csv",
            },
        )
        Tale().remove(tale)

    def tearDown(self):
        self.model("user").remove(self.user)
        self.model("user").remove(self.admin)
