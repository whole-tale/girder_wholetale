import mock
import httmock
import os
import json
from tests import base
from girder.models.item import Item
from girder.models.folder import Folder


SCRIPTDIRS_NAME = None
DATADIRS_NAME = None

def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.startServer()

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
            name="test my name", creator=self.user, public=True)

    def testTaleFlow(self):
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
                'public': True,
                'published': False,
                'doi': 'doi:10.x.x.xx',
                'publishedURI': 'publishedURI_URL'
            })
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['title'], 'new name')
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

        resp = self.request(
            path='/tale/{_id}/export'.format(**tale),
            method='GET',
            user=self.user,
            type='application/octet-stream',
            isJson=False)

        self.assertStatus(resp, 200)

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
            "published": False,
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
        # self.assertEqual(str(tale['dataSet'][0]['itemId']), data_dir['_id'])
        # self.assertEqual(tale['dataSet'][0]['mountPath'], '/' + data_dir['name'])
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
        published = True
        doi = 'doi:10.x.zz'
        published_uri = 'atestURI'

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
                'published': False,
                'doi': 'doi',
                'publishedURI': 'published_uri'
            })
        )

        self.assertStatus(resp, 200)

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
                'published': published,
                'doi': doi,
                'publishedURI': published_uri
            })
        )

        # Check that the updates happened
        # self.assertStatus(resp, 200)
        self.assertEqual(resp.json['imageId'], str(self.image['_id']))
        self.assertEqual(resp.json['title'], title)
        self.assertEqual(resp.json['description'], description)
        self.assertEqual(resp.json['config'], config)
        self.assertEqual(resp.json['public'], public)
        self.assertEqual(resp.json['published'], published)
        self.assertEqual(resp.json['doi'], doi)
        self.assertEqual(resp.json['publishedURI'], published_uri)

    def tearDown(self):
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        self.model('image', 'wholetale').remove(self.image)
        super(TaleTestCase, self).tearDown()
