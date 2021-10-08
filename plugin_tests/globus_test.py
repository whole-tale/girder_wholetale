import httmock
import io
import json
import mock
import os
import vcr
import zipfile
from tests import base
from urllib.parse import urlparse, parse_qs
from girder.models.folder import Folder
from girder.models.setting import Setting
from girder.models.user import User


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.startServer()


def tearDownModule():
    base.stopServer()


class GlobusProviderTestCase(base.TestCase):
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
        self.user["otherTokens"] = [
            {
                "access_token": "totally_legit_globus_token",
                "scope": "urn:globus:auth:scope:transfer.api.globus.org:all",
                "expires_in": 172800,
                "token_type": "Bearer",
                "resource_server": "transfer.api.globus.org",
                "state": "before_the_dot.https://doesexist.not/#",
                "refresh_token": "globus_sdk_would_never_accept_bogus_token",
            }
        ]
        self.user = User().save(self.user)

    def testLookup(self):
        resolved_lookup = {
            "dataId": (
                "https://acdc.alcf.anl.gov/mdf/detail/"
                "pub_30_shahani_twinmediated_v1.2/"
            ),
            "doi": "doi:10.18126/M2301J",
            "name": "Twin-mediated Crystal Growth: an Enigma Resolved",
            "repository": "Globus",
            "size": -1,
            "tale": False,
        }

        resp = self.request(
            path="/repository/lookup",
            method="GET",
            user=self.user,
            params={
                "dataId": json.dumps(
                    [
                        "doi:10.18126/M2301J",
                        (
                            "https://acdc.alcf.anl.gov/mdf/detail/"
                            "pub_30_shahani_twinmediated_v1.2/"
                        ),
                    ]
                )
            },
        )
        self.assertStatus(resp, 200)
        self.assertEqual(resp.json, [resolved_lookup, resolved_lookup])
