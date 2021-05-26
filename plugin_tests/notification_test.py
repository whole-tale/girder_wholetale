import time
from tests import base
from girder.models.setting import Setting


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.startServer()


def tearDownModule():
    base.stopServer()


class NotificationTestCase(base.TestCase):

    def setUp(self):
        super(NotificationTestCase, self).setUp()
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

        self.authors = [
            {
                'firstName': 'Charles',
                'lastName': 'Darwmin',
                'orcid': 'https://orcid.org/000-000'
            },
            {
                'firstName': 'Thomas',
                'lastName': 'Edison',
                'orcid': 'https://orcid.org/111-111'
            }
        ]
        self.admin, self.user = [self.model('user').createUser(**user)
                                 for user in users]

    def testSingleJobNotification(self):
        from girder.plugins.jobs.models.job import Job
        from girder.plugins.jobs.constants import JobStatus
        from girder.models.notification import Notification, ProgressState
        from girder.plugins.wholetale.utils import init_progress
        from girder.plugins.worker.constants import PluginSettings as WorkerPluginSettings

        # TODO: Why do we need it here?
        Setting().set(WorkerPluginSettings.API_URL, 'http://localhost:8080/api/v1')

        total = 2
        resource = {'type': 'wt_test_build_image', 'instance_id': 'instance_id'}

        notification = init_progress(
            resource, self.user, 'Test notification', 'Creating job', total
        )

        # Job to test error path
        job = Job().createJob(
            title='Error test job',
            type='test',
            handler='my_handler',
            user=self.user,
            public=False,
            args=["tale_id"],
            kwargs={},
            otherFields={'wt_notification_id': str(notification['_id'])},
        )
        job = Job().updateJob(
            job, status=JobStatus.INACTIVE, progressTotal=2, progressCurrent=0)
        self.assertEqual(job['status'], JobStatus.INACTIVE)
        notification = Notification().load(notification['_id'])
        self.assertEqual(notification['data']['state'], ProgressState.QUEUED)
        self.assertEqual(notification['data']['total'], 2)
        self.assertEqual(notification['data']['current'], 0)
        self.assertEqual(notification['data']['resource']['jobs'][0], job['_id'])

        # State change to ACTIVE
        job = Job().updateJob(job, status=JobStatus.RUNNING)
        self.assertEqual(job['status'], JobStatus.RUNNING)

        # Progress update
        job = Job().updateJob(
            job, status=JobStatus.RUNNING, progressCurrent=1,
            progressMessage="Error test message")
        notification = Notification().load(notification['_id'])
        self.assertEqual(notification['data']['state'], ProgressState.ACTIVE)
        self.assertEqual(notification['data']['total'], 2)
        self.assertEqual(notification['data']['current'], 1)
        self.assertEqual(notification['data']['message'], 'Error test message')

        # State change to ERROR
        job = Job().updateJob(job, status=JobStatus.ERROR)
        notification = Notification().load(notification['_id'])
        self.assertEqual(notification['data']['state'], ProgressState.ERROR)
        self.assertEqual(notification['data']['total'], 2)
        self.assertEqual(notification['data']['current'], 1)
        self.assertEqual(notification['data']['message'], 'Error test message')

        # new notification
        notification = init_progress(
            resource, self.user, 'Test notification', 'Creating job', total
        )

        # New job to test success path
        job = Job().createJob(
            title='Test Job',
            type='test',
            handler='my_handler',
            user=self.user,
            public=False,
            args=["tale_id"],
            kwargs={},
            otherFields={'wt_notification_id': str(notification['_id'])},
        )

        # State change to ACTIVE
        job = Job().updateJob(job, status=JobStatus.RUNNING)
        self.assertEqual(job['status'], JobStatus.RUNNING)

        # Progress update
        job = Job().updateJob(
            job, status=JobStatus.RUNNING, progressCurrent=1,
            progressMessage="Success test message")
        notification = Notification().load(notification['_id'])
        self.assertEqual(notification['data']['state'], ProgressState.ACTIVE)
        self.assertEqual(notification['data']['total'], 2)
        self.assertEqual(notification['data']['current'], 1)
        self.assertEqual(notification['data']['message'], 'Success test message')

        job = Job().updateJob(job, status=JobStatus.SUCCESS, progressCurrent=2)
        notification = Notification().load(notification['_id'])
        self.assertEqual(notification['data']['state'], ProgressState.SUCCESS)
        self.assertEqual(notification['data']['total'], 2)
        self.assertEqual(notification['data']['current'], 2)
        self.assertEqual(notification['data']['message'], 'Success test message')

    def assertNotification(self, notification_id, state, total, current, msg):
        from girder.models.notification import Notification
        notification = Notification().load(notification_id)
        self.assertEqual(notification['data']['state'], state)
        self.assertEqual(notification['data']['total'], total)
        self.assertEqual(notification['data']['current'], current)
        self.assertEqual(notification['data']['message'], msg)

    def testChainedJobNotification(self):
        from girder.plugins.jobs.models.job import Job
        from girder.plugins.jobs.constants import JobStatus
        from girder.models.notification import Notification, ProgressState
        from girder.plugins.wholetale.utils import init_progress
        from girder.plugins.worker.constants import PluginSettings as WorkerPluginSettings

        Setting().set(WorkerPluginSettings.API_URL, 'http://localhost:8080/api/v1')

        total = 5 # 2 + 2 + 1
        resource = {'type': 'wt_test_build_image', 'instance_id': 'instance_id'}

        notification = init_progress(
            resource, self.user, 'Test notification', 'Creating job', total
        )

        # First Job
        job = Job().createJob(
            title='First Job',
            type='test',
            handler='my_handler',
            user=self.user,
            public=False,
            args=["tale_id"],
            kwargs={},
            otherFields={'wt_notification_id': str(notification['_id'])},
        )
        # State change to ACTIVE
        msg = "Some message 1"
        job = Job().updateJob(
            job, status=JobStatus.RUNNING, progressCurrent=1, progressTotal=2,
            progressMessage=msg)
        self.assertEqual(job['status'], JobStatus.RUNNING)
        self.assertNotification(notification["_id"], ProgressState.ACTIVE, total, 1, msg)

        msg = "Success msg 1"
        job = Job().updateJob(
            job, status=JobStatus.SUCCESS, progressCurrent=2, progressTotal=2,
            progressMessage=msg)
        self.assertEqual(job['status'], JobStatus.SUCCESS)
        self.assertNotification(notification["_id"], ProgressState.ACTIVE, total, 2, msg)

        # Second Job
        job = Job().createJob(
            title='Second Job',
            type='test',
            handler='my_handler',
            user=self.user,
            public=False,
            args=["tale_id"],
            kwargs={},
            otherFields={'wt_notification_id': str(notification['_id'])},
        )
        # State change to QUEUE
        msg = "Some message 1"
        job = Job().updateJob(
            job, status=JobStatus.INACTIVE, progressTotal=2, progressCurrent=0,
            progressMessage=msg)
        self.assertEqual(job['status'], JobStatus.INACTIVE)
        self.assertNotification(notification["_id"], ProgressState.QUEUED, total, 2, msg)

        job = Job().updateJob(job, status=JobStatus.QUEUED)
        self.assertNotification(notification["_id"], ProgressState.QUEUED, total, 2, msg)

        job = Job().updateJob(job, status=JobStatus.RUNNING)
        self.assertNotification(notification["_id"], ProgressState.ACTIVE, total, 2, msg)

        msg = "Success msg 2"
        job = Job().updateJob(
            job, status=JobStatus.SUCCESS, progressCurrent=2, progressTotal=2,
            progressMessage=msg)
        self.assertEqual(job['status'], JobStatus.SUCCESS)
        self.assertNotification(notification["_id"], ProgressState.ACTIVE, total, 4, msg)

        # Final Job
        job = Job().createJob(
            title='Final Job',
            type='test',
            handler='my_handler',
            user=self.user,
            public=False,
            args=["tale_id"],
            kwargs={},
            otherFields={'wt_notification_id': str(notification['_id'])},
        )
        msg = "Some message 1"
        job = Job().updateJob(
            job, status=JobStatus.INACTIVE, progressTotal=1, progressCurrent=0,
            progressMessage=msg)
        self.assertEqual(job['status'], JobStatus.INACTIVE)
        self.assertNotification(notification["_id"], ProgressState.QUEUED, total, 4, msg)

        job = Job().updateJob(job, status=JobStatus.QUEUED)
        job = Job().updateJob(job, status=JobStatus.RUNNING)
        msg = "Success msg 3"
        job = Job().updateJob(
            job, status=JobStatus.SUCCESS, progressCurrent=1, progressTotal=1,
            progressMessage=msg)
        self.assertEqual(job['status'], JobStatus.SUCCESS)
        self.assertNotification(notification["_id"], ProgressState.SUCCESS, total, 5, msg)
