import json
from tests import base


JobStatus = None
worker = None
CustomJobStatus = None


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.startServer()

    global JobStatus, worker, CustomJobStatus
    from girder.plugins.jobs.constants import JobStatus
    from girder.plugins import worker
    from girder.plugins.worker import CustomJobStatus


def tearDownModule():
    base.stopServer()


class FakeAsyncResult(object):
    def __init__(self):
        self.task_id = 'fake_id'

    def get(self):
        return {'image_digest': 'registry/image_name@image_hash'}


class ImageTestCase(base.TestCase):

    def setUp(self):
        super(ImageTestCase, self).setUp()
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

    def testImageAccess(self):

        # Create a new user image
        resp = self.request(
            path='/image', method='POST', user=self.user,
            params={
                'name': 'test user image', 'public': True
            }
        )
        self.assertStatusOk(resp)
        image_user = resp.json

        # Create a new admin image
        resp = self.request(
            path='/image', method='POST', user=self.admin,
            params={
                'name': 'test admin image', 'public': True
            }
        )
        self.assertStatusOk(resp)
        image_admin = resp.json

        from girder.constants import AccessType

        # Retrieve access control list for the newly created image
        resp = self.request(
            path='/image/%s/access' % image_user['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        access = resp.json
        self.assertEqual(access, {
            'users': [{
                'login': self.user['login'],
                'level': AccessType.ADMIN,
                'id': str(self.user['_id']),
                'flags': [],
                'name': '%s %s' % (
                    self.user['firstName'], self.user['lastName'])}],
            'groups': []
        })
        self.assertTrue(image_user.get('public'))

        # Update the access control list for the image by adding the admin
        # as a second user
        input_access = {
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
            path='/image/%s/access' % image_user['_id'], method='PUT',
            user=self.user, params={'access': json.dumps(input_access)})
        self.assertStatusOk(resp)
        # Check that the returned access control list for the image is as expected
        result_image_access = resp.json['access']
        expected_image_access = {
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
        self.assertEqual(result_image_access, expected_image_access)

        # Update the access control list of the admin image
        resp = self.request(
            path='/image/%s/access' % image_admin['_id'], method='PUT',
            user=self.user, params={'access': json.dumps(input_access)})
        self.assertStatus(resp, 403)

        # Check that the access control list was correctly set for the image
        resp = self.request(
            path='/image/%s/access' % image_admin['_id'], method='GET',
            user=self.admin)
        self.assertStatusOk(resp)
        access = resp.json
        self.assertEqual(access, {
            'users': [{
                'login': self.admin['login'],
                'level': AccessType.ADMIN,
                'id': str(self.admin['_id']),
                'flags': [],
                'name': '%s %s' % (
                    self.admin['firstName'], self.admin['lastName'])}],
            'groups': []
        })

        # Setting the access list with bad json should throw an error
        resp = self.request(
            path='/image/%s/access' % image_user['_id'], method='PUT',
            user=self.user, params={'access': 'badJSON'})
        self.assertStatus(resp, 400)

        # Change the access to private
        resp = self.request(
            path='/image/%s/access' % image_user['_id'], method='PUT',
            user=self.user,
            params={'access': json.dumps(input_access), 'public': False})
        self.assertStatusOk(resp)
        resp = self.request(
            path='/image/%s' % image_user['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['public'], False)

    def testImageSearch(self):
        from girder.plugins.wholetale.models.image import Image
        images = []
        images.append(
            Image().createImage(
                name='Jupyter One',
                tags=['black'], creator=self.user, description='Blah', public=False)
        )
        images.append(
            Image().createImage(
                name='Jupyter Two',
                tags=['orange'], creator=self.user, description='Blah', public=False,
                parent=images[0])
        )
        images.append(
            Image().createImage(
                name='Fortran',
                tags=['black'], creator=self.user, description='Blah', public=True)
        )

        resp = self.request(
            path='/image', method='GET', user=self.user,
            params={'text': 'Jupyter'})
        self.assertStatusOk(resp)
        self.assertEqual(
            {_['name'] for _ in resp.json}, {'Jupyter One', 'Jupyter Two'}
        )

        resp = self.request(
            path='/image', method='GET', user=self.user,
            params={'tag': 'black'})
        self.assertStatusOk(resp)
        self.assertEqual(
            {_['name'] for _ in resp.json}, {'Jupyter One', 'Fortran'}
        )

        resp = self.request(
            path='/image', method='GET', user=self.user,
            params={'tag': 'black', 'text': 'Fortran'})
        self.assertStatusOk(resp)
        self.assertEqual(
            {_['name'] for _ in resp.json}, {'Fortran'}
        )

        resp = self.request(
            path='/image', method='GET', user=self.user,
            params={'parentId': str(images[0]['_id'])})
        self.assertStatusOk(resp)
        self.assertEqual(
            {_['name'] for _ in resp.json}, {'Jupyter Two'}
        )

        for image in images:
            Image().remove(image)

    def testCreateUpdateImage(self):
        from girder.plugins.wholetale.models.image import Image

        # Create the image
        params = {
            'name': 'test user image',
            'iframe': True,
            'public': True,
            'description': 'description',
            'icon': 'icon',
            'idleTimeout': 1
        }

        resp = self.request(
            path='/image', method='POST', user=self.user, params=params
        )
        self.assertStatusOk(resp)
        image = resp.json

        for param in params:
            self.assertEqual(params[param], image[param])

        # Update the image
        new_params = {
            'name': 'new test user image',
            'iframe': False,
            'public': False,
            'description': 'new description',
            'icon': 'new icon',
            'idleTimeout': 2
        }

        resp = self.request(
            path='/image/{}'.format(str(image['_id'])),
            method='PUT',
            user=self.user,
            params=new_params
        )
        self.assertStatusOk(resp)
        new_image = resp.json

        print(new_image)

        for param in new_params:
            self.assertEqual(new_params[param], new_image[param])

        Image().remove(image)

    def tearDown(self):
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        super(ImageTestCase, self).tearDown()
