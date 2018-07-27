import httmock
import mock
import json
from tests import base
from .tests_helpers import \
    GOOD_REPO, GOOD_COMMIT, GOOD_CHILD, XPRA_REPO, XPRA_COMMIT, \
    mockOtherRequest, mockCommitRequest, mockReposRequest


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
        return {'Id': 'image_hash'}


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
        with httmock.HTTMock(mockReposRequest, mockCommitRequest,
                             mockOtherRequest):
            self.recipe = self.model('recipe', 'wholetale').createRecipe(
                GOOD_COMMIT, 'https://github.com/' + GOOD_REPO,
                creator=self.user, public=True)
            self.new_recipe = self.model('recipe', 'wholetale').createRecipe(
                GOOD_CHILD, 'https://github.com/' + GOOD_REPO,
                parent=self.recipe, creator=self.user, public=True)
            self.admin_recipe = self.model('recipe', 'wholetale').createRecipe(
                XPRA_COMMIT, 'https://github.com/' + XPRA_REPO,
                creator=self.admin, public=True)

    def testImageFlow(self):
        from girder.plugins.wholetale.constants import ImageStatus
        from server.utils import create_repository_file
        # test search modes
        resp = self.request(
            path='/image', method='POST', user=self.user,
            params={
                'fullName': GOOD_REPO, 'recipeId': str(self.recipe['_id']),
                'public': True}
        )
        self.assertStatusOk(resp)
        image = resp.json
        self.assertEqual(image['status'], ImageStatus.UNAVAILABLE)

        with mock.patch('celery.Celery') as celeryMock:
            instance = celeryMock.return_value
            instance.send_task.return_value = FakeAsyncResult()
            instance.AsyncResult.return_value = FakeAsyncResult()

            resp = self.request(
                path='/image/{_id}/build'.format(**image), method='PUT',
                user=self.admin)
            self.assertStatusOk(resp)
            self.assertEqual(len(celeryMock.mock_calls), 2)
            self.assertEqual(celeryMock.mock_calls[0][1], ('girder_worker',))

            sendTaskCalls = celeryMock.return_value.send_task.mock_calls
            mock_repo_url = 'https://github.com/{}/archive/{}.tar.gz'.format(GOOD_REPO, GOOD_COMMIT)
            self.assertEqual(len(sendTaskCalls), 1)
            file_id = create_repository_file(str(self.recipe['_id']))
            self.assertEqual(sendTaskCalls[0][1], (
                'gwvolman.tasks.build_image',
                (image['_id'], image['fullName'], mock_repo_url), {'file_id': file_id}))

            job = resp.json
            imageId = job['args'][0]

            # Failed build
            resp = self.request(
                path='/image/{}'.format(imageId), method='GET',
                user=self.admin)
            self.assertStatusOk(resp)
            self.assertEqual(resp.json['_id'], imageId)
            self.assertEqual(resp.json['status'], ImageStatus.BUILDING)

            resp = self.request(
                path='/job/{_id}'.format(**job), method='PUT',
                params={'status': JobStatus.RUNNING}, user=self.admin)
            self.assertStatusOk(resp)
            resp = self.request(
                path='/job/{_id}'.format(**job), method='PUT',
                params={'status': JobStatus.ERROR}, user=self.admin)
            self.assertStatusOk(resp)

            resp = self.request(
                path='/image/{}'.format(imageId), method='GET',
                user=self.admin)
            self.assertStatusOk(resp)
            self.assertEqual(resp.json['status'], ImageStatus.INVALID)

            # Successful build
            resp = self.request(
                path='/image/{_id}/build'.format(**image), method='PUT',
                user=self.admin)
            self.assertStatusOk(resp)
            job = resp.json
            imageId = job['args'][0]
            resp = self.request(
                path='/job/{_id}'.format(**job), method='PUT',
                params={'status': JobStatus.QUEUED}, user=self.admin)
            self.assertStatusOk(resp)
            resp = self.request(
                path='/job/{_id}'.format(**job), method='PUT',
                params={'status': JobStatus.RUNNING}, user=self.admin)
            self.assertStatusOk(resp)
            resp = self.request(
                path='/job/{_id}'.format(**job), method='PUT',
                params={'status': JobStatus.SUCCESS}, user=self.admin)
            self.assertStatusOk(resp)

            resp = self.request(
                path='/image/{}'.format(imageId), method='GET',
                user=self.admin)
            self.assertStatusOk(resp)
            self.assertEqual(resp.json['status'], ImageStatus.AVAILABLE)
            self.assertEqual(resp.json['digest'], 'image_hash')

        resp = self.request(
            path='/image/{_id}'.format(**image), method='PUT',
            user=self.user, params={
                'name': 'new name',
                'description': 'new description',
                'tags': json.dumps(['latest', 'foo']),
                'icon': 'http://lorempixel.com/200/200/cats/'
            }
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['name'], 'new name')
        image = resp.json

        with mock.patch('celery.Celery') as celeryMock:
            instance = celeryMock.return_value
            instance.send_task.return_value = FakeAsyncResult()
            instance.AsyncResult.return_value = FakeAsyncResult()

            resp = self.request(
                path='/image/{_id}/copy'.format(**image), method='POST',
                user=self.user, params={'recipeId': str(self.new_recipe['_id'])})
            self.assertStatusOk(resp)
            new_image = resp.json
            self.assertEqual(new_image['parentId'], image['_id'])

        resp = self.request(
            path='/image',  method='GET', user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(set([_['_id'] for _ in resp.json]),
                         {new_image['_id'], image['_id']})

        resp = self.request(
            path='/image/{_id}'.format(**new_image), method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        for key in new_image.keys():
            if key in ('access', 'updated', 'created'):
                continue
            self.assertEqual(resp.json[key], new_image[key])

        resp = self.request(
            path='/image/{_id}'.format(**new_image), method='DELETE',
            user=self.admin)
        self.assertStatusOk(resp)

        resp = self.request(
            path='/image/{_id}'.format(**new_image), method='GET',
            user=self.user)
        self.assertStatus(resp, 400)

    def testImageAccess(self):
        with httmock.HTTMock(mockReposRequest, mockCommitRequest,
                             mockOtherRequest):
            from girder.plugins.wholetale.constants import ImageStatus
            # Create a new image from a user recipe
            resp = self.request(
                path='/image', method='POST', user=self.user,
                params={
                    'fullName': GOOD_REPO, 'recipeId': str(self.recipe['_id']),
                    'public': True}
            )
            self.assertStatusOk(resp)
            image_user_recipe = resp.json
            self.assertEqual(image_user_recipe['status'], ImageStatus.UNAVAILABLE)

            # Create a new image from an admin recipe
            resp = self.request(
                path='/image', method='POST', user=self.user,
                params={
                    'fullName': GOOD_REPO, 'recipeId': str(self.admin_recipe['_id']),
                    'public': True}
            )
            self.assertStatusOk(resp)
            image_admin_recipe = resp.json
            self.assertEqual(image_admin_recipe['status'], ImageStatus.UNAVAILABLE)

        from girder.constants import AccessType

        # Retrieve access control list for the newly created image
        resp = self.request(
            path='/image/%s/access' % image_user_recipe['_id'], method='GET',
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
        self.assertTrue(image_user_recipe.get('public'))

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
            path='/image/%s/access' % image_user_recipe['_id'], method='PUT',
            user=self.user, params={'access': json.dumps(input_access)})
        self.assertStatusOk(resp)
        # Check that the returned access control list for the image is as expected
        result_image_access = resp.json['access']
        result_recipe_id = resp.json['recipeId']
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

        # Check that the access control list propagated to the recipe that the image
        # was created from
        resp = self.request(
            path='/recipe/%s/access' % result_recipe_id, method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        result_recipe_access = resp.json
        expected_recipe_access = input_access
        self.assertEqual(result_recipe_access, expected_recipe_access)

        # Update the access control list of an image that was generated from a recipe that the user
        # does not have admin access to
        input_access = {
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
            path='/image/%s/access' % image_admin_recipe['_id'], method='PUT',
            user=self.user, params={'access': json.dumps(input_access)})
        self.assertStatus(resp, 403)

        # Check that the access control list was correctly set for the image
        resp = self.request(
            path='/image/%s/access' % image_admin_recipe['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        result_image_access = resp.json
        expected_image_access = input_access
        self.assertEqual(result_image_access, expected_image_access)

        # Check that the access control list did not propagate to the recipe
        resp = self.request(
            path='/recipe/%s/access' % image_admin_recipe['recipeId'], method='GET',
            user=self.user)
        self.assertStatus(resp, 403)

        # Setting the access list with bad json should throw an error
        resp = self.request(
            path='/image/%s/access' % image_user_recipe['_id'], method='PUT',
            user=self.user, params={'access': 'badJSON'})
        self.assertStatus(resp, 400)

        # Change the access to private
        resp = self.request(
            path='/image/%s/access' % image_user_recipe['_id'], method='PUT',
            user=self.user,
            params={'access': json.dumps(input_access), 'public': False})
        self.assertStatusOk(resp)
        resp = self.request(
            path='/image/%s' % image_user_recipe['_id'], method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['public'], False)

    def tearDown(self):
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        self.model('recipe', 'wholetale').remove(self.recipe)
        super(ImageTestCase, self).tearDown()
