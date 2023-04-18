import httmock
import time
import pytest
import json
import mock
import six
import urllib.parse
from bson import ObjectId
from datetime import datetime
from tests import base
from girder.exceptions import ValidationException
from girder.utility import config

from .tests_helpers import get_events, mockOtherRequest


JobStatus = None
ImageStatus = None
Instance = None
InstanceStatus = None
Tale = None


def setUpModule():
    cfg = config.getConfig()
    cfg['server']['heartbeat'] = 10
    base.enabledPlugins.append('wholetale')
    base.startServer()
    global JobStatus, CustomJobStatus, Instance, \
        InstanceStatus, Tale, ImageStatus
    from girder.plugins.jobs.constants import JobStatus
    from girder.plugins.wholetale.models.instance import Instance
    from girder.plugins.wholetale.models.tale import Tale
    from girder.plugins.wholetale.constants import InstanceStatus, ImageStatus


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
            name='tmp-xxx',
            mountPoint='/foo/bar',
            volumeName='blah_volume',
            sessionId='5ecece693fec11b4854a874d',
            instanceId=self.instanceId
        )


class FakeAsyncResultForUpdate(object):

    def __init__(self, instanceId=None):
        self.task_id = 'fake_update_id'
        self.instanceId = instanceId
        self.digest = 'sha256:7a789bc20359dce987653'

    def get(self, timeout=None):
        return dict(digest=self.digest)


class InstanceTestCase(base.TestCase):

    def setUp(self):
        super(InstanceTestCase, self).setUp()
        global PluginSettings, instanceCapErrMsg
        from girder.plugins.wholetale.constants import PluginSettings
        from girder.plugins.wholetale.rest.instance import instanceCapErrMsg
        from girder.plugins.wholetale.utils import init_progress
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
            name="image my name", creator=self.user, idleTimeout=.25, public=True)

        self.userPrivateFolder = self.model('folder').createFolder(
            self.user, 'PrivateFolder', parentType='user', public=False,
            creator=self.user)
        self.userPublicFolder = self.model('folder').createFolder(
            self.user, 'PublicFolder', parentType='user', public=True,
            creator=self.user)

        data = []
        self.tale_one = self.model('tale', 'wholetale').createTale(
            self.image, data, creator=self.user,
            title='tale one', public=True, config={'memLimit': '2g'})

        fake_imageInfo = {
            "digest": (
                "registry.local.wholetale.org/5c8fe826da39aa00013e9609/1552934951@"
                "sha256:4f604e6fab47f79e28251657347ca20ee89b737b4b1048c18ea5cf2fe9a9f098"
            ),
            "jobId": ObjectId("5c9009deda39aa0001d702b7"),
            "last_build": 1552943449,
            "repo2docker_version": "craigwillis/repo2docker:latest",
            "status": 3
        }
        self.tale_one["imageInfo"] = fake_imageInfo
        self.model('tale', 'wholetale').save(self.tale_one)

        data = []
        self.tale_two = self.model('tale', 'wholetale').createTale(
            self.image, data, creator=self.user,
            title='tale two', public=True, config={'memLimit': '1g'})
        self.tale_two["imageInfo"] = fake_imageInfo
        self.model('tale', 'wholetale').save(self.tale_two)
        self.notification = init_progress({}, self.user, "Fake", ".", 5)

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
        since = datetime.utcnow().isoformat()
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
            for _ in range(20):
                job = jobModel.load(job['_id'], force=True)
                if job['status'] == JobStatus.QUEUED:
                    break
                time.sleep(0.1)
            self.assertEqual(job['status'], JobStatus.QUEUED)
            events = get_events(self, since)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['data']['event'], 'wt_instance_launching')

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
            since = datetime.utcnow().isoformat()
            Job().updateJob(job, log='job ran', status=JobStatus.SUCCESS)

            resp = self.request(
                path='/job/{_id}/result'.format(**job), method='GET', user=self.user
            )
            self.assertStatusOk(resp)
            self.assertEqual(resp.json['nodeId'], '123456')

            # Confirm event
            events = get_events(self, since)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['data']['event'], 'wt_instance_running')

        # Check if set up properly
        resp = self.request(
            path='/instance/{_id}'.format(**instance), method='GET', user=self.user
        )
        self.assertEqual(resp.json['containerInfo']['imageId'], str(self.image['_id']))
        self.assertEqual(resp.json['containerInfo']['digest'], self.tale_one['imageInfo']['digest'])
        self.assertEqual(resp.json['containerInfo']['nodeId'], '123456')
        self.assertEqual(resp.json['containerInfo']['volumeName'], 'blah_volume')
        self.assertEqual(resp.json['status'], InstanceStatus.RUNNING)

        # Save this response to populate containerInfo
        instance = resp.json

        # Check that the instance is a singleton
        resp = self.request(
            path='/instance', method='POST', user=self.user,
            params={'taleId': str(self.tale_one['_id']),
                    'name': 'tale one'},

        )
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['_id'], str(instance['_id']))

        # Instance authorization checks
        # Missing forward auth headers
        resp = self.request(
            path="/user/authorize",
            params={"instance": True},
            method="GET",
            isJson=False,
            user=self.user,
        )
        # Assert 400 "Forward auth request required"
        self.assertStatus(resp, 400)

        # Valid user, invalid host
        resp = self.request(
            user=self.user,
            path="/user/authorize",
            params={"instance": True},
            method="GET",
            additionalHeaders=[("X-Forwarded-Host", "blah.wholetale.org"),
                               ("X-Forwarded_Uri", "/")],
            isJson=False,
        )
        # 403 "Access denied for instance"
        self.assertStatus(resp, 403)

        # Valid user, valid host
        resp = self.request(
            user=self.user,
            path="/user/authorize",
            params={"instance": True},
            method="GET",
            additionalHeaders=[("X-Forwarded-Host", "tmp-xxx.wholetale.org"),
                               ("X-Forwarded_Uri", "/")],
            isJson=False,
        )
        self.assertStatus(resp, 200)

        # No user
        resp = self.request(
            path="/user/authorize",
            params={"instance": True},
            method="GET",
            additionalHeaders=[("X-Forwarded-Host", "tmp-xxx.wholetale.org"),
                               ("X-Forwarded-Uri", "/")],
            isJson=False,
        )
        self.assertStatus(resp, 303)
        # Confirm redirect to https://girder.{domain}/api/v1/user/sign_in
        self.assertEqual(resp.headers["Location"],
                         "https://girder.wholetale.org/api/v1/"
                         "user/sign_in?redirect=https://tmp-xxx.wholetale.org/")

        # Update/restart the instance
        job = jobModel.createJob(
            title='Update Instance', type='celery', handler='worker_handler',
            user=self.user, public=False, args=[instance['_id']], kwargs={})
        job = jobModel.save(job)
        self.assertEqual(job['status'], JobStatus.INACTIVE)
        with mock.patch('celery.Celery') as celeryMock, mock.patch(
            'girder_worker.task.celery.Task.apply_async', spec=True
        ) as mock_apply_async, mock.patch(
            'girder.plugins.worker.getCeleryApp'
        ) as gca:
            gca().send_task.return_value = FakeAsyncResultForUpdate(instance['_id'])
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
                    }
                })
            )
            self.assertStatusOk(resp)
            mock_apply_async.assert_called_once()

            jobModel.scheduleJob(job)
            for _ in range(20):
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
            self.assertEqual(job['celeryTaskId'], 'fake_update_id')
            Job().updateJob(job, log='job running', status=JobStatus.RUNNING)

            Job().updateJob(job, log='job running', status=JobStatus.RUNNING)
            Job().updateJob(job, log='job ran', status=JobStatus.SUCCESS)

        resp = self.request(
            path='/instance/{_id}'.format(**instance), method='GET',
            user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['containerInfo']['digest'], 'sha256:7a789bc20359dce987653')
        instance = resp.json

        # Update/restart the instance and fail
        job = jobModel.createJob(
            title='Update Instance', type='celery', handler='worker_handler',
            user=self.user, public=False, args=[instance['_id']], kwargs={})
        job = jobModel.save(job)
        self.assertEqual(job['status'], JobStatus.INACTIVE)
        with mock.patch('celery.Celery') as celeryMock, mock.patch(
            'girder_worker.task.celery.Task.apply_async', spec=True
        ) as mock_apply_async, mock.patch(
            'girder.plugins.worker.getCeleryApp'
        ) as gca:
            gca().send_task.return_value = FakeAsyncResultForUpdate(instance['_id'])
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
                    }
                })
            )
            self.assertStatusOk(resp)
            mock_apply_async.assert_called_once()

            jobModel.scheduleJob(job)
            for _ in range(20):
                job = jobModel.load(job['_id'], force=True)
                if job['status'] == JobStatus.QUEUED:
                    break
                time.sleep(0.1)
            self.assertEqual(job['status'], JobStatus.QUEUED)

            instance = Instance().load(instance['_id'], force=True)
            self.assertEqual(instance['status'], InstanceStatus.LAUNCHING)

            Job().updateJob(job, log='job failed', status=JobStatus.ERROR)
            instance = Instance().load(instance['_id'], force=True)
            self.assertEqual(instance['status'], InstanceStatus.ERROR)

        # Delete the instance
        since = datetime.utcnow().isoformat()
        with mock.patch('girder_worker.task.celery.Task.apply_async', spec=True) \
                as mock_apply_async:
            resp = self.request(
                path='/instance/{_id}'.format(**instance), method='DELETE',
                user=self.user)
            self.assertStatusOk(resp)
            self.assertEqual(mock_apply_async.call_count, 2)

        resp = self.request(
            path='/instance/{_id}'.format(**instance), method='GET',
            user=self.user)
        self.assertStatus(resp, 400)

        # Confirm notifications
        events = get_events(self, since)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]['data']['event'], 'wt_instance_deleting')
        self.assertEqual(events[1]['data']['event'], 'wt_instance_deleted')

    def testBuildFail(self):
        from girder.plugins.jobs.models.job import Job
        resp = self.request(
            path='/instance', method='POST', user=self.user,
            params={'taleId': str(self.tale_one['_id']),
                    'name': 'tale that will fail', 'spawn': False}
        )
        self.assertStatusOk(resp)
        instance = resp.json
        self.assertNotEqual(instance['status'], InstanceStatus.ERROR)

        job = Job().createJob(
            title='Fake build job',
            type='celery',
            handler='worker_handler',
            user=self.user,
            public=False,
            args=[str(self.tale_one['_id']), False],
            kwargs={},
            otherFields={
                'wt_notification_id': str(self.notification["_id"]),
                'instance_id': instance['_id']
            }
        )
        job = Job().save(job)
        self.assertEqual(job['status'], JobStatus.INACTIVE)
        Job().updateJob(job, log='job queued', status=JobStatus.QUEUED)
        Job().updateJob(job, log='job running', status=JobStatus.RUNNING)
        Job().updateJob(job, log='job failed', status=JobStatus.ERROR)
        instance = Instance().load(instance['_id'], force=True)
        self.assertEqual(instance['status'], InstanceStatus.ERROR)
        Instance().remove(instance)

    def testBuildCancel(self):
        from girder.plugins.jobs.models.job import Job
        from girder.plugins.worker import CustomJobStatus
        resp = self.request(
            path='/instance', method='POST', user=self.user,
            params={'taleId': str(self.tale_one['_id']),
                    'name': 'tale that will fail', 'spawn': False}
        )
        self.assertStatusOk(resp)
        instance = resp.json
        self.assertNotEqual(instance['status'], InstanceStatus.ERROR)

        job = Job().createJob(
            title='Build Tale Image',
            type='celery',
            handler='worker_handler',
            user=self.user,
            public=False,
            args=[str(self.tale_one['_id']), False],
            kwargs={},
            otherFields={
                'wt_notification_id': str(self.notification["_id"]),
                'instance_id': instance['_id']
            }
        )
        job = Job().save(job)
        self.assertEqual(job['status'], JobStatus.INACTIVE)
        Job().updateJob(job, log='job queued', status=JobStatus.QUEUED)
        Job().updateJob(job, log='job running', status=JobStatus.RUNNING)

        with mock.patch(
            "girder.plugins.wholetale.models.instance.Instance.deleteInstance"
        ) as mock_delete:
            Job().updateJob(job, log='job canceling', status=CustomJobStatus.CANCELING)
            tale = Tale().load(self.tale_one["_id"], force=True)
            while tale["imageInfo"]["status"] != ImageStatus.UNAVAILABLE:
                time.sleep(1)
                tale = Tale().load(self.tale_one["_id"], force=True)
        mock_delete.assert_called_once()

        with mock.patch(
            "girder.plugins.wholetale.models.instance.Instance.deleteInstance"
        ) as mock_delete:
            Job().updateJob(job, log='job canceling', status=JobStatus.CANCELED)

        instance = Instance().load(instance['_id'], force=True)
        Instance().remove(instance)

    def testLaunchFail(self):
        from girder.plugins.jobs.models.job import Job
        resp = self.request(
            path='/instance', method='POST', user=self.user,
            params={'taleId': str(self.tale_one['_id']),
                    'name': 'tale that will fail', 'spawn': False}
        )
        self.assertStatusOk(resp)
        instance = resp.json

        job = Job().createJob(
            title='Spawn Instance',
            type='celery',
            handler='worker_handler',
            user=self.user,
            public=False,
            args=[{'instanceId': instance['_id']}],
            kwargs={},
            otherFields={
                'wt_notification_id': str(self.notification["_id"]),
                'instance_id': instance['_id']
            }
        )

        job = Job().save(job)
        self.assertEqual(job['status'], JobStatus.INACTIVE)
        Job().updateJob(job, log='job queued', status=JobStatus.QUEUED)
        Job().updateJob(job, log='job running', status=JobStatus.RUNNING)
        since = datetime.utcnow().isoformat()
        Job().updateJob(job, log='job failed', status=JobStatus.ERROR)
        instance = Instance().load(instance['_id'], force=True)
        self.assertEqual(instance['status'], InstanceStatus.ERROR)
        events = get_events(self, since)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['data']['event'], 'wt_instance_error')

    def testIdleInstance(self):
        instance = self.model('instance', 'wholetale').createInstance(
            self.tale_one, self.user, name="idle instance", spawn=False)

        instance['containerInfo'] = {
            'imageId': self.image['_id'],
        }
        self.model('instance', 'wholetale').updateInstance(instance)

        cfg = config.getConfig()
        self.assertEqual(cfg['server']['heartbeat'], 10)

        # Wait for idle instance to be culled
        with mock.patch(
                "girder.plugins.wholetale.models.instance.Instance.deleteInstance"
                ) as mock_delete:
            time.sleep(25)
        mock_delete.assert_called_once()

        self.model('instance', 'wholetale').remove(instance)

    def testInstanceLogs(self):
        instance = self.model('instance', 'wholetale').createInstance(
            self.tale_one, self.user, name="instance", spawn=False
        )
        instance['containerInfo'] = {
            'imageId': self.image['_id'],
        }
        self.model('instance', 'wholetale').updateInstance(instance)

        @httmock.urlmatch(
            scheme="http",
            netloc="logger:8000",
            path="^/$",
        )
        def logger_call(url, request):
            params = urllib.parse.parse_qs(url.query)
            if "name" not in params:
                return httmock.response(
                    status_code=400,
                    content={"detail": "Missing 'name' parameter"}
                )
            name = params["name"][0]
            assert name == "some_service"
            return httmock.response(
                status_code=200,
                content="blah",
                headers={"content-type": "text/plain; charset=utf-8"},
            )

        with httmock.HTTMock(logger_call, mockOtherRequest):
            resp = self.request(
                user=self.user,
                path=f"/instance/{instance['_id']}/log",
                method="GET",
                isJson=False,
            )
            self.assertEqual(
                self.getBody(resp),
                f"Logs for instance {instance['_id']} are currently unavailable..."
            )
            instance["containerInfo"]["name"] = "some_service"
            self.model('instance', 'wholetale').updateInstance(instance)

            resp = self.request(
                user=self.user,
                path=f"/instance/{instance['_id']}/log",
                method="GET",
                isJson=False,
            )
            self.assertEqual(self.getBody(resp), "blah")

        self.model('instance', 'wholetale').remove(instance)

    def testLoggerSetting(self):
        from girder.plugins.wholetale.constants import PluginSettings, SettingDefault
        with pytest.raises(ValidationException) as exc:
            self.model('setting').set(PluginSettings.LOGGER_URL, 'a')
        self.assertTrue(str(exc.value) == "Invalid Instance Logger URL")

        self.assertEqual(
            self.model('setting').get(PluginSettings.LOGGER_URL),
            SettingDefault.defaults[PluginSettings.LOGGER_URL]
        )

    def tearDown(self):
        self.model('folder').remove(self.userPrivateFolder)
        self.model('folder').remove(self.userPublicFolder)
        self.model('image', 'wholetale').remove(self.image)
        self.model('tale', 'wholetale').remove(self.tale_one)
        self.model('tale', 'wholetale').remove(self.tale_two)
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        super(InstanceTestCase, self).tearDown()
