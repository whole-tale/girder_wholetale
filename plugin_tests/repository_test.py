import json
from tests import base
from girder.models.user import User

# TODO: for some reason vcr is stuck in a infinite loop


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.startServer()


def tearDownModule():
    base.stopServer()


class RepositoryTestCase(base.TestCase):
    def setUp(self):
        super(RepositoryTestCase, self).setUp()
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

    def _lookup(self, url, path):
        return self.request(
            path="/repository/" + path,
            method="GET",
            params={"dataId": json.dumps([url])},
        )

    def testErrorHandling(self):
        for path in ("lookup", "listFiles"):
            resp = self._lookup("https://doi.org/10.7910/DVN/blah", path)
            self.assertStatus(resp, 400)
            self.assertEqual(
                resp.json,
                {
                    "message": 'Id "https://doi.org/10.7910/DVN/blah" was '
                    "categorized as DOI, but its resolution failed.",
                    "type": "rest",
                },
            )

            resp = self._lookup("https://wrong.url", path)
            self.assertStatus(resp, 400)
            if path == "lookup":
                self.assertTrue(
                    resp.json["message"].startswith(
                        'Lookup for "https://wrong.url" failed with:'
                    )
                )
            else:
                self.assertTrue(
                    resp.json["message"].startswith(
                        'Listing files at "https://wrong.url" failed with:'
                    )
                )

    def testPublishers(self):
        # This assumes some defaults that probably should be set here instead...
        resp = self.request(path="/repository", method="GET")
        self.assertStatusOk(resp)
        self.assertEqual(resp.json, [])

        # Pretend we have authorized with DataONE
        self.user["otherTokens"] = [
            {
                "provider": "dataone",
                "access_token": "dataone_token",
                "resource_server": "cn-stage.test.dataone.org",
                "token_type": "dataone",
            }
        ]
        self.user = User().save(self.user)

        resp = self.request(path="/repository", method="GET", user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(
            resp.json,
            [
                {
                    "name": "DataONE Dev",
                    "repository": "https://dev.nceas.ucsb.edu/knb/d1/mn",
                }
            ],
        )

        # Pretend we have authorized with DataONE and Zenodo
        self.user["otherTokens"].append(
            {
                "provider": "zenodo",
                "access_token": "zenodo_key",
                "resource_server": "sandbox.zenodo.org",
                "token_type": "apikey",
            }
        )
        self.user = User().save(self.user)

        resp = self.request(path="/repository", method="GET", user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(
            resp.json,
            [
                {
                    "name": "DataONE Dev",
                    "repository": "https://dev.nceas.ucsb.edu/knb/d1/mn",
                },
                {"name": "Zenodo Sandbox", "repository": "sandbox.zenodo.org"},
            ],
        )
