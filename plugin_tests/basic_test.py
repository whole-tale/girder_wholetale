#!/usr/bin/env python
# -*- coding: utf-8 -*-

import hashlib
import json
import tempfile
import os
from tests import base
from six.moves import urllib
from girder.models.upload import Upload
from girder.exceptions import GirderException
from girder.models.assetstore import Assetstore

DATA_PATH = os.path.join(
    os.path.dirname(os.environ["GIRDER_TEST_DATA_PREFIX"]),
    "data_src",
    "plugins",
    "wholetale",
)


def setUpModule():
    base.enabledPlugins.append('wholetale')
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


class WholeTaleTestCase(base.TestCase):

    def setUp(self):
        super(WholeTaleTestCase, self).setUp()
        users = ({
            'email': 'root@dev.null',
            'login': 'admin',
            'firstName': 'Root',
            'lastName': 'van Klompf',
            'password': 'secret'
        }, {
            'email': 'joe@dev.null',
            'login': 'joeregular',
            'firstName': 'Joe',
            'lastName': 'Regular',
            'password': 'secret'
        })
        self.admin, self.user = [self.model('user').createUser(**user)
                                 for user in users]

    def testListing(self):
        user = self.user
        c1 = self.model('collection').createCollection('c1', user)
        f1 = self.model('folder').createFolder(
            c1, 'f1', parentType='collection')
        i1 = self.model('item').createItem('i1', user, f1)

        fname = os.path.join(DATA_PATH, "logo.png")
        size = os.path.getsize(fname)
        with open(fname, "rb") as f:
            Upload().uploadFromFile(f, size, "i1", "item", i1, user)

        f2 = self.model('folder').createFolder(f1, 'f2', parentType='folder')
        i2 = self.model('item').createItem('i2', user, f2)
        with open(fname, "rb") as f:
            Upload().uploadFromFile(f, size, "i2", "item", i2, user)

        resp = self.request(
            path='/folder/{_id}/listing'.format(**f1), method='GET',
            user=user)
        self.assertStatusOk(resp)
        current_dir = resp.json
        self.assertEqual(current_dir["name"], "/")
        self.assertEqual(len(current_dir["children"]), 2)
        with open(fname, "rb") as f:
            chksum = hashlib.sha512(f.read()).hexdigest()

        host_path = os.path.join(
            Assetstore().getCurrent().get("root"), chksum[0:2], chksum[2:4], chksum
        )

        for child in current_dir["children"]:
            self.assertTrue(child["name"] in {"i1", "f2"})
            if child["name"] == "i1":
                self.assertEqual(
                    child,
                    {
                        "children": [],
                        "host_path": host_path,
                        "name": "i1",
                        "type": 1,
                    }
                )
            else:
                self.assertEqual(
                    child,
                    {
                        "children": [
                            {
                                "children": [],
                                "host_path": host_path,
                                "name": "i2",
                                "type": 1,
                            }
                        ],
                        "name": "f2",
                        "type": 0,
                    }
                )

    def testHubRoutes(self):
        from girder.plugins.wholetale.constants import API_VERSION
        resp = self.request(path='/wholetale', method='GET')
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['api_version'], API_VERSION)

    def testUserSettings(self):
        resp = self.request(path='/user/settings', method='GET')
        self.assertStatus(resp, 401)

        resp = self.request(
            path='/user/settings', method='PUT', user=self.user,
            type='application/json',
            body=json.dumps({'key1': 1, 'key2': 'value2'}))
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['meta']['key1'], 1)
        self.assertEqual(resp.json['meta']['key2'], 'value2')

        resp = self.request(
            path='/user/settings', method='GET', user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(resp.json, {'key1': 1, 'key2': 'value2'})

        resp = self.request(
            path='/user/settings', method='PUT', user=self.user,
            type='application/json',
            body=json.dumps({'key1': 2, 'key2': None}))
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['meta']['key1'], 2)
        self.assertNotIn('key2', resp.json['meta'])

    def testListingResources(self):
        user = self.user
        c1 = self.model('collection').createCollection('c1', user)
        f1 = self.model('folder').createFolder(
            c1, 'f1', parentType='collection')
        f2 = self.model('folder').createFolder(
            c1, 'f2', parentType='collection')
        i1 = self.model('item').createItem('i1', user, f1)
        i2 = self.model('item').createItem('i2', user, f1)

        data = {'item': [str(i1['_id']), str(i2['_id'])]}
        items = []
        for item in (i1, i2):
            resp = self.request(
                path='/item/{_id}'.format(**item), user=self.user)
            items.append(resp.json)

        resp = self.request(
            path='/resource', method='GET', user=self.user,
            params={'resources': json.dumps(data)})
        self.assertStatusOk(resp)
        self.assertEqual('folder' in resp.json, False)
        for iel, el in enumerate(resp.json['item']):
            for key in el:
                if key in ('lowerName', ):
                    continue
                self.assertEqual(el[key], items[iel][key])

        data = {'item': [str(i1['_id'])],
                'folder': [str(f1['_id']), str(f2['_id'])],
                'blah': []}
        folders = []
        for folder in (f1, f2):
            resp = self.request(
                path='/folder/{_id}'.format(**folder), user=self.user)
            folders.append(resp.json)

        resp = self.request(
            path='/resource', method='GET', user=self.user,
            params={'resources': json.dumps(data)})
        self.assertStatusOk(resp)
        self.assertEqual('item' in resp.json, True)
        for iel, el in enumerate(resp.json['folder']):
            for key in el:
                if key in ('lowerName', 'access'):
                    continue
                self.assertEqual(el[key], folders[iel][key])

        f3 = self.model('folder').createFolder(
            f1, 'f3', parentType='folder')
        self.model('item').createItem('i1', user, f3)
        self.model('item').createItem('i2', user, f3)

        resp = self.request(
            path='/folder/{_id}/dataset'.format(**f1), user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual({_['mountPath'] for _ in resp.json}, {'/i1', '/i2', '/f3'})

    def testSignIn(self):
        from girder.plugins.oauth.constants import PluginSettings
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
        }

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
            "/system/setting", user=self.admin, method="PUT", params=params
        )
        self.assertStatusOk(resp)

        resp = self.request(
            path='/user/sign_in', method='GET', isJson=False,
            params={'redirect': 'https://blah.wholetale.org'})
        self.assertStatus(resp, 303)
        redirect = urllib.parse.urlparse(resp.headers["Location"])
        self.assertEqual(redirect.netloc, 'auth.globus.org')

        resp = self.request(
            path='/user/sign_in', method='GET', user=self.user, isJson=False,
            params={'redirect': 'https://blah.wholetale.org'})
        self.assertStatus(resp, 303)
        self.assertEqual(resp.headers["Location"],
                         "https://blah.wholetale.org")

    def testAuthorize(self):

        # Note: additional instance specific tests in instance_tests
        # Non-instance authorization tests
        resp = self.request(
            path="/user/authorize",
            method="GET",
            isJson=False,
            user=self.user,
        )
        # Assert 400 "Forward auth request required"
        self.assertStatus(resp, 400)

        # Non-instance host with valid user
        resp = self.request(
            user=self.user,
            path="/user/authorize",
            method="GET",
            additionalHeaders=[("X-Forwarded-Host", "docs.wholetale.org"),
                               ("X-Forwarded_Uri", "/")],
            isJson=False,
        )
        self.assertStatus(resp, 200)

        # No user
        resp = self.request(
            path="/user/authorize",
            method="GET",
            additionalHeaders=[("X-Forwarded-Host", "blah.wholetale.org"),
                               ("X-Forwarded-Uri", "/")],
            isJson=False,
        )
        self.assertStatus(resp, 303)
        # Confirm redirect to https://girder.{domain}/api/v1/user/sign_in
        self.assertEqual(resp.headers["Location"],
                         "https://girder.wholetale.org/api/v1/"
                         "user/sign_in?redirect=https://blah.wholetale.org/")

    def testPluginSettings(self):
        self.maxDiff = None
        from girder.plugins.wholetale.constants import PluginSettings, SettingDefault

        # setup basic brand info
        core_settings = [
            {
                "key": "core.brand_name",
                "value": SettingDefault.defaults[PluginSettings.DASHBOARD_TITLE]
            }, {
                "key": "core.banner_color",
                "value": SettingDefault.defaults[PluginSettings.HEADER_COLOR]
            }
        ]
        resp = self.request('/system/setting', user=self.admin, method='PUT',
                            params={'list': json.dumps(core_settings)})
        self.assertStatus(resp, 200)

        # test defaults
        default_settings = {
            PluginSettings.HEADER_COLOR:
                SettingDefault.defaults[PluginSettings.HEADER_COLOR],
            PluginSettings.DASHBOARD_TITLE:
                SettingDefault.defaults[PluginSettings.DASHBOARD_TITLE],
            PluginSettings.CATALOG_LINK_TITLE:
                SettingDefault.defaults[PluginSettings.CATALOG_LINK_TITLE],
            PluginSettings.DASHBOARD_LINK_TITLE:
                SettingDefault.defaults[PluginSettings.DASHBOARD_LINK_TITLE],
            PluginSettings.DASHBOARD_URL: 'https://dashboard.wholetale.org',
            PluginSettings.ENABLE_DATA_CATALOG:
                SettingDefault.defaults[PluginSettings.ENABLE_DATA_CATALOG],
            PluginSettings.LOGO: '',
            PluginSettings.WEBSITE_URL:
                SettingDefault.defaults[PluginSettings.WEBSITE_URL],
            PluginSettings.ABOUT_HREF: SettingDefault.defaults[PluginSettings.ABOUT_HREF],
            PluginSettings.CONTACT_HREF: SettingDefault.defaults[PluginSettings.CONTACT_HREF],
            PluginSettings.BUG_HREF: SettingDefault.defaults[PluginSettings.BUG_HREF],
        }

        resp = self.request('/wholetale/settings', user=self.admin, method='GET')
        self.assertStatus(resp, 200)
        self.assertEqual(resp.json, default_settings)

        # test validation
        test_settings = {
            PluginSettings.WEBSITE_URL: ('not_a_url', 'Invalid  URL'),
            PluginSettings.DASHBOARD_LINK_TITLE: (1, 'The setting is not a string'),
            PluginSettings.CATALOG_LINK_TITLE: (1, 'The setting is not a string'),
            PluginSettings.ENABLE_DATA_CATALOG: ('not_a_boolean', 'The setting is not a boolean'),
        }

        for key, value in test_settings.items():
            resp = self.request('/system/setting', user=self.admin, method='PUT',
                                params={'key': key,
                                        'value': value[0]})
            self.assertStatus(resp, 400)
            self.assertEqual(resp.json, {
                'field': 'value',
                'type': 'validation',
                'message': value[1]
            })

        # test set default settings
        for key in test_settings.keys():
            resp = self.request('/system/setting', user=self.admin, method='PUT',
                                params={'key': key,
                                        'value': ''})
            self.assertStatus(resp, 200)

        resp = self.request('/wholetale/settings', user=self.admin, method='GET')
        self.assertStatus(resp, 200)

        # test logo
        col = self.model('collection').createCollection('WholeTale Assets', self.admin,
                                                        public=False, reuseExisting=True)
        folder = self.model('folder').createFolder(col, "Logo", parentType='collection',
                                                   public=True, reuseExisting=True)
        item = self.model('item').createItem('logo.png', self.admin, folder)

        fname = os.path.join(DATA_PATH, "logo.png")
        size = os.path.getsize(fname)

        with open(fname, 'rb') as f:
            Upload().uploadFromFile(f, size, "logo.png", 'item', item, self.admin)

        resp = self.request('/resource/lookup', user=self.admin, method='GET',
                            params={'path': '/collection/WholeTale Assets/Logo/logo.png/logo.png'})
        self.assertStatus(resp, 200)
        logoId = resp.json['_id']

        resp = self.request('/system/setting', user=self.admin, method='PUT',
                            params={'key': PluginSettings.LOGO, 'value': logoId})
        self.assertStatus(resp, 200)

        resp = self.request('/wholetale/settings', user=self.admin, method='GET')
        logoPath = resp.json['wholetale.logo']
        self.assertEqual(logoPath, f'file/{logoId}/download?contentDisposition=inline')

        resp = self.request('/wholetale/assets', user=self.admin, method='GET')
        logoAssetFolderId = resp.json['wholetale.logo']
        self.assertEqual(logoAssetFolderId, str(folder['_id']))
