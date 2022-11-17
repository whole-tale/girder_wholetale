import json
import os

import vcr
from tests import base

DATA_PATH = os.path.join(
    os.path.dirname(os.environ["GIRDER_TEST_DATA_PREFIX"]),
    "data_src",
    "plugins",
    "wholetale",
)


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.startServer()


def tearDownModule():
    base.stopServer()


class DatasetTestCase(base.TestCase):
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

    @vcr.use_cassette(os.path.join(DATA_PATH, "dataset_register.txt"))
    def testDatasetRest(self):
        user_data_map = [
            {
                "dataId": "resource_map_doi:10.5065/D6862DM8",
                "doi": "10.5065/D6862DM8",
                "name": "Humans and Hydrology at High Latitudes: Water Use Information",
                "repository": "DataONE",
                "size": 28856295,
            },
            {
                "dataId": "http://use.yt/upload/9241131f",
                "doi": None,
                "name": "illustris.jpg",
                "repository": "HTTP",
                "size": 781665,
            },
        ]

        admin_data_map = [
            {
                "dataId": "https://dataverse.harvard.edu/dataset.xhtml"
                "?persistentId=doi:10.7910/DVN/TJCLKP",
                "doi": "10.7910/DVN/TJCLKP",
                "name": "Open Source at Harvard",
                "repository": "Dataverse",
                "size": 518379,
            },
            {
                "dataId": "https://search-dev.test.dataone.org/view/tao.14232.1",
                "doi": None,
                "name": "tao.14232.1",
                "repository": "HTTP",
                "size": 6252,
            },
        ]

        resp = self.request(
            path="/dataset/register",
            method="POST",
            params={"dataMap": json.dumps(user_data_map)},
            user=self.user,
        )
        self.assertStatusOk(resp)

        resp = self.request(
            path="/dataset/register",
            method="POST",
            params={"dataMap": json.dumps(admin_data_map)},
            user=self.admin,
        )
        self.assertStatusOk(resp)

        resp = self.request(path="/dataset", method="GET", user=self.user)
        self.assertStatusOk(resp)
        ds = resp.json
        self.assertEqual(len(ds), 4)

        resp = self.request(
            path="/dataset", method="GET", user=self.user, params={"myData": True}
        )
        self.assertStatusOk(resp)
        ds = resp.json
        self.assertEqual(len(ds), 2)

        resp = self.request(
            path="/dataset/{_id}".format(**ds[0]), method="DELETE", user=self.user
        )
        self.assertStatusOk(resp)

        resp = self.request(
            path="/dataset", method="GET", user=self.user, params={"myData": True}
        )
        self.assertStatusOk(resp)
        ds = resp.json
        self.assertEqual(len(ds), 1)

        resp = self.request(
            path="/dataset",
            method="GET",
            user=self.user,
            params={
                "identifiers": json.dumps(
                    ["urn:uuid:62e1a8c5-406b-43f9-9234-1415277674cb"]
                )
            },
        )
        self.assertStatusOk(resp)
        ds = resp.json
        self.assertEqual(len(ds), 1)
        self.assertEqual(ds[0]["name"], "usco2000.xls")
