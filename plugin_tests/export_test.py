import json

import httmock
import mock

from tests import base

from .tests_helpers import mockOtherRequest


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.enabledPlugins.append("wt_home_dir")
    base.enabledPlugins.append("virtual_resources")
    base.enabledPlugins.append("wt_versioning")
    base.startServer()


def tearDownModule():
    base.stopServer()


class ExportTestCase(base.TestCase):
    def setUp(self):
        super(ExportTestCase, self).setUp()
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

        self.image = self.model("image", "wholetale").createImage(
            name="test image", creator=self.admin, public=True
        )

    def testExportTemplate(self):
        resp = self.request(
            path="/tale",
            method="POST",
            user=self.user,
            type="application/json",
            body=json.dumps({"imageId": str(self.image["_id"]), "dataSet": []}),
        )
        self.assertStatusOk(resp)
        tale = resp.json

        with mock.patch(
            "girder.plugins.wholetale.lib.manifest.ImageBuilder"
        ) as mock_builder:
            mock_builder.return_value.container_config.repo2docker_version = (
                "craigwillis/repo2docker:latest"
            )
            mock_builder.return_value.get_tag.return_value = (
                "registry.local.wholetale.org/tale/hash:tag"
            )
            resp = self.request(
                path=f"/tale/{tale['_id']}/manifest",
                method="GET",
                user=self.user,
            )
            self.assertStatusOk(resp)
            manifest = resp.json

        from server.lib.exporters.bag import BagTaleExporter

        exporter = BagTaleExporter(self.user, manifest, {})

        @httmock.urlmatch(
            scheme="https",
            netloc="images.local.wholetale.org",
            path="^/v2/tale/hash/tags/list$",
            method="GET",
        )
        def mockImageFoundResponse(url, request):
            return json.dumps(
                {
                    "name": "tale/hash",
                    "tags": ["tag"],
                }
            )

        with httmock.HTTMock(mockImageFoundResponse, mockOtherRequest):
            tmpl = exporter.format_run_file(
                {"port": 80, "targetMount": "/srv", "user": "user"},
                "path?param",
                "token",
            )
            self.assertTrue("jupyter-repo2docker" not in tmpl)

        @httmock.urlmatch(
            scheme="https",
            netloc="images.local.wholetale.org",
            path="^/v2/tale/hash/tags/list$",
            method="GET",
        )
        def mockImageNotFoundResponse(url, request):
            return httmock.response(
                status_code=404,
                content=json.dumps(
                    {
                        "errors": [
                            {
                                "code": "NAME_UNKNOWN",
                                "message": "repository name not known to registry",
                                "detail": {"name": "tale/hash"},
                            }
                        ]
                    }
                ),
            )

        with httmock.HTTMock(mockImageNotFoundResponse, mockOtherRequest):
            tmpl = exporter.format_run_file(
                {"port": 80, "targetMount": "/srv", "user": "user"},
                "path?param",
                "token",
            )
            self.assertTrue("jupyter-repo2docker" in tmpl)
