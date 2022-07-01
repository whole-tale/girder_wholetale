import httmock
import io
import json
import mock
import os
import tempfile
import vcr
import zipfile
from tests import base
from urllib.parse import urlparse, parse_qs
from girder.exceptions import GirderException
from girder.models.assetstore import Assetstore
from girder.models.folder import Folder
from girder.models.setting import Setting
from girder.models.user import User


DATA_PATH = os.path.join(
    os.path.dirname(os.environ["GIRDER_TEST_DATA_PREFIX"]),
    "data_src",
    "plugins",
    "wholetale",
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


@httmock.all_requests
def mock_other_request(url, request):
    raise Exception("Unexpected url %s" % str(request.url))


@httmock.urlmatch(
    scheme="https",
    netloc="^sandbox.zenodo.org$",
    path="^/api/records/430905$",
    method="GET",
)
def mock_get_record(url, request):
    return httmock.response(
        status_code=200,
        content={
            "id": 430905,
            "files": [
                {
                    "bucket": "111daf16-680a-48bb-bb85-5e251f3d7609",
                    "checksum": "md5:42c822247416fcf0ad9c9f7ee776bae4",
                    "key": "5df2752385bc9fc730ce423b.zip",
                    "links": {
                        "self": (
                            "https://sandbox.zenodo.org/api/files/"
                            "111daf16-680a-48bb-bb85-5e251f3d7609/"
                            "5df2752385bc9fc730ce423b.zip"
                        )
                    },
                    "size": 92599,
                    "type": "zip",
                }
            ],
            "doi": "10.5072/zenodo.430905",
            "links": {"doi": "https://doi.org/10.5072/zenodo.430905"},
            "created": "2019-12-12T17:13:35.820719+00:00",
            "metadata": {"keywords": ["Tale", "Astronomy"]},
        },
        headers={},
        reason=None,
        elapsed=5,
        request=request,
        stream=False,
    )


def fake_urlopen(url):
    fname = os.path.join(DATA_PATH, "5c92fbd472a9910001fbff72.zip")
    return open(fname, "rb")


class ZenodoHarversterTestCase(base.TestCase):
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

    @vcr.use_cassette(os.path.join(DATA_PATH, "zenodo_lookup.txt"))
    def testLookup(self):
        resolved_lookup = {
            "dataId": "https://zenodo.org/record/3459420",
            "doi": "doi:10.5281/zenodo.3459420",
            "name": "A global network of biomedical relationships derived from text_ver_7",
            "repository": "Zenodo",
            "size": 8037626747,
            "tale": False,
        }

        resp = self.request(
            path="/repository/lookup",
            method="GET",
            user=self.user,
            params={
                "dataId": json.dumps(
                    [
                        "https://doi.org/10.5281/zenodo.3459420",
                        "https://zenodo.org/record/3459420",
                    ]
                )
            },
        )
        self.assertStatus(resp, 200)
        self.assertEqual(resp.json, [resolved_lookup, resolved_lookup])

        resolved_listFiles = [
            {
                "jbferet_biodivMapR v1.0.1_ver_v1.0.1": {
                    "jbferet": {
                        "fileList": [{"biodivMapR-v1.0.1.zip": {"size": 24692383}}]
                    }
                }
            }
        ]

        resp = self.request(
            path="/repository/listFiles",
            method="GET",
            user=self.user,
            params={"dataId": json.dumps(["https://zenodo.org/record/3463499"])},
        )
        self.assertStatus(resp, 200)
        self.assertEqual(resp.json, resolved_listFiles)

    def test_extra_hosts(self):
        from girder.plugins.wholetale.constants import PluginSettings, SettingDefault

        resp = self.request(
            "/system/setting",
            user=self.admin,
            method="PUT",
            params={
                "key": PluginSettings.ZENODO_EXTRA_HOSTS,
                "value": "https://sandbox.zenodo.org/record",
            },
        )
        self.assertStatus(resp, 400)
        self.assertEqual(
            resp.json,
            {
                "field": "value",
                "type": "validation",
                "message": "Zenodo extra hosts setting must be a list.",
            },
        )

        resp = self.request(
            "/system/setting",
            user=self.admin,
            method="PUT",
            params={
                "key": PluginSettings.ZENODO_EXTRA_HOSTS,
                "value": json.dumps(["not a url"]),
            },
        )
        self.assertStatus(resp, 400)
        self.assertEqual(
            resp.json,
            {
                "field": "value",
                "type": "validation",
                "message": "Invalid URL in Zenodo extra hosts",
            },
        )

        # defaults
        resp = self.request(
            "/system/setting",
            user=self.admin,
            method="PUT",
            params={"key": PluginSettings.ZENODO_EXTRA_HOSTS, "value": ""},
        )
        self.assertStatusOk(resp)
        resp = self.request(
            "/system/setting",
            user=self.admin,
            method="GET",
            params={"key": PluginSettings.ZENODO_EXTRA_HOSTS},
        )
        self.assertStatusOk(resp)
        self.assertEqual(
            resp.body[0].decode(),
            str(SettingDefault.defaults[PluginSettings.ZENODO_EXTRA_HOSTS]),
        )

        resp = self.request(
            "/system/setting",
            user=self.admin,
            method="PUT",
            params={
                "list": json.dumps(
                    [
                        {
                            "key": PluginSettings.ZENODO_EXTRA_HOSTS,
                            "value": ["https://sandbox.zenodo.org/record/"],
                        }
                    ]
                )
            },
        )
        self.assertStatusOk(resp)
        from girder.plugins.wholetale.lib.zenodo.provider import ZenodoImportProvider

        self.assertEqual(
            "^http(s)?://(sandbox.zenodo.org/record/|zenodo.org/record/).*$",
            ZenodoImportProvider().regex[0].pattern,
        )

    @vcr.use_cassette(os.path.join(DATA_PATH, "zenodo_hierarchy.txt"))
    def test_dataset_with_hierarchy(self):
        resp = self.request(
            path="/repository/listFiles",
            method="GET",
            user=self.user,
            params={"dataId": json.dumps(["https://zenodo.org/record/3463499"])},
        )
        self.assertStatus(resp, 200)
        self.assertEqual(
            resp.json[0],
            {
                "jbferet_biodivMapR v1.0.1_ver_v1.0.1": {
                    "jbferet": {
                        "fileList": [{"biodivMapR-v1.0.1.zip": {"size": 24692383}}]
                    }
                }
            },
        )

    @vcr.use_cassette(os.path.join(DATA_PATH, "zenodo_manifest.txt"))
    def test_manifest_helpers(self):
        resp = self.request(
            path="/repository/lookup",
            method="GET",
            user=self.user,
            params={"dataId": json.dumps(["https://zenodo.org/record/3463499"])},
        )
        self.assertStatus(resp, 200)
        data_map = resp.json

        resp = self.request(
            path="/dataset/register",
            method="POST",
            params={"dataMap": json.dumps(data_map)},
            user=self.user,
        )
        self.assertStatusOk(resp)

        user = User().load(self.user["_id"], force=True)
        dataset_root_folder = Folder().load(user["myData"][0], user=user)
        child_folder = next(
            Folder().childFolders(
                parentType="folder", parent=dataset_root_folder, user=user
            )
        )
        child_item = next((item for item in Folder().childItems(folder=child_folder)))

        from girder.plugins.wholetale.lib.zenodo.provider import ZenodoImportProvider

        for obj in (dataset_root_folder, child_folder, child_item):
            self.assertEqual(
                ZenodoImportProvider().getDatasetUID(obj, user),
                "doi:10.5281/zenodo.3463499",
            )

    def test_import_binder(self):
        resp = self.request(
            path="/integration/zenodo",
            method="GET",
            user=self.user,
            params={
                "record_id": "5092301",
                "resource_server": "zenodo.org",
            },
            isJson=False,
        )

        self.assertTrue("Location" in resp.headers)
        location = urlparse(resp.headers["Location"])
        self.assertEqual(location.netloc, "dashboard.wholetale.org")
        qs = parse_qs(location.query)
        self.assertTrue(qs["asTale"][0])
        self.assertTrue(qs["name"][0].startswith("antonninkov/ISSI2021"))
        self.assertEqual(qs["uri"], ["https://zenodo.org/record/5092301"])

    def test_import_tale(self):
        from girder.plugins.wholetale.models.tale import Tale
        from girder.plugins.oauth.constants import PluginSettings as OAuthSettings

        Setting().set(OAuthSettings.PROVIDERS_ENABLED, ["globus"])
        Setting().set(OAuthSettings.GLOBUS_CLIENT_ID, "client_id")
        Setting().set(OAuthSettings.GLOBUS_CLIENT_SECRET, "secret_id")

        resp = self.request(path="/integration/zenodo", method="GET")
        self.assertStatus(resp, 400)
        self.assertEqual(
            resp.json,
            {
                "type": "rest",
                "message": "You need to provide either 'doi' or 'record_id'",
            },
        )

        resp = self.request(
            path="/integration/zenodo",
            method="GET",
            params={"doi": "10.5072/zenodo.430905"},
        )
        self.assertStatus(resp, 400)
        self.assertEqual(
            resp.json, {"type": "rest", "message": "resource_server not set"}
        )

        resp = self.request(
            path="/integration/zenodo",
            method="GET",
            params={"doi": "10.5072/zenodo.430905"},
            additionalHeaders=[("Referer", "https://sandbox.zenodo.org")],
            isJson=False,
        )
        self.assertStatus(resp, 303)
        self.assertTrue("Location" in resp.headers)
        location = urlparse(resp.headers["Location"])
        self.assertEqual(location.netloc, "auth.globus.org")
        redirect = urlparse(parse_qs(location.query)["state"][0].split(".", 1)[-1])
        self.assertEqual(redirect.path, "/api/v1/integration/zenodo")
        self.assertEqual(
            parse_qs(redirect.query),
            {
                "record_id": ["430905"],
                "resource_server": ["sandbox.zenodo.org"],
                "token": ["{girderToken}"],
                "force": ["False"],
            },
        )

        with httmock.HTTMock(mock_get_record, mock_other_request):
            with mock.patch(
                "girder.plugins.wholetale.lib.zenodo.provider.urlopen", fake_urlopen
            ):
                resp = self.request(
                    path="/integration/zenodo",
                    method="GET",
                    user=self.user,
                    params={
                        "record_id": "430905",
                        "resource_server": "sandbox.zenodo.org",
                    },
                    isJson=False,
                )

        self.assertTrue("Location" in resp.headers)
        location = urlparse(resp.headers["Location"])
        self.assertEqual(location.netloc, "dashboard.wholetale.org")
        tale_id = location.path.rsplit("/")[-1]

        tale = Tale().load(tale_id, user=self.user)
        self.assertEqual(tale["title"], "Water Tale")

        with httmock.HTTMock(mock_get_record, mock_other_request):
            with mock.patch(
                "girder.plugins.wholetale.lib.zenodo.provider.urlopen", fake_urlopen
            ):
                resp = self.request(
                    path="/integration/zenodo",
                    method="GET",
                    user=self.user,
                    params={
                        "record_id": "430905",
                        "resource_server": "sandbox.zenodo.org",
                    },
                    isJson=False,
                )
        self.assertTrue("Location" in resp.headers)
        location = urlparse(resp.headers["Location"])
        self.assertEqual(location.netloc, "dashboard.wholetale.org")
        existing_tale_id = location.path.rsplit("/")[-1]
        self.assertEqual(tale_id, existing_tale_id)

    def test_analyze_in_wt_failures(self):
        def not_a_zip(url):
            return io.BytesIO(b"blah")

        def no_manifest(url):
            fp = io.BytesIO()
            with zipfile.ZipFile(fp, mode="w") as zf:
                zf.writestr("blah", "blah")
            fp.seek(0)
            return fp

        def malformed_manifest(url):
            fp = io.BytesIO()
            with zipfile.ZipFile(fp, mode="w") as zf:
                zf.writestr("manifest.json", "blah")
            fp.seek(0)
            return fp

        def no_env(url):
            fp = io.BytesIO()
            with zipfile.ZipFile(fp, mode="w") as zf:
                zf.writestr(
                    "manifest.json",
                    json.dumps(
                        {
                            "@id": "https://data.wholetale.org",
                            "@type": "wt:Tale",
                        }
                    ),
                )
            fp.seek(0)
            return fp

        funcs = [not_a_zip, no_manifest, malformed_manifest, no_env]
        errors = [
            "'Provided file is not a zipfile'",
            "'Provided file doesn't contain a Tale manifest'",
            (
                "'Couldn't read manifest.json or not a Tale: "
                "Expecting value: line 1 column 1 (char 0)'"
            ),
            (
                "'Couldn't read environment.json or not a Tale: "
                "'There is no item named None in the archive''"
            ),
        ]

        with httmock.HTTMock(mock_get_record, mock_other_request):
            for func, msg in zip(funcs, errors):
                with mock.patch(
                    "girder.plugins.wholetale.lib.zenodo.provider.urlopen", func
                ):
                    resp = self.request(
                        path="/integration/zenodo",
                        method="GET",
                        user=self.user,
                        params={
                            "record_id": "430905",
                            "resource_server": "sandbox.zenodo.org",
                        },
                    )
                    self.assertStatus(resp, 400)
                    self.assertEqual(
                        resp.json,
                        {
                            "type": "rest",
                            "message": "Failed to import Tale. Server returned: " + msg,
                        },
                    )

    def tearDown(self):
        self.model("user").remove(self.user)
        self.model("user").remove(self.admin)
