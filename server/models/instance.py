#!/usr/bin/env python
# -*- coding: utf-8 -*-

from bson import ObjectId
import datetime
import requests
import time

from girder import logger
from girder.constants import AccessType, SortDir, TokenScope
from girder.exceptions import ValidationException
from girder.models.model_base import AccessControlledModel
from girder.models.setting import Setting
from girder.models.token import Token
from girder.models.user import User
from girder.plugins.worker import getCeleryApp
from girder.plugins.jobs.constants import JobStatus, REST_CREATE_JOB_TOKEN_SCOPE
from gwvolman.tasks import \
    create_volume, launch_container, update_container, shutdown_container, \
    remove_volume, build_tale_image, \
    CREATE_VOLUME_STEP_TOTAL, BUILD_TALE_IMAGE_STEP_TOTAL, \
    LAUNCH_CONTAINER_STEP_TOTAL, UPDATE_CONTAINER_STEP_TOTAL

from ..constants import InstanceStatus, PluginSettings
from ..lib.metrics import metricsLogger
from ..schema.misc import containerInfoSchema
from ..utils import init_progress, notify_event

from girder.plugins.wholetale.models.tale import Tale
from girder.plugins.wholetale.models.image import Image

TASK_TIMEOUT = 15.0
BUILD_TIMEOUT = 360.0
DEFAULT_IDLE_TIMEOUT = 1440.0


class Instance(AccessControlledModel):

    def initialize(self):
        self.name = 'instance'
        compoundSearchIndex = (
            ('taleId', SortDir.ASCENDING),
            ('creatorId', SortDir.DESCENDING),
            ('name', SortDir.ASCENDING)
        )
        self.ensureIndices([(compoundSearchIndex, {})])

        self.exposeFields(
            level=AccessType.READ,
            fields={'_id', 'created', 'creatorId', 'iframe', 'name', 'taleId'})
        self.exposeFields(
            level=AccessType.WRITE,
            fields={'containerInfo', 'lastActivity', 'status', 'url', 'sessionId'})

    def validate(self, instance):
        if not InstanceStatus.isValid(instance['status']):
            raise ValidationException(
                'Invalid instance status %s.' % instance['status'],
                field='status')
        return instance

    def list(self, user=None, tale=None, limit=0, offset=0,
             sort=None, currentUser=None):
        """
        List a page of jobs for a given user.

        :param user: The user who owns the job.
        :type user: dict or None
        :param limit: The page limit.
        :param offset: The page offset
        :param sort: The sort field.
        :param currentUser: User for access filtering.
        """
        cursor_def = {}
        if user is not None:
            cursor_def['creatorId'] = user['_id']
        if tale is not None:
            cursor_def['taleId'] = tale['_id']
        cursor = self.find(cursor_def, sort=sort)
        for r in self.filterResultsByPermission(
                cursor=cursor, user=currentUser, level=AccessType.READ,
                limit=limit, offset=offset):
            yield r

    def updateAndRestartInstance(self, instance, user, tale):
        """
        Updates and restarts an instance.

        :param image: The instance document to restart.
        :type image: dict
        :returns: The instance document that was edited.
        """
        token = Token().createToken(user=user, days=0.5)

        digest = tale['imageInfo']['digest']

        resource = {
            'type': 'wt_update_instance',
            'instance_id': instance['_id'],
            'tale_title': tale['title']
        }
        total = UPDATE_CONTAINER_STEP_TOTAL

        notification = init_progress(
            resource, user, 'Updating instance',
            'Initializing', total)

        update_container.signature(
            args=[str(instance['_id'])], queue='manager',
            girder_job_other_fields={
                'wt_notification_id': str(notification['_id'])
            },
            girder_client_token=str(token['_id']),
            kwargs={'digest': digest}
        ).apply_async()

    def updateInstance(self, instance):
        """
        Updates an instance.

        :param image: The instance document to restart.
        :type image: dict
        :returns: The instance document that was edited.
        """

        instance['updated'] = datetime.datetime.utcnow()
        return self.save(instance)

    def deleteInstance(self, instance, user):
        initial_status = instance["status"]
        instance["status"] = InstanceStatus.DELETING
        instance = self.updateInstance(instance)
        token = Token().createToken(user=user, days=0.5)
        app = getCeleryApp()
        active_queues = list(app.control.inspect().active_queues().keys())

        instanceTask = shutdown_container.signature(
            args=[str(instance['_id'])], queue='manager', girder_client_token=str(token['_id']),
        ).apply_async()
        instanceTask.get(timeout=TASK_TIMEOUT)

        notify_event([instance['creatorId']], 'wt_instance_deleting',
                     {'taleId': instance['taleId'], 'instanceId': instance['_id']})

        try:
            queue = 'celery@{}'.format(instance['containerInfo']['nodeId'])
            if queue in active_queues:
                volumeTask = remove_volume.signature(
                    args=[str(instance['_id'])],
                    girder_client_token=str(token['_id']),
                    queue=instance['containerInfo']['nodeId']
                ).apply_async()
                volumeTask.get(timeout=TASK_TIMEOUT)
        except KeyError:
            pass

        # TODO: handle error
        self.remove(instance)

        notify_event([instance["creatorId"]], "wt_instance_deleted",
                     {'taleId': instance['taleId'], 'instanceId': instance['_id']})

        metricsLogger.info(
            "instance.remove",
            extra={
                "details": {
                    "id": instance["_id"],
                    "taleId": instance["taleId"],
                    "status": initial_status,
                    "containerInfo": instance.get("containerInfo"),
                }
            },
        )

    def createInstance(self, tale, user, /, *, name=None, save=True, spawn=True):
        if not name:
            name = tale.get('title', '')

        now = datetime.datetime.utcnow()
        instance = {
            'created': now,
            'creatorId': user['_id'],
            'iframe': tale.get('iframe', False),
            'lastActivity': now,
            'name': name,
            'status': InstanceStatus.LAUNCHING,
            'taleId': tale['_id']
        }

        self.setUserAccess(instance, user=user, level=AccessType.ADMIN)
        if save:
            instance = self.save(instance)

        if spawn:
            # Create single job
            token = Token().createToken(
                user=user,
                days=0.5,
                scope=(TokenScope.USER_AUTH, REST_CREATE_JOB_TOKEN_SCOPE)
            )

            resource = {
                'type': 'wt_create_instance',
                'tale_id': tale['_id'],
                'instance_id': instance['_id'],
                'tale_title': tale['title']
            }

            total = BUILD_TALE_IMAGE_STEP_TOTAL + CREATE_VOLUME_STEP_TOTAL + \
                LAUNCH_CONTAINER_STEP_TOTAL

            notification = init_progress(
                resource, user, 'Creating instance',
                'Initializing', total)

            buildTask = build_tale_image.signature(
                args=[str(tale['_id']), False],
                girder_job_other_fields={
                    'wt_notification_id': str(notification['_id']),
                    'instance_id': str(instance['_id']),
                },
                girder_client_token=str(token['_id']),
                girder_user=user,
                immutable=True
            )
            volumeTask = create_volume.signature(
                args=[str(instance['_id'])],
                girder_job_other_fields={
                    'wt_notification_id': str(notification['_id']),
                    'instance_id': str(instance['_id']),
                },
                girder_client_token=str(token['_id']),
                girder_user=user,
                immutable=True
            )
            serviceTask = launch_container.signature(
                girder_job_other_fields={
                    'wt_notification_id': str(notification['_id']),
                    'instance_id': str(instance['_id']),
                },
                girder_client_token=str(token['_id']),
                girder_user=user,
                queue='manager'
            )

            (buildTask | volumeTask | serviceTask).apply_async()

            notify_event([instance["creatorId"]], "wt_instance_launching",
                         {'taleId': instance['taleId'], 'instanceId': instance['_id']})

        metricsLogger.info(
            "instance.create",
            extra={
                "details": {
                    "id": instance["_id"],
                    "taleId": instance["taleId"],
                    "spawn": spawn,
                }
            },
        )

        return instance

    def get_logs(self, instance, tail):
        r = requests.get(
            Setting().get(PluginSettings.LOGGER_URL),
            params={"tail": tail, "name": instance["containerInfo"].get("name")}
        )
        try:
            r.raise_for_status()
            return r.text
        except requests.exceptions.HTTPError:
            return f"Logs for instance {instance['_id']} are currently unavailable..."


def _wait_for_server(url, token, timeout=30, wait_time=0.5):
    """Wait for a server to show up within a newly launched instance."""
    tic = time.time()
    while time.time() - tic < timeout:
        try:
            r = requests.get(url, cookies={'girderToken': token}, timeout=1)
            r.raise_for_status()
            if int(r.headers.get("Content-Length", "0")) == 0:
                raise ValueError("HTTP server returns no content")
        except requests.exceptions.HTTPError as err:
            logger.info(
                'Booting server at [%s], getting HTTP status [%s]', url, err.response.status_code)
            time.sleep(wait_time)
        except requests.exceptions.SSLError:
            logger.info(
                'Booting server at [%s], getting SSLError', url)
            time.sleep(wait_time)
        except requests.exceptions.ConnectionError:
            logger.info(
                'Booting server at [%s], getting ConnectionError', url)
            time.sleep(wait_time)
        except Exception as ex:
            logger.info(
                'Booting server at [%s], getting "%s"', url, str(ex))
        else:
            break


def finalizeInstance(event):
    job = event.info['job']

    if job.get("instance_id"):
        instance = Instance().load(job["instance_id"], force=True)

        if (
            instance["status"] == InstanceStatus.LAUNCHING
            and job["status"] == JobStatus.ERROR  # noqa
        ):
            instance["status"] = InstanceStatus.ERROR
            Instance().updateInstance(instance)

    if job['title'] == 'Spawn Instance' and job.get('status') is not None:
        status = int(job['status'])
        instance_id = job['args'][0]['instanceId']
        instance = Instance().load(instance_id, force=True, exc=True)
        tale = Tale().load(instance['taleId'], force=True)
        update = True
        event_name = None

        if (
            status == JobStatus.SUCCESS
            and instance["status"] == InstanceStatus.LAUNCHING  # noqa
        ):
            # Get a url to the container
            service = getCeleryApp().AsyncResult(job['celeryTaskId']).get()
            url = service.get("url", "https://girder.hub.yt/")

            # Generate the containerInfo
            valid_keys = set(containerInfoSchema['properties'].keys())
            containerInfo = {key: service.get(key, '') for key in valid_keys}
            # Preserve the imageId / current digest in containerInfo
            containerInfo["imageId"] = tale["imageId"]
            containerInfo["digest"] = tale["imageInfo"]["digest"]

            # Set the url and the containerInfo since they're used in /authorize
            new_fields = {"url": url, "containerInfo": containerInfo}
            if "sessionId" in service:
                new_fields["sessionId"] = ObjectId(service["sessionId"])
            Instance().update({"_id": instance["_id"]}, {"$set": new_fields})

            user = User().load(instance["creatorId"], force=True)
            token = Token().createToken(user=user, days=0.25)
            _wait_for_server(url, token['_id'])

            # Since _wait_for_server can potentially take some time,
            # we need to refresh the state of the instance
            # TODO: Why? What can modify instance status at this point?
            instance = Instance().load(instance_id, force=True, exc=True)
            if instance["status"] != InstanceStatus.LAUNCHING:
                return  # bail

            instance["status"] = InstanceStatus.RUNNING
            event_name = "wt_instance_running"
        elif (
            status == JobStatus.ERROR
            and instance["status"] != InstanceStatus.ERROR  # noqa
        ):
            instance['status'] = InstanceStatus.ERROR
        elif (
            status == JobStatus.ERROR
            and instance["status"] == InstanceStatus.ERROR  # noqa
        ):
            event_name = "wt_instance_error"
        elif (
            status in (JobStatus.QUEUED, JobStatus.RUNNING)
            and instance["status"] != InstanceStatus.LAUNCHING  # noqa
        ):
            instance['status'] = InstanceStatus.LAUNCHING
        else:
            update = False

        if update:
            msg = "Updating instance ({_id}) in finalizeInstance".format(**instance)
            msg += " for job(id={_id}, status={status})".format(**job)
            logger.debug(msg)
            Instance().updateInstance(instance)

            if event_name:
                notify_event([instance["creatorId"]], event_name,
                             {'taleId': instance['taleId'], 'instanceId': instance['_id']})


def cullIdleInstances(event):
    """
    Stop idle instances that have exceeded the configured timeout
    """

    logger.info("Culling idle instances")

    images = Image().find()
    for image in images:
        idleTimeout = image.get('idleTimeout', DEFAULT_IDLE_TIMEOUT)

        cullbefore = datetime.datetime.utcnow() - datetime.timedelta(minutes=idleTimeout)

        instances = Instance().find({
            'lastActivity': {'$lt': cullbefore},
            'containerInfo.imageId': image['_id']
        })

        for instance in instances:
            logger.info('Stopping instance {}: idle timeout exceeded.'.format(instance['_id']))
            user = User().load(instance['creatorId'], force=True)
            Instance().deleteInstance(instance, user)
