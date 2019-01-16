import time
import json
import copy
import mock
import six
from tests import base
from girder.exceptions import ValidationException


JobStatus = None
Instance = None
InstanceStatus = None


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.startServer()
    global JobStatus, CustomJobStatus, Instance, \
        InstanceStatus
    from girder.plugins.jobs.constants import JobStatus
    from girder.plugins.wholetale.models.instance import Instance
    from girder.plugins.wholetale.constants import InstanceStatus


def tearDownModule():
    base.stopServer()


class FakeAsyncResult(object):
    def __init__(self, instanceId=None):
        self.task_id = 'fake_id'
        self.instanceId = instanceId

    def get(self, timeout=None):
        return dict(
            digest='sha256:7a789bc20359dce987653',
            imageId='5678901234567890',
            nodeId='123456',
            mountPoint='/foo/bar',
            volumeName='blah_volume',
            sessionId='sessionId',
            instanceId=self.instanceId
        )


class InstanceTestCase(base.TestCase):

    def setUp(self):
        super(InstanceTestCase, self).setUp()
        global PluginSettings, instanceCapErrMsg
        from girder.plugins.wholetale.constants import PluginSettings
        from girder.plugins.wholetale.rest.instance import instanceCapErrMsg
        self.model('setting').set(
            PluginSettings.INSTANCE_CAP, '2')
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

        self.image = self.model('image', 'wholetale').createImage(
            name="image my name", creator=self.user,
            public=True)

        self.userPrivateFolder = self.model('folder').createFolder(
            self.user, 'PrivateFolder', parentType='user', public=False,
            creator=self.user)
        self.userPublicFolder = self.model('folder').createFolder(
            self.user, 'PublicFolder', parentType='user', public=True,
            creator=self.user)

        data = [{'type': 'folder', 'id': self.userPrivateFolder['_id']}]
        self.tale_one = self.model('tale', 'wholetale').createTale(
            self.image, data, creator=self.user,
            title='tale one', public=True, config={'memLimit': '2g'})
        data = [{'type': 'folder', 'id': self.userPublicFolder['_id']}]
        self.tale_two = self.model('tale', 'wholetale').createTale(
            self.image, data, creator=self.user,
            title='tale two', public=True, config={'memLimit': '1g'})

    def testInstanceFromImage(self):
        return  # FIXME
        with mock.patch('celery.Celery') as celeryMock:
            with mock.patch('tornado.httpclient.HTTPClient') as tornadoMock:
                instance = celeryMock.return_value
                instance.send_task.return_value = FakeAsyncResult()

                req = tornadoMock.return_value
                req.fetch.return_value = {}

                resp = self.request(
                    path='/instance', method='POST', user=self.user,
                    params={})
                self.assertStatus(resp, 400)
                self.assertEqual(resp.json['message'],
                                 'You need to provide "imageId" or "taleId".')
                resp = self.request(
                    path='/instance', method='POST', user=self.user,
                    params={'imageId': str(self.image['_id'])})

                self.assertStatusOk(resp)
                self.assertEqual(
                    resp.json['url'], 'https://tmp-blah.0.0.1/?token=foo')
                self.assertEqual(
                    resp.json['name'], 'Testing %s' % self.image['fullName'])
                instanceId = resp.json['_id']

                resp = self.request(
                    path='/instance', method='POST', user=self.user,
                    params={'imageId': str(self.image['_id'])})
                self.assertStatusOk(resp)
                self.assertEqual(resp.json['_id'], instanceId)

            resp = self.request(
                path='/instance/{}'.format(instanceId), method='DELETE',
                user=self.user)
            self.assertStatusOk(resp)

    def testInstanceCap(self):
        from girder.plugins.wholetale.constants import PluginSettings, SettingDefault
        with six.assertRaisesRegex(self, ValidationException,
                                   '^Instance Cap needs to be an integer.$'):
            self.model('setting').set(PluginSettings.INSTANCE_CAP, 'a')

        setting = self.model('setting')

        resp = self.request(
            '/system/setting', user=self.admin, method='PUT',
            params={'key': PluginSettings.INSTANCE_CAP,
                    'value': ''})
        self.assertStatusOk(resp)
        resp = self.request(
            '/system/setting', user=self.admin, method='GET',
            params={'key': PluginSettings.INSTANCE_CAP})
        self.assertStatusOk(resp)
        self.assertEqual(
            resp.body[0].decode(),
            str(SettingDefault.defaults[PluginSettings.INSTANCE_CAP]))

        with mock.patch('celery.Celery') as celeryMock:
            instance = celeryMock.return_value
            instance.send_task.return_value = FakeAsyncResult()

            current_cap = setting.get(PluginSettings.INSTANCE_CAP)
            setting.set(PluginSettings.INSTANCE_CAP, '0')
            resp = self.request(
                path='/instance', method='POST', user=self.user,
                params={'taleId': str(self.tale_one['_id'])})
            self.assertStatus(resp, 400)
            self.assertEqual(
                resp.json['message'], instanceCapErrMsg.format('0'))
            setting.set(PluginSettings.INSTANCE_CAP, current_cap)
        
    @mock.patch('gwvolman.tasks.create_volume')
    @mock.patch('gwvolman.tasks.launch_container')
    @mock.patch('gwvolman.tasks.update_container')
    @mock.patch('gwvolman.tasks.shutdown_container')
    @mock.patch('gwvolman.tasks.remove_volume')
    def testInstanceFlow(self, lc, cv, uc, sc, rv):
        with mock.patch('girder_worker.task.celery.Task.apply_async', spec=True) \
                as mock_apply_async:
            resp = self.request(
                path='/instance', method='POST', user=self.user,
                params={'taleId': str(self.tale_one['_id']),
                        'name': 'tale one'}
            )
            mock_apply_async.assert_called_once()

        self.assertStatusOk(resp)
        instance = resp.json

        # Create a job to be handled by the worker plugin
        from girder.plugins.jobs.models.job import Job
        jobModel = Job()
        job = jobModel.createJob(
            title='Spawn Instance', type='celery', handler='worker_handler',
            user=self.user, public=False, args=[{'instanceId': instance['_id']}], kwargs={})
        job = jobModel.save(job)
        self.assertEqual(job['status'], JobStatus.INACTIVE)

        # Schedule the job, make sure it is sent to celery
        with mock.patch('celery.Celery') as celeryMock, \
                mock.patch('girder.plugins.worker.getCeleryApp') as gca:

            celeryMock().AsyncResult.return_value = FakeAsyncResult(instance['_id'])
            gca().send_task.return_value = FakeAsyncResult(instance['_id'])

            jobModel.scheduleJob(job)
            for i in range(20):
                job = jobModel.load(job['_id'], force=True)
                if job['status'] == JobStatus.QUEUED:
                    break
                time.sleep(0.1)
            self.assertEqual(job['status'], JobStatus.QUEUED)

            instance = Instance().load(instance['_id'], force=True)
            self.assertEqual(instance['status'], InstanceStatus.LAUNCHING)

            # Make sure we sent the job to celery
            sendTaskCalls = gca.return_value.send_task.mock_calls

            self.assertEqual(len(sendTaskCalls), 1)
            self.assertEqual(sendTaskCalls[0][1], (
                'girder_worker.run', job['args'], job['kwargs']))

            self.assertTrue('headers' in sendTaskCalls[0][2])
            self.assertTrue('jobInfoSpec' in sendTaskCalls[0][2]['headers'])

            # Make sure we got and saved the celery task id
            job = jobModel.load(job['_id'], force=True)
            self.assertEqual(job['celeryTaskId'], 'fake_id')
            Job().updateJob(job, log='job running', status=JobStatus.RUNNING)
            Job().updateJob(job, log='job ran', status=JobStatus.SUCCESS)

            resp = self.request(
                path='/job/{_id}/result'.format(**job), method='GET', user=self.user
            )
            self.assertStatusOk(resp)
            self.assertEqual(resp.json['nodeId'], '123456')

        # Check if set up properly
        resp = self.request(
            path='/instance/{_id}'.format(**instance), method='GET', user=self.user
        )
        self.assertEqual(resp.json['containerInfo']['imageId'], str(self.image['_id']))
        self.assertEqual(resp.json['containerInfo']['digest'], self.image['digest'])
        self.assertEqual(resp.json['containerInfo']['nodeId'], '123456')
        self.assertEqual(resp.json['containerInfo']['volumeName'], 'blah_volume')
        self.assertEqual(resp.json['status'], InstanceStatus.RUNNING)
        
        # Save this response to populate containerInfo
        instance = resp.json

        # Check that the instance is a singleton
        resp = self.request(
            path='/instance', method='POST', user=self.user,
            params={'taleId': str(self.tale_one['_id']),
                    'name': 'tale one'}
        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['_id'], str(instance['_id']))

        # Update/restart the instance
        with mock.patch('girder_worker.task.celery.Task.apply_async', spec=True) \
                as mock_apply_async:
                    
            # PUT /instance/:id (currently a no-op)
            resp = self.request(
                path='/instance/{_id}'.format(**instance), method='PUT', user=self.user,
                body=json.dumps({
                    # ObjectId is not serializable
                    '_id': str(instance['_id']),
                    'iframe': instance['iframe'],
                    'name': instance['name'],
                    'status': instance['status'],
                    'taleId': instance['status'],
                    'sessionId': instance['status'],
                    'url': instance['url'],
                    'containerInfo': {
                       'digest': instance['containerInfo']['digest'],
                       'imageId': instance['containerInfo']['imageId'],
                       'mountPoint': instance['containerInfo']['mountPoint'],
                       'name': instance['containerInfo']['name'],
                       'nodeId': instance['containerInfo']['nodeId'],
                       'urlPath': instance['containerInfo']['urlPath'],
                    }
                })
            )
            self.assertStatusOk(resp)
            mock_apply_async.assert_called_once()

        resp = self.request(
            path='/instance/{_id}'.format(**instance), method='GET',
            user=self.user)
        self.assertStatus(resp, 200)

        # Delete the instance
        with mock.patch('girder_worker.task.celery.Task.apply_async', spec=True) \
                as mock_apply_async:
            resp = self.request(
                path='/instance/{_id}'.format(**instance), method='DELETE',
                user=self.user)
            self.assertStatusOk(resp)
            mock_apply_async.assert_called_once()

        resp = self.request(
            path='/instance/{_id}'.format(**instance), method='GET',
            user=self.user)
        self.assertStatus(resp, 400)

    def tearDown(self):
        self.model('folder').remove(self.userPrivateFolder)
        self.model('folder').remove(self.userPublicFolder)
        self.model('image', 'wholetale').remove(self.image)
        self.model('tale', 'wholetale').remove(self.tale_one)
        self.model('tale', 'wholetale').remove(self.tale_two)
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        super(InstanceTestCase, self).tearDown()
