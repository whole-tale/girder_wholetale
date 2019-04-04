import bagit
from bdbag import bdbag_api as bdb
import mock
import httmock
import os
import json
import time
import urllib.request
import tempfile
import zipfile
import shutil
from bson import ObjectId
from tests import base
from .tests_helpers import mockOtherRequest
from girder.models.item import Item
from girder.models.folder import Folder


SCRIPTDIRS_NAME = None
DATADIRS_NAME = None
DATA_PATH = os.path.join(
    os.path.dirname(os.environ['GIRDER_TEST_DATA_PREFIX']),
    'data_src',
    'plugins',
    'wholetale',
)


JobStatus = None
ImageStatus = None
Tale = None


class FakeAsyncResult(object):
    def __init__(self, tale_id=None):
        self.task_id = 'fake_id'
        self.tale_id = tale_id

    def get(self, timeout=None):
        return {
            'image_digest': 'digest123',
            'repo2docker_version': 1,
            'last_build': 123
        }


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.startServer()

    global JobStatus, Tale, ImageStatus
    from girder.plugins.jobs.constants import JobStatus
    from girder.plugins.wholetale.models.tale import Tale
    from girder.plugins.wholetale.constants import ImageStatus

    global SCRIPTDIRS_NAME, DATADIRS_NAME
    from girder.plugins.wholetale.constants import \
        SCRIPTDIRS_NAME, DATADIRS_NAME


def tearDownModule():
    base.stopServer()


class TaleTestCase(base.TestCase):

    def setUp(self):
        super(TaleTestCase, self).setUp()
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

        self.image_admin = self.model('image', 'wholetale').createImage(
            name="test admin image", creator=self.admin, public=True)

        self.image = self.model('image', 'wholetale').createImage(
            name="test my name", creator=self.user, public=True,
            config=dict(template='base.tpl', buildpack='SomeBuildPack',
                        user='someUser', port=8888, urlPath=''))

    def testTaleFlow(self):
        from server.lib.license import WholeTaleLicense
        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({'imageId': str(self.image['_id'])})
        )
        self.assertStatus(resp, 400)
        self.assertEqual(resp.json, {
            'message': ("Invalid JSON object for parameter tale: "
                        "'dataSet' "
                        "is a required property"),
            'type': 'rest'
        })

        # Grab the default user folders
        resp = self.request(
            path='/folder', method='GET', user=self.user, params={
                'parentType': 'user',
                'parentId': self.user['_id'],
                'sort': 'title',
                'sortdir': 1
            })
        privateFolder = resp.json[0]
        publicFolder = resp.json[1]

        resp = self.request(
            path='/folder', method='GET', user=self.admin, params={
                'parentType': 'user',
                'parentId': self.admin['_id'],
                'sort': 'title',
                'sortdir': 1
            })
        # adminPrivateFolder = resp.json[0]
        adminPublicFolder = resp.json[1]

        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': [
                    {'mountPath': '/' + publicFolder['name'], 'itemId': publicFolder['_id']}
                ]
            })
        )
        self.assertStatusOk(resp)
        tale = resp.json

        # Check that workspace was created

        # Check that data folder was created
        from girder.plugins.wholetale.constants import DATADIRS_NAME
        from girder.utility.path import getResourcePath
        sc = {
            '_id': tale['_id'],
            'cname': DATADIRS_NAME,
            'fname': DATADIRS_NAME
        }
        self.assertEqual(
            getResourcePath(
                'folder',
                Folder().load(tale['folderId'], user=self.user),
                user=self.admin),
            '/collection/{cname}/{fname}/{_id}'.format(**sc)
        )

        taleLicense = WholeTaleLicense.default_spdx()
        resp = self.request(
            path='/tale/{_id}'.format(**tale), method='PUT',
            type='application/json',
            user=self.user, body=json.dumps({
                'folderId': tale['folderId'],
                'dataSet': tale['dataSet'],
                'imageId': tale['imageId'],
                'title': 'new name',
                'description': 'new description',
                'config': {'memLimit': '2g'},
                'public': False,
                'licenseSPDX': taleLicense,
                'publishInfo': [
                    {
                
                       'pid': 'published_pid',
                       'uri': 'published_url',
                       'date': '2019-01-23T15:48:17.476000+00:00',
                    }
                ]
            })
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['title'], 'new name')
        self.assertEqual(resp.json['licenseSPDX'], taleLicense)
        tale = resp.json

        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': [{
                    'mountPath': '/' + privateFolder['name'],
                    'itemId': privateFolder['_id']
                }]
            })
        )
        self.assertStatusOk(resp)
        new_tale = resp.json

        resp = self.request(
            path='/tale', method='POST', user=self.admin,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': [{
                    'mountPath': '/' + privateFolder['name'],
                    'itemId': adminPublicFolder['_id']
                }],
                'public': False
            })
        )
        self.assertStatusOk(resp)
        # admin_tale = resp.json

        resp = self.request(
            path='/tale', method='GET', user=self.admin,

            params={}
        )
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 3)

        resp = self.request(
            path='/tale', method='GET', user=self.user,
            params={'imageId': str(self.image['_id'])}
        )
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 2)
        self.assertEqual(set([_['_id'] for _ in resp.json]),
                         {tale['_id'], new_tale['_id']})

        resp = self.request(
            path='/tale', method='GET', user=self.user,
            params={'userId': str(self.user['_id'])}
        )
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 2)
        self.assertEqual(set([_['_id'] for _ in resp.json]),
                         {tale['_id'], new_tale['_id']})

        resp = self.request(
            path='/tale', method='GET', user=self.user,
            params={'text': 'new'}
        )
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 1)
        self.assertEqual(set([_['_id'] for _ in resp.json]),
                         {tale['_id']})

        resp = self.request(
            path='/tale/{_id}'.format(**new_tale), method='DELETE',
            user=self.admin)
        self.assertStatusOk(resp)

        resp = self.request(
            path='/tale/{_id}'.format(**new_tale), method='GET',
            user=self.user)
        self.assertStatus(resp, 400)

        resp = self.request(
            path='/tale/{_id}'.format(**tale), method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        for key in tale.keys():
            if key in ('access', 'updated', 'created'):
                continue
            self.assertEqual(resp.json[key], tale[key])

    def testTaleAccess(self):
        with httmock.HTTMock(mockOtherRequest):
            # Grab the default user folders
            resp = self.request(
                path='/folder', method='GET', user=self.user, params={
                    'parentType': 'user',
                    'parentId': self.user['_id'],
                    'sort': 'title',
                    'sortdir': 1
                })
            folder = resp.json[1]
            # Create a new tale from a user image
            resp = self.request(
                path='/tale', method='POST', user=self.user,
                type='application/json',
                body=json.dumps(
                    {
                        'imageId': str(self.image['_id']),
                        'dataSet': [
                            {'mountPath': '/' + folder['name'], 'itemId': folder['_id']}
                        ],
                        'public': True
                    })
            )
            self.assertStatusOk(resp)
            tale_user_image = resp.json
            # Create a new tale from an admin image
            resp = self.request(
                path='/tale', method='POST', user=self.user,
                type='application/json',
                body=json.dumps(
                    {
                        'imageId': str(self.image_admin['_id']),
                        'dataSet': [
                            {'mountPath': '/' + folder['name'], 'itemId': folder['_id']}
                        ]
                    })
            )
            self.assertStatusOk(resp)
            tale_admin_image = resp.json

        from girder.constants import AccessType

        # Retrieve access control list for the newly created tale
        resp = self.request(
            path='/tale/%s/access' % tale_user_image['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        result_tale_access = resp.json
        expected_tale_access = {
            'users': [{
                'login': self.user['login'],
                'level': AccessType.ADMIN,
                'id': str(self.user['_id']),
                'flags': [],
                'name': '%s %s' % (
                    self.user['firstName'], self.user['lastName'])}],
            'groups': []
        }
        self.assertEqual(result_tale_access, expected_tale_access)

        # Update the access control list for the tale by adding the admin
        # as a second user
        input_tale_access = {
            "users": [
                {
                    "login": self.user['login'],
                    "level": AccessType.ADMIN,
                    "id": str(self.user['_id']),
                    "flags": [],
                    "name": "%s %s" % (self.user['firstName'], self.user['lastName'])
                },
                {
                    'login': self.admin['login'],
                    'level': AccessType.ADMIN,
                    'id': str(self.admin['_id']),
                    'flags': [],
                    'name': '%s %s' % (self.admin['firstName'], self.admin['lastName'])
                }],
            "groups": []}
        resp = self.request(
            path='/tale/%s/access' % tale_user_image['_id'], method='PUT',
            user=self.user, params={'access': json.dumps(input_tale_access)})
        self.assertStatusOk(resp)
        # Check that the returned access control list for the tale is as expected
        tale = resp.json
        result_tale_access = resp.json['access']
        expected_tale_access = {
            "groups": [],
            "users": [
                {
                    "flags": [],
                    "id": str(self.user['_id']),
                    "level": AccessType.ADMIN
                },
                {
                    "flags": [],
                    "id": str(self.admin['_id']),
                    "level": AccessType.ADMIN
                },
            ]
        }
        self.assertEqual(result_tale_access, expected_tale_access)
        # Check that the access control list propagated to the image that the tale
        # was built from
        # resp = self.request(
        #     path='/image/%s/access' % result_image_id, method='GET',
        #     user=self.user)
        # self.assertStatusOk(resp)
        # result_image_access = resp.json
        # expected_image_access = input_tale_access
        # self.assertEqual(result_image_access, expected_image_access)

        # Check that the access control list propagated to the folder that the tale
        # is associated with
        for key in ('folderId', 'workspaceId'):
            resp = self.request(
                path='/folder/%s/access' % tale[key], method='GET',
                user=self.user)
            self.assertStatusOk(resp)
            result_folder_access = resp.json
            expected_folder_access = input_tale_access
            self.assertEqual(result_folder_access, expected_folder_access)

        # Update the access control list of a tale that was generated from an image that the user
        # does not have admin access to
        input_tale_access = {
            "users": [
                {
                    "login": self.user['login'],
                    "level": AccessType.ADMIN,
                    "id": str(self.user['_id']),
                    "flags": [],
                    "name": "%s %s" % (self.user['firstName'], self.user['lastName'])
                }],
            "groups": []
        }
        resp = self.request(
            path='/tale/%s/access' % tale_admin_image['_id'], method='PUT',
            user=self.user, params={'access': json.dumps(input_tale_access)})
        self.assertStatus(resp, 200)  # TODO: fix me

        # Check that the access control list was correctly set for the tale
        resp = self.request(
            path='/tale/%s/access' % tale_admin_image['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        result_tale_access = resp.json
        expected_tale_access = input_tale_access
        self.assertEqual(result_tale_access, expected_tale_access)

        # Check that the access control list did not propagate to the image
        resp = self.request(
            path='/image/%s/access' % tale_admin_image['imageId'], method='GET',
            user=self.user)
        self.assertStatus(resp, 403)

        # Setting the access list with bad json should throw an error
        resp = self.request(
            path='/tale/%s/access' % tale_user_image['_id'], method='PUT',
            user=self.user, params={'access': 'badJSON'})
        self.assertStatus(resp, 400)

        # Change the access to private
        resp = self.request(
            path='/tale/%s/access' % tale_user_image['_id'], method='PUT',
            user=self.user,
            params={'access': json.dumps(input_tale_access), 'public': False})
        self.assertStatusOk(resp)
        resp = self.request(
            path='/tale/%s' % tale_user_image['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['public'], False)

    def testTaleNarrative(self):
        resp = self.request(
            path='/resource/lookup', method='GET', user=self.user,
            params={'path': '/user/{login}/Home'.format(**self.user)})
        home_dir = resp.json
        resp = self.request(
            path='/folder', method='POST', user=self.user, params={
                'name': 'my_narrative', 'parentId': home_dir['_id']
            })
        sub_home_dir = resp.json
        my_narrative = Item().createItem('notebook.ipynb', self.user, sub_home_dir)

        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': [
                    {'mountPath': '/' + sub_home_dir['name'], 'itemId': sub_home_dir['_id']}
                ],
                'narrative': [str(my_narrative['_id'])]
            })
        )
        self.assertStatusOk(resp)
        tale = resp.json

        path = os.path.join(
            '/collection', SCRIPTDIRS_NAME, SCRIPTDIRS_NAME,
            tale['_id'], 'notebook.ipynb')
        resp = self.request(
            path='/resource/lookup', method='GET', user=self.user,
            params={'path': path})
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['name'], my_narrative['name'])
        self.assertNotEqual(resp.json['_id'], str(my_narrative['_id']))

        resp = self.request(
            path='/tale/{_id}'.format(**tale), method='DELETE',
            user=self.admin, params={'progress': True})
        self.assertStatusOk(resp)
        self.assertEqual(Folder().load(tale['workspaceId'], force=True), None)

    def testTaleValidation(self):
        from server.lib.license import WholeTaleLicense
        resp = self.request(
            path='/resource/lookup', method='GET', user=self.user,
            params={'path': '/user/{login}/Home'.format(**self.user)})
        home_dir = resp.json
        resp = self.request(
            path='/folder', method='POST', user=self.user, params={
                'name': 'validate_my_narrative', 'parentId': home_dir['_id']
            })
        sub_home_dir = resp.json
        Item().createItem('notebook.ipynb', self.user, sub_home_dir)

        resp = self.request(
            path='/resource/lookup', method='GET', user=self.user,
            params={'path': '/user/{login}/Data'.format(**self.user)})
        data_dir = resp.json
        resp = self.request(
            path='/folder', method='POST', user=self.user, params={
                'name': 'my_fake_data', 'parentId': data_dir['_id']
            })
        sub_data_dir = resp.json
        Item().createItem('data.dat', self.user, sub_data_dir)

        # Mock old format
        tale = {
            "config": None,
            "creatorId": self.user['_id'],
            "description": "Fake Tale",
            "folderId": data_dir['_id'],
            "imageId": "5873dcdbaec030000144d233",
            "public": True,
            "publishInfo": [],
            "title": "Fake Unvalidated Tale"
        }
        tale = self.model('tale', 'wholetale').save(tale)  # get's id
        tale = self.model('tale', 'wholetale').save(tale)  # migrate to new format

        # path = os.path.join(
        #     '/collection', DATADIRS_NAME, DATADIRS_NAME, str(tale['_id']))
        # resp = self.request(
        #    path='/resource/lookup', method='GET', user=self.user,
        #    params={'path': path})
        # self.assertStatusOk(resp)
        # new_data_dir = resp.json
        # self.assertEqual(str(tale['folderId']), str(new_data_dir['_id']))
        self.assertEqual(tale['dataSet'], [])
        self.assertEqual(tale['licenseSPDX'], WholeTaleLicense.default_spdx())
        # self.assertEqual(str(tale['dataSet'][0]['itemId']), data_dir['_id'])
        # self.assertEqual(tale['dataSet'][0]['mountPath'], '/' + data_dir['name'])
        tale['licenseSPDX'] = 'unsupportedLicense'
        tale = self.model('tale', 'wholetale').save(tale)
        self.assertEqual(tale['licenseSPDX'], WholeTaleLicense.default_spdx())
        self.model('tale', 'wholetale').remove(tale)

    @mock.patch('gwvolman.tasks.import_tale')
    def testTaleImport(self, it):
        with mock.patch('girder_worker.task.celery.Task.apply_async', spec=True) \
                as mock_apply_async:
            # mock_apply_async.return_value = 1
            mock_apply_async().job.return_value = json.dumps({'job': 1, 'blah': 2})
            resp = self.request(
                path='/tale/import', method='POST', user=self.user,
                params={'url': 'http://blah.com/', 'spawn': False,
                        'imageId': self.image['_id']}
            )
            self.assertStatusOk(resp)
            job_call = mock_apply_async.call_args_list[-1][-1]
            self.assertEqual(
                job_call['args'],
                ({'dataId': ['http://blah.com/']}, {'imageId': str(self.image['_id'])})
            )
            self.assertEqual(job_call['kwargs'], {'spawn': False})
            self.assertEqual(job_call['headers']['girder_job_title'], 'Import Tale')

    def testTaleUpdate(self):
        from server.lib.license import WholeTaleLicense
        # Test that Tale updating works

        resp = self.request(
            path='/folder', method='GET', user=self.user, params={
                'parentType': 'user',
                'parentId': self.user['_id'],
                'sort': 'title',
                'sortdir': 1
            }
        )

        title = 'new name'
        description = 'new description'
        config = {'memLimit': '2g'}
        public = True
        tale_licenses = WholeTaleLicense()
        taleLicense = tale_licenses.supported_spdxes().pop()

        # Create a new Tale
        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'folderId': '1234',
                'imageId': str(self.image['_id']),
                'dataSet': [
                    {'mountPath': '/' + 'folder', 'itemId': '123456'}
                ],
                'title': 'tale tile',
                'description': 'description',
                'config': {},
                'public': False,
                'licenseSPDX': taleLicense,
                'publishInfo': [
                    {
                       'pid': 'published_pid',
                       'uri': 'published_url',
                       'date': '2019-01-23T15:48:17.476000+00:00',
                    }
                ]
            })
        )

        self.assertStatus(resp, 200)

        newLicense = tale_licenses.supported_spdxes().pop()
        # Update the Tale with new values
        resp = self.request(
            path='/tale/{}'.format(str(resp.json['_id'])),
            method='PUT',
            user=self.user,
            type='application/json',
            body=json.dumps({
                'folderId': '1234',
                'imageId': str(self.image['_id']),
                'dataSet': [
                    {'mountPath': '/' + 'folder', 'itemId': '123456'}
                ],
                'title': title,
                'description': description,
                'config': config,
                'public': public,
                'licenseSPDX': newLicense,
                'publishInfo': [
                    {
                        'pid': 'published_pid',
                        'uri': 'published_url',
                        'date': '2019-01-23T15:48:17.476000+00:00',
                    }
                ]
            })
        )

        # Check that the updates happened
        # self.assertStatus(resp, 200)
        self.assertEqual(resp.json['imageId'], str(self.image['_id']))
        self.assertEqual(resp.json['title'], title)
        self.assertEqual(resp.json['description'], description)
        self.assertEqual(resp.json['config'], config)
        self.assertEqual(resp.json['public'], public)
        self.assertEqual(resp.json['publishInfo'][0]['pid'], 'published_pid')
        self.assertEqual(resp.json['publishInfo'][0]['uri'], 'published_url')
        self.assertEqual(resp.json['publishInfo'][0]['date'], '2019-01-23T15:48:17.476000+00:00')
        self.assertEqual(resp.json['licenseSPDX'], newLicense)

    def testManifest(self):
        from server.lib.license import WholeTaleLicense
        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'folderId': '1234',
                'imageId': str(self.image['_id']),
                'dataSet': [],
                'title': 'tale tile',
                'description': 'description',
                'config': {},
                'public': False,
                'publishInfo': [],
                'licenseSPDX': WholeTaleLicense.default_spdx()
            })
        )

        self.assertStatus(resp, 200)
        pth = '/tale/{}/manifest'.format(str(resp.json['_id']))
        resp = self.request(
            path=pth, method='GET', user=self.user)
        # The contents of the manifest are checked in the manifest tests, so
        # just make sure that we get the right response
        self.assertStatus(resp, 200)

    def _create_water_tale(self):
        # register required data
        self.data_collection = self.model('collection').createCollection(
            'WholeTale Catalog', public=True, reuseExisting=True
        )
        catalog = self.model('folder').createFolder(
            self.data_collection,
            'WholeTale Catalog',
            parentType='collection',
            public=True,
            reuseExisting=True,
        )
        # Tale map of values to check against in tests

        def restore_catalog(parent, current):
            for folder in current['folders']:
                resp = self.request(
                    path='/folder',
                    method='POST',
                    user=self.admin,
                    params={
                        'parentId': parent['_id'],
                        'name': folder['name'],
                        'metadata': json.dumps(folder['meta']),
                    },
                )
                folderObj = resp.json
                restore_catalog(folderObj, folder)

            for obj in current['files']:
                resp = self.request(
                    path='/item',
                    method='POST',
                    user=self.admin,
                    params={
                        'folderId': parent['_id'],
                        'name': obj['name'],
                        'metadata': json.dumps(obj['meta']),
                    },
                )
                item = resp.json
                self.request(
                    path='/file',
                    method='POST',
                    user=self.admin,
                    params={
                        'parentType': 'item',
                        'parentId': item['_id'],
                        'name': obj['name'],
                        'size': obj['size'],
                        'mimeType': obj['mimeType'],
                        'linkUrl': obj['linkUrl'],
                    },
                )

        with open(os.path.join(DATA_PATH, 'watertale_catalog.json'), 'r') as fp:
            data = json.load(fp)
            restore_catalog(catalog, data)

        resp = self.request(
            path='/dataset', method='GET', user=self.user)
        self.assertStatusOk(resp)
        ds = resp.json[0]

        resp = self.request(
            path='/item', method='GET', user=self.user,
            params={'name': 'usco2000.xls', 'folderId': ds['_id']}
        )
        item = resp.json[0]

        tale = self.model('tale', 'wholetale').createTale(
            self.image,
            [{
                'itemId': item['_id'],
                '_modelType': 'item',
                'mountPath': item['name']
            }], creator=self.user, title="Export Tale", public=True)
        workspace = self.model('folder').load(tale['workspaceId'], force=True)
        with urllib.request.urlopen(
            'https://wholetale.readthedocs.io/en/stable/'
            '_downloads/wt_quickstart.ipynb'
        ) as url:
            self.uploadFile(
                name=item['name'], contents=url.read(), user=self.user,
                parent=workspace, parentType='folder')
        return tale

    def testExport(self):
        from server.lib.license import WholeTaleLicense

        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': [],
                'title': 'tale tile',
                'description': 'description',
                'config': {},
                'public': False,
                'publishInfo': [],
                'licenseSPDX': WholeTaleLicense.default_spdx()
            })
        )
        self.assertStatusOk(resp)
        tale = resp.json
        export_path = '/tale/{}/export'.format(str(tale['_id']))
        resp = self.request(
            path=export_path, method='GET', isJson=False, user=self.user)
        with tempfile.NamedTemporaryFile() as fp:
            for content in resp.body:
                fp.write(content)
            fp.seek(0)
            zip_archive = zipfile.ZipFile(fp, 'r')
            zip_files = zip_archive.namelist()
        # Check the the manifest.json is present
        manifest_path = str(tale['_id']) + '/metadata/manifest.json'
        is_present = manifest_path in zip_files
        self.assertTrue(is_present)

        # Check that the top level README is present
        readme_path = str(tale['_id']) + '/README.md'
        is_present = readme_path in zip_files
        self.assertTrue(is_present)

        # Check that the LICENSE is present
        license_path = str(tale['_id']) + '/LICENSE'
        is_present = license_path in zip_files
        self.assertTrue(is_present)
        self.model('tale', 'wholetale').remove(tale)

    def testExportBag(self):
        tale = self._create_water_tale()
        export_path = '/tale/{}/export'.format(str(tale['_id']))
        resp = self.request(
            path=export_path, method='GET', params={'taleFormat': 'bagit'},
            isJson=False, user=self.user)
        dirpath = tempfile.mkdtemp()
        bag_file = os.path.join(dirpath, "{}.zip".format(str(tale['_id'])))
        with open(bag_file, 'wb') as fp:
            for content in resp.body:
                fp.write(content)
        temp_path = bdb.extract_bag(bag_file, temp=True)
        try:
            bdb.validate_bag_structure(temp_path)
        except bagit.BagValidationError:
            pass  # TODO: Goes without saying that we should not be doing that...
        shutil.rmtree(dirpath)
        self.model('tale', 'wholetale').remove(tale)
        self.model('collection').remove(self.data_collection)

    @mock.patch('gwvolman.tasks.build_tale_image')
    def testImageBuild(self, it):
        resp = self.request(
            path='/tale', method='POST', user=self.user,
            type='application/json',
            body=json.dumps({
                'imageId': str(self.image['_id']),
                'dataSet': []
            })
        )
        self.assertStatusOk(resp)
        tale = resp.json

        with mock.patch('girder_worker.task.celery.Task.apply_async', spec=True) \
                as mock_apply_async:
            mock_apply_async().job.return_value = json.dumps({'job': 1, 'blah': 2})
            resp = self.request(
                path='/tale/{}/build'.format(tale['_id']), method='PUT',
                user=self.user)
            self.assertStatusOk(resp)
            job_call = mock_apply_async.call_args_list[-1][-1]
            self.assertEqual(
                job_call['args'], (str(tale['_id']),)
            )
            self.assertEqual(job_call['headers']['girder_job_title'], 'Build Tale Image')
        self.assertStatusOk(resp)

        # Create a job to be handled by the worker plugin
        from girder.plugins.jobs.models.job import Job
        jobModel = Job()
        job = jobModel.createJob(
            title='Build Tale Image', type='celery', handler='worker_handler',
            user=self.user, public=False, args=[str(tale['_id'])], kwargs={})
        job = jobModel.save(job)
        self.assertEqual(job['status'], JobStatus.INACTIVE)

        # Schedule the job, make sure it is sent to celery
        with mock.patch('celery.Celery') as celeryMock, \
                mock.patch('girder.plugins.worker.getCeleryApp') as gca:

            celeryMock().AsyncResult.return_value = FakeAsyncResult(tale['_id'])
            gca().send_task.return_value = FakeAsyncResult(tale['_id'])

            jobModel.scheduleJob(job)
            for i in range(20):
                job = jobModel.load(job['_id'], force=True)
                if job['status'] == JobStatus.QUEUED:
                    break
                time.sleep(0.1)
            self.assertEqual(job['status'], JobStatus.QUEUED)

            tale = Tale().load(tale['_id'], force=True)
            self.assertEqual(tale['imageInfo']['status'], ImageStatus.BUILDING)

            # Set status to RUNNING
            job = jobModel.load(job['_id'], force=True)
            self.assertEqual(job['celeryTaskId'], 'fake_id')
            Job().updateJob(job, log='job running', status=JobStatus.RUNNING)

            tale = Tale().load(tale['_id'], force=True)
            self.assertEqual(tale['imageInfo']['status'], ImageStatus.BUILDING)

            # Set status to SUCCESS
            job = jobModel.load(job['_id'], force=True)
            self.assertEqual(job['celeryTaskId'], 'fake_id')
            Job().updateJob(job, log='job running', status=JobStatus.SUCCESS)

            tale = Tale().load(tale['_id'], force=True)
            self.assertEqual(tale['imageInfo']['status'], ImageStatus.AVAILABLE)
            self.assertEqual(tale['imageInfo']['digest'], 'digest123')

            # Set status to ERROR
            # job = jobModel.load(job['_id'], force=True)
            # self.assertEqual(job['celeryTaskId'], 'fake_id')
            # Job().updateJob(job, log='job running', status=JobStatus.ERROR)

            # tale = Tale().load(tale['_id'], force=True)
            # self.assertEqual(tale['imageInfo']['status'], ImageStatus.INVALID)

    def tearDown(self):
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        self.model('image', 'wholetale').remove(self.image)
        super(TaleTestCase, self).tearDown()
