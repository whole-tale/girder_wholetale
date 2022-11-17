#!/usr/bin/env python
# -*- coding: utf-8 -*-

###############################################################################
#  Copyright 2014 Kitware Inc.
#
#  Licensed under the Apache License, Version 2.0 ( the "License" );
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

import datetime
import json

import httmock
import requests
import six
from girder.models.token import Token
from girder.models.user import User
from six.moves import urllib
from tests import base


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.startServer()


def tearDownModule():
    base.stopServer()


class OauthTest(base.TestCase):
    def setUp(self):
        base.TestCase.setUp(self)

        # girder.plugins is not available until setUp is running
        global PluginSettings
        from girder.plugins.oauth.constants import PluginSettings

        self.adminUser = User().createUser(
            email="rocky@phila.pa.us",
            login="rocky",
            firstName="Robert",
            lastName="Balboa",
            password="adrian",
            admin=True,
        )

        # Specifies which test account (typically 'new' or 'existing') a
        # redirect to a provider will simulate authentication for
        self.accountType = None

    def _testOauth(self, providerInfo):
        # Set up provider normally
        params = {
            "list": json.dumps(
                [
                    {
                        "key": PluginSettings.PROVIDERS_ENABLED,
                        "value": [providerInfo["id"]],
                    },
                    {
                        "key": providerInfo["client_id"]["key"],
                        "value": providerInfo["client_id"]["value"],
                    },
                    {
                        "key": providerInfo["client_secret"]["key"],
                        "value": providerInfo["client_secret"]["value"],
                    },
                ]
            )
        }
        resp = self.request(
            "/system/setting", user=self.adminUser, method="PUT", params=params
        )
        self.assertStatusOk(resp)

        # This will need to be called several times, to get fresh tokens
        def getProviderResp():
            resp = self.request(
                "/oauth/provider",
                params={"redirect": "http://localhost/#foo/bar", "list": True},
            )
            self.assertStatusOk(resp)
            self.assertIsInstance(resp.json, list)
            self.assertEqual(len(resp.json), 1)
            providerResp = resp.json[0]
            self.assertSetEqual(set(six.viewkeys(providerResp)), {"id", "name", "url"})
            self.assertEqual(providerResp["id"], providerInfo["id"])
            self.assertEqual(providerResp["name"], providerInfo["name"])
            six.assertRegex(self, providerResp["url"], providerInfo["url_re"])
            redirectParams = urllib.parse.parse_qs(
                urllib.parse.urlparse(providerResp["url"]).query
            )
            csrfTokenParts = redirectParams["state"][0].partition(".")
            token = Token().load(csrfTokenParts[0], force=True, objectId=False)
            self.assertLess(
                token["expires"],
                datetime.datetime.utcnow() + datetime.timedelta(days=0.30),
            )
            self.assertEqual(csrfTokenParts[2], "http://localhost/#foo/bar")
            return providerResp

        # This will need to be called several times, to use fresh tokens
        def getCallbackParams(providerResp):
            resp = requests.get(providerResp["url"], allow_redirects=False)
            self.assertEqual(resp.status_code, 302)
            callbackLoc = urllib.parse.urlparse(resp.headers["location"])
            self.assertEqual(
                callbackLoc.path, r"/api/v1/oauth/%s/callback" % providerInfo["id"]
            )
            callbackLocQuery = urllib.parse.parse_qs(callbackLoc.query)
            self.assertNotHasKeys(callbackLocQuery, ("error",))
            callbackParams = {
                key: val[0] for key, val in six.viewitems(callbackLocQuery)
            }
            return callbackParams

        # This will need to be called several times, and will do a normal login
        def doOauthLogin(accountType):
            self.accountType = accountType
            params = getCallbackParams(getProviderResp())
            resp = self.request(
                "/oauth/%s/callback" % providerInfo["id"], params=params, isJson=False
            )
            self.assertStatus(resp, 303)
            self.assertEqual(resp.headers["Location"], "http://localhost/#foo/bar")
            self.assertTrue("girderToken" in resp.cookie)

            resp = self.request("/user/me", token=resp.cookie["girderToken"].value)
            user = resp.json
            self.assertStatusOk(resp)
            self.assertEqual(
                user["email"], providerInfo["accounts"][accountType]["user"]["email"]
            )
            self.assertEqual(
                user["login"], providerInfo["accounts"][accountType]["user"]["login"]
            )
            self.assertEqual(
                user["firstName"],
                providerInfo["accounts"][accountType]["user"]["firstName"],
            )
            self.assertEqual(
                user["lastName"],
                providerInfo["accounts"][accountType]["user"]["lastName"],
            )
            return user

        # Try callback for the 'existing' account, which should succeed
        existing = doOauthLogin("existing")
        self.assertEqual(existing["otherTokens"][0]["access_token"], "some_token")

        existing = doOauthLogin("existing")
        self.assertEqual(len(existing["otherTokens"]), 1)
        self.assertEqual(existing["otherTokens"][0]["access_token"], "some_token")

    @httmock.all_requests
    def mockOtherRequest(self, url, request):
        raise Exception("Unexpected url %s" % str(request.url))

    def testGlobusOauth(self):  # noqa
        providerInfo = {
            "id": "globus",
            "name": "Globus",
            "client_id": {
                "key": PluginSettings.GLOBUS_CLIENT_ID,
                "value": "globus_test_client_id",
            },
            "client_secret": {
                "key": PluginSettings.GLOBUS_CLIENT_SECRET,
                "value": "globus_test_client_secret",
            },
            "scope": "urn:globus:auth:scope:auth.globus.org:view_identities openid profile email",
            "allowed_callback_re": r"^http://127\.0\.0\.1(?::\d+)?/api/v1/oauth/globus/callback$",
            "url_re": r"^https://auth.globus.org/v2/oauth2/authorize",
            "accounts": {
                "existing": {
                    "auth_code": "globus_existing_auth_code",
                    "access_token": "globus_existing_test_token",
                    "id_token": "globus_exisiting_id_token",
                    "user": {
                        "login": self.adminUser["login"],
                        "email": self.adminUser["email"],
                        "firstName": self.adminUser["firstName"],
                        "lastName": self.adminUser["lastName"],
                        "oauth": {"provider": "globus", "id": "2399"},
                    },
                },
                "new": {
                    "auth_code": "globus_new_auth_code",
                    "access_token": "globus_new_test_token",
                    "id_token": "globus_new_id_token",
                    "user": {
                        "login": "metaphor",
                        "email": "metaphor@labs.ussr.gov",
                        "firstName": "Ivan",
                        "lastName": "Drago",
                        "oauth": {"provider": "globus", "id": 1985},
                    },
                },
            },
        }

        @httmock.urlmatch(
            scheme="https",
            netloc="^auth.globus.org$",
            path="^/v2/oauth2/authorize$",
            method="GET",
        )
        def mockGlobusRedirect(url, request):
            params = urllib.parse.parse_qs(url.query)
            state = params["state"][0]
            returnQuery = urllib.parse.urlencode(
                {
                    "state": state,
                    "code": providerInfo["accounts"][self.accountType]["auth_code"],
                }
            )
            return {
                "status_code": 302,
                "headers": {
                    "Location": "%s?%s" % (params["redirect_uri"][0], returnQuery)
                },
            }

        @httmock.urlmatch(
            scheme="https",
            netloc="^auth.globus.org$",
            path="^/v2/oauth2/userinfo$",
            method="GET",
        )
        def mockGlobusUserInfo(url, request):
            for account in six.viewvalues(providerInfo["accounts"]):
                if (
                    "Bearer %s" % account["access_token"]
                    == request.headers["Authorization"]
                ):
                    break
            else:
                self.fail()
            user = account["user"]
            return json.dumps(
                {
                    "email": user["email"],
                    "preferred_username": user["email"],
                    "sub": user["oauth"]["id"],
                    "name": "{firstName} {lastName}".format(**user),
                }
            )

        @httmock.urlmatch(
            scheme="https",
            netloc="^auth.globus.org$",
            path="^/v2/oauth2/token$",
            method="POST",
        )
        def mockGlobusToken(url, request):
            params = urllib.parse.parse_qs(request.body)
            for account in six.viewvalues(providerInfo["accounts"]):
                if account["auth_code"] == params["code"][0]:
                    break
            else:
                self.fail()
            returnBody = json.dumps(
                {
                    "access_token": account["access_token"],
                    "resource_server": "auth.globus.org",
                    "expires_in": 3600,
                    "token_type": "bearer",
                    "scope": "urn:globus:auth:scope:auth.globus.org:monitor_ongoing",
                    "refresh_token": "blah",
                    "id_token": account["id_token"],
                    "state": "provided_by_client_to_prevent_replay_attacks",
                    "other_tokens": [
                        {
                            "access_token": "some_token",
                            "expires_in": 172800,
                            "refresh_token": "some_refresh_token",
                            "resource_server": "transfer.api.globus.org",
                            "scope": "urn:globus:auth:scope:transfer.api.globus.org:all",
                            "state": "provided_by_client_to_prevent_replay_attacks",
                            "token_type": "Bearer",
                        }
                    ],
                }
            )
            return {
                "status_code": 200,
                "headers": {"Content-Type": "application/json"},
                "content": returnBody,
            }

        with httmock.HTTMock(
            mockGlobusRedirect,
            mockGlobusUserInfo,
            mockGlobusToken,
            # Must keep 'mockOtherRequest' last
            self.mockOtherRequest,
        ):
            self._testOauth(providerInfo)
