#!/usr/bin/env python
# -*- coding: utf-8 -*-
import datetime
from girder import events
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.docs import addModel
from girder.api.rest import (
    Resource,
    filtermodel,
    RestException,
    setResponseHeader,
    setRawResponse
)
from girder.constants import AccessType, SortDir
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.worker import getCeleryApp
from ..constants import PluginSettings, InstanceStatus
from ..models.instance import Instance as instanceModel
import cherrypy


instanceSchema = {
    'id': 'instance',
    'type': 'object',
    'required': [
        '_accessLevel', '_id', '_modelType', 'containerId',
        'containerPath', 'created', 'digest',
        'frontendId', 'imageId',  'lastActivity', 'mountPoint',
        'status', 'userId', 'when'
    ],
    'example': {
        '_accessLevel': 2,
        '_id': '587506670791d3000121b68d',
        '_modelType': 'instance',
        'containerInfo': {
            'containerId': '397914f6bf9e4d153dd86',
            'containerPath': 'user/.../login?token=...',
            'host': '172.17.0.1',
            'mountPoint': '/var/lib/docker/volumes/58caa69f9fcbde0001/_data',
            'volumeName': '58ca9fcbde0001df4d26_foo',
            'digest': 'sha256:198246816212941281ab1243de09c9adbca92',
            'imageId': '58caa69f00f4d26cbd9fe01d'
        },
        'created': '2017-04-07T17:04:04.777000+00:00',
        'creatorId': '57c099af86ed1d0001733722',
        'iframe': True,
        'lastActivity': '2017-04-07T17:04:04.777000+00:00',
        'name': 'test',
        'status': 0,
        'taleId': '58caa69f9fcbde0001df4d26',
        'url': 'user/hkhHpMloA4Pp/login?token=babf41833c9641a4a92bece48a34e5b7'
    },
    'properties': {
        '_accessLevel': {'type': 'integer', 'format': 'int32'},
        '_id': {'type': 'string'},
        '_modelType': {'type': 'string'},
        'containerInfo': {
            '$ref': '#/definitions/containerInfo'
        },
        'created': {'type': 'string', 'format': 'date'},
        'creatorId': {'type': 'string'},
        'iframe': {
            'type': 'boolean',
            'description': 'If "true", instance can be embedded in an iframe'
        },
        'lastActivity': {'type': 'string', 'format': 'date'},
        'name': {'type': 'string'},
        'status': {'type': 'integer', 'format': 'int32',
                   'allowEmptyValue': False,
                   'maximum': 1, 'minimum': 0},
        'taleId': {'type': 'string'},
        'url': {'type': 'string'}
    }
}
addModel('instance', instanceSchema, resources='instance')
instanceCapErrMsg = (
    'You have reached a limit for running instances ({}). '
    'Please shutdown one of the running instances before '
    'continuing.'
)


class Instance(Resource):

    def __init__(self):
        super(Instance, self).__init__()
        self.resourceName = 'instance'
        self._model = instanceModel()

        self.route('GET', (), self.listInstances)
        self.route('POST', (), self.createInstance)
        self.route('GET', (':id',), self.getInstance)
        self.route('DELETE', (':id',), self.deleteInstance)
        self.route('PUT', (':id',), self.updateInstance)
        self.route('GET', (':id', 'log'), self.getInstanceLog)
        self.route('GET', ('authorize', ), self.authorize)

        events.bind('jobs.job.update.after', 'wholetale', self.handleUpdateJob)

    @access.user
    @filtermodel(model='instance', plugin='wholetale')
    @autoDescribeRoute(
        Description('Return all the running instances accessible by the user')
        .param('userId', "The ID of the instance's creator.", required=False)
        .param('taleId',  'List all the instanes using this tale.', required=False)
        .param('text', 'Perform a full text search for a tale with a matching '
               'name.', required=False)
        .responseClass('instance', array=True)
        .pagingParams(defaultSort='created', defaultSortDir=SortDir.DESCENDING)
    )
    def listInstances(self, userId, taleId, text, limit, offset, sort, params):
        # TODO: text search is ignored
        currentUser = self.getCurrentUser()
        if taleId:
            tale = self.model('tale', 'wholetale').load(
                taleId, user=currentUser, level=AccessType.READ)
        else:
            tale = None

        if userId:
            user = self.model('user').load(userId, force=True, exc=True)
        else:
            user = None

        # TODO allow to search for instances that belongs to specific user
        return list(self.model('instance', 'wholetale').list(
            user=user, tale=tale, offset=offset, limit=limit,
            sort=sort, currentUser=currentUser))

    @access.user
    @filtermodel(model='instance', plugin='wholetale')
    @autoDescribeRoute(
        Description('Get an instance by ID.')
        .modelParam('id', model='instance', plugin='wholetale', level=AccessType.READ)
        .responseClass('instance')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the instance.', 403)
    )
    def getInstance(self, instance, params):
        return instance

    @access.user
    @filtermodel(model='instance', plugin='wholetale')
    @autoDescribeRoute(
        Description('Updates and restarts an existing instance.')
        .modelParam('id', model='instance', plugin='wholetale', level=AccessType.WRITE)
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the instance.', 403)
    )
    def updateInstance(self, instance):
        currentUser = self.getCurrentUser()

        taleId = instance['taleId']
        tale = self.model('tale', 'wholetale').load(
            taleId, user=currentUser, level=AccessType.READ)

        # TODO: Only continue if digest has changed
        # if image['digest'] != instance['containerInfo']['digest']:

        # Digest ensures that container runs from newest image version
        self._model.updateAndRestartInstance(
            instance,
            currentUser,
            tale)
        return instance

    @access.user
    @autoDescribeRoute(
        Description('Delete an existing instance.')
        .modelParam('id', model='instance', plugin='wholetale', level=AccessType.WRITE)
        .errorResponse('ID was invalid.')
        .errorResponse('Write access was denied for the instance.', 403)
    )
    def deleteInstance(self, instance, params):
        self.model('instance', 'wholetale').deleteInstance(
            instance, self.getCurrentUser())

    @access.user
    @filtermodel(model='instance', plugin='wholetale')
    @autoDescribeRoute(
        Description('Create a new instance')
        .notes('Instantiate a tale.')
        .param('taleId', 'The ID of a tale used to create an instance.',
               required=True)
        .param('name', 'A user-friendly, short name of the tale.',
               required=False)
        .param('spawn', 'If false, create only db object without a corresponding '
                        'container.',
               default=True, required=False, dataType='boolean')
        .responseClass('instance')
        .errorResponse(instanceCapErrMsg, 400)
        .errorResponse('Read access was denied for the tale.', 403)
    )
    def createInstance(self, taleId, name, spawn):
        user = self.getCurrentUser()

        taleModel = self.model('tale', 'wholetale')
        tale = taleModel.load(
            taleId, user=user, level=AccessType.READ)

        existing = self._model.findOne({
            'taleId': tale['_id'],
            'creatorId': user['_id'],
        })
        if existing:
            return existing

        running_instances = list(
            self._model.list(user=user, currentUser=user)
        )
        instance_cap = self.model('setting').get(PluginSettings.INSTANCE_CAP)
        if len(running_instances) + 1 > int(instance_cap):
            raise RestException(instanceCapErrMsg.format(instance_cap))

        return self._model.createInstance(tale, user, name=name, save=True, spawn=spawn)

    def handleUpdateJob(self, event):
        job = event.info['job']
        if not (job['title'] == 'Update Instance' and job.get('status') is not None):
            return

        status = int(job['status'])
        instance = self._model.load(job['args'][0], force=True)

        if status == JobStatus.SUCCESS:
            result = getCeleryApp().AsyncResult(job['celeryTaskId']).get()
            instance['containerInfo'].update(result)
            instance['status'] = InstanceStatus.RUNNING
        elif status == JobStatus.ERROR:
            instance['status'] = InstanceStatus.ERROR
        elif status in (JobStatus.QUEUED, JobStatus.RUNNING):
            instance['status'] = InstanceStatus.LAUNCHING
        self._model.updateInstance(instance)

    @access.cookie
    @access.public
    @autoDescribeRoute(
        Description('Determine whether user has access to instance requested via forward auth')
    )
    def authorize(self):
        # This endpoint must be called frmo a Traefik forward-auth request. The X-Forwarded-Host
        # is assumed to be the hostname for a running instance. Also assumes that the
        # core.cookie_domain is set to .(local.)wholetale.org
        user = self.getCurrentUser()

        forwarded_host = cherrypy.request.headers.get('X-Forwarded-Host')
        forwarded_uri = cherrypy.request.headers.get('X-Forwarded-Uri')
        if not forwarded_host and not forwarded_uri:
            raise RestException('Forward auth request required', code=400)
        subdomain, domain = forwarded_host.split('.', 1)

        if user is None:
            # If no user, redirect to authentication endpoint to initiate oauth flow
            redirect = f'https://{forwarded_host}{forwarded_uri}'
            # As a forward-auth request, the host is the origin (e.g., tmp-xxx.*)
            # but we need to redirect to Girder.
            raise cherrypy.HTTPRedirect(
                  f'https://girder.{domain}/api/v1/user/sign_in?redirect={redirect}')

        instance = self._model.findOne(
            {"containerInfo.name": subdomain, "creatorId": user["_id"]}
        )
        if instance is None:
            raise RestException('Access denied for instance', code=403)

        # Authorize can be called quite a lot. Therefore we only update db
        # once every 5 min.
        now = datetime.datetime.utcnow()
        if instance["lastActivity"] + datetime.timedelta(minutes=5) < now:
            self._model.update({"_id": instance["_id"]}, {"$set": {"lastActivity": now}})

    @access.user
    @autoDescribeRoute(
        Description("Fetch Instance logs")
        .modelParam('id', model='instance', plugin='wholetale', level=AccessType.READ)
        .param("tail", "Number of lines to show from the end of the logs",
               default=100, required=False, dataType='int')
        .produces("text/plain")
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the instance.', 403)
    )
    def getInstanceLog(self, instance, tail):
        if tail < 0:
            tail = "all"
        setResponseHeader('Content-Type', "text/plain")
        setRawResponse()
        return self._model.get_logs(instance, tail)
