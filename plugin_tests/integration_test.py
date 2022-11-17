#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
from urllib.parse import parse_qs, urlparse

import mock
import vcr
from girder.models.setting import Setting
from girder.models.user import User
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


class IntegrationTestCase(base.TestCase):
    def setUp(self):
        super(IntegrationTestCase, self).setUp()
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

    @vcr.use_cassette(os.path.join(DATA_PATH, "dataverse_integration.txt"))
    def testDataverseIntegration(self):
        error_handling_cases = [
            (
                {"fileId": "1234", "siteUrl": "definitely not a URL"},
                "Not a valid URL: siteUrl",
            ),
            ({"siteUrl": "https://dataverse.someplace"}, "No data Id provided"),
            (
                {"fileId": "not_a_number", "siteUrl": "https://dataverse.someplace"},
                "Invalid fileId (should be integer)",
            ),
            (
                {"datasetId": "not_a_number", "siteUrl": "https://dataverse.someplace"},
                "Invalid datasetId (should be integer)",
            ),
        ]

        for params, errmsg in error_handling_cases:
            resp = self.request(
                "/integration/dataverse", method="GET", params=params, user=self.user
            )
            self.assertStatus(resp, 400)
            self.assertEqual(resp.json, {"message": errmsg, "type": "rest"})

        def dv_dataset(flag):
            uri = "https://dataverse.harvard.edu"
            if flag == "dataset_pid":
                uri += "/dataset.xhtml?persistentId=doi:10.7910/DVN/TJCLKP"
            elif flag == "datafile":
                uri += "/api/access/datafile/3371438"
            elif flag == "datafile_pid":
                uri += "/file.xhtml?persistentId=doi:10.7910/DVN/TJCLKP/3VSTKY"
            elif flag == "dataset_id":
                uri += "/api/datasets/3035124"

            return {
                "uri": [uri],
                "name": ["Open Source at Harvard"],
                "asTale": ["True"],
            }

        valid_cases = [
            (
                {"fileId": "3371438", "siteUrl": "https://dataverse.harvard.edu"},
                dv_dataset("dataset_pid"),
            ),
            (
                {
                    "fileId": "3371438",
                    "siteUrl": "https://dataverse.harvard.edu",
                    "fullDataset": False,
                },
                dv_dataset("datafile"),
            ),
            (
                {
                    "filePid": "doi:10.7910/DVN/TJCLKP/3VSTKY",
                    "siteUrl": "https://dataverse.harvard.edu",
                    "fullDataset": False,
                },
                dv_dataset("datafile_pid"),
            ),
            (
                {
                    "filePid": "doi:10.7910/DVN/TJCLKP/3VSTKY",
                    "siteUrl": "https://dataverse.harvard.edu",
                    "fullDataset": True,
                },
                dv_dataset("dataset_pid"),
            ),
            (
                {
                    "datasetPid": "doi:10.7910/DVN/TJCLKP",
                    "siteUrl": "https://dataverse.harvard.edu",
                    "fullDataset": False,
                },
                dv_dataset("dataset_pid"),
            ),
            (
                {
                    "datasetId": "3035124",
                    "siteUrl": "https://dataverse.harvard.edu",
                    "fullDataset": False,
                },
                dv_dataset("dataset_pid"),
            ),
        ]

        for params, response in valid_cases:
            resp = self.request(
                "/integration/dataverse", method="GET", params=params, user=self.user
            )
            self.assertStatus(resp, 303)
            self.assertEqual(
                parse_qs(urlparse(resp.headers["Location"]).query), response
            )

    @vcr.use_cassette(os.path.join(DATA_PATH, "dataone_integration.txt"))
    def testDataoneTaleIntegration(self):
        from girder.plugins.wholetale.models.image import Image

        # Tale case
        image = Image().createImage(name="JupyterLab", creator=self.user, public=True)
        resp = self.request(
            "/integration/dataone",
            method="GET",
            user=self.user,
            params={
                "uri": "urn:uuid:f57b69fe-7001-41d3-80af-87d6a4d77870",
                "api": "https://dev.nceas.ucsb.edu/knb/d1/mn/v2",
            },
            isJson=False,
        )

        self.assertStatus(resp, 303)
        path = urlparse(resp.headers["Location"]).path
        self.assertTrue(path.startswith("/run/"))
        tale_id = path.split("/")[-1]

        resp = self.request(f"/tale/{tale_id}", method="GET", user=self.user)
        self.assertStatusOk(resp)
        tale = resp.json
        gold = [
            {
                "date": "2022-03-07T14:47:33.486Z",
                "pid": "doi:10.5072/FK2SF2W48V",
                "repository": "DataONE",
                "repository_id": "urn:uuid:f57b69fe-7001-41d3-80af-87d6a4d77870",
                "uri": "https://cn.dataone.org/cn/v2/resolve/doi%3A10.5072%2FFK2SF2W48V",
            }
        ]
        self.assertEqual(gold, tale["publishInfo"])
        Image().remove(image)

    def testDataoneNonTaleIntegration(self):
        from girder.plugins.wholetale.lib.data_map import DataMap

        def lookup(entity):
            return DataMap(
                "urn:uuid:12345.6789", 0, base_url="https://some.dataone.cn/"
            )

        with mock.patch(
            "girder.plugins.wholetale.lib.dataone.integration.DataOneImportProvider.lookup",
            side_effect=lookup,
        ):
            resp = self.request(
                "/integration/dataone",
                method="GET",
                user=self.user,
                params={
                    "uri": "urn:uuid:12345.6789",
                    "title": "dataset title",
                    "environment": "rstudio",
                    "api": "https://some.dataone.cn/",
                },
                isJson=False,
            )

        self.assertStatus(resp, 303)
        query = parse_qs(urlparse(resp.headers["Location"]).query)
        self.assertEqual(query["name"][0], "dataset title")
        self.assertEqual(query["uri"][0], "urn:uuid:12345.6789")
        self.assertEqual(query["environment"][0], "rstudio")
        self.assertEqual(query["api"][0], "https://some.dataone.cn/")

    def testAutoLogin(self):
        from girder.plugins.oauth.constants import PluginSettings as OAuthSettings

        Setting().set(OAuthSettings.PROVIDERS_ENABLED, ["globus"])
        Setting().set(OAuthSettings.GLOBUS_CLIENT_ID, "client_id")
        Setting().set(OAuthSettings.GLOBUS_CLIENT_SECRET, "secret_id")

        resp = self.request(
            "/integration/dataverse",
            method="GET",
            params={"fileId": "3371438", "siteUrl": "https://dataverse.harvard.edu"},
            isJson=False,
        )
        self.assertStatus(resp, 303)
        query = parse_qs(urlparse(resp.headers["Location"]).query)
        self.assertIn("state", query)
        redirect = query["state"][0].split(".", 1)[-1]
        query = parse_qs(urlparse(redirect).query)
        self.assertEqual(query["fileId"][0], "3371438")
        self.assertEqual(query["force"][0], "False")
        self.assertEqual(query["siteUrl"][0], "https://dataverse.harvard.edu")

    def testSingletonDataverse(self):
        from bson import ObjectId
        from girder.plugins.wholetale.models.tale import Tale

        tale = Tale().createTale(
            {"_id": ObjectId()},
            [],
            creator=self.user,
            title="Some Tale",
            relatedIdentifiers=[
                {"identifier": "doi:10.7910/DVN/TJCLKP", "relation": "IsDerivedFrom"}
            ],
        )

        resp = self.request(
            "/integration/dataverse",
            method="GET",
            params={
                "datasetId": "3035124",
                "siteUrl": "https://dataverse.harvard.edu",
                "fullDataset": False,
            },
            user=self.user,
            isJson=False,
        )
        self.assertStatus(resp, 303)
        self.assertEqual(
            urlparse(resp.headers["Location"]).path, "/run/{}".format(tale["_id"])
        )
        Tale().remove(tale)

    def tearDown(self):
        User().remove(self.user)
        User().remove(self.admin)
        super(IntegrationTestCase, self).tearDown()
