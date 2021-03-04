#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder import events
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.docs import addModel
from girder.api.rest import Resource, filtermodel, RestException
from girder.constants import AccessType, SortDir
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.worker import getCeleryApp
from ..constants import PluginSettings, InstanceStatus
from ..models.instance import Instance as instanceModel
from urllib.parse import urlparse, parse_qs
import cherrypy
from girder.models.token import Token
from girder.models.user import User
from girder.plugins.oauth.rest import OAuth as OAuthResource


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

    @access.public
    @autoDescribeRoute(
        Description('Make authorization decision for instance based on forwarded URL')
        .param('fhost', 'Forwarded host', required=False)
        .param('redirect', 'If true, redirect to fhost',
               default=True, required=False, dataType='boolean')
    )
    def authorize(self, fhost, redirect):
        """
        Intended for use with traefik forwardauth

        Does the user have access to the instance specified by the host name
        in the 'fhost' parameter or the X-Forwarded-Host header?

        Assumes the following flow:

        * User accesses instance tmp-xxx.wholetale.org
        * Traefik forwardauth calls this endpoint with "X-Forwarded-Host" set to the
          host name and "X-Forwarded-Uri" set to "/"
        * In the initial request, we don't know who the user is, so run them
          through the oauth flow with this endpoint as the callback (requires)
          changing the Globus Auth config). Set the "fhost" parameter to the
          forwarded host name.
        * At the end of the Globus auth flow, we'll have a user and know the
          forwarded host. Redirect to the original forwarded host with the
          "?token=x" query string.
        * In the subsequent request for https://tmp-xxx.wholetale.org/?token=xxx,
          forward autho will be called with the token in the X-Forwarded-Uri.
          Get the token and load the user, checkif they actually have access to this
          instance. If so, return 200. If not return 403.
        """

        # TODO: Why is this none when I call as a logged in user?
        user = self.getCurrentUser()

        # The X-Forwarded-Uri header means this is a forwardauth request.
        # Check for an existing token and load the user if present.
        furi = cherrypy.request.headers.get('X-Forwarded-Uri')
        if furi:
            qs = parse_qs(urlparse(furi).query)
            if 'token' in qs:
                token = Token().load(qs['token'][0], force=True, objectId=False)
                user = User().load(token["userId"], force=True)

        # If there's no user, initiate the oauth flow with this endpoint
        # as the callback along with the fhost parameter
        if user is None:
            fhost = cherrypy.request.headers.get('X-Forwarded-Host')
            # With forwardauth, the base will be https://tmp-xxx...
            # TODO: fix hardcode
            cherrypy.request.base = "https://girder.local.wholetale.org"
            redirect = cherrypy.request.base + cherrypy.request.app.script_name
            redirect += cherrypy.request.path_info + "?"
            redirect += "&fhost=" + fhost
            redirect += "&token={girderToken}"
            oauth_providers = OAuthResource().listProviders(params={"redirect": redirect})
            raise cherrypy.HTTPRedirect(oauth_providers["Globus"])

        # If the fhost parameter is set and we have a user, this is the Globus
        # auth callback. Redirect to the original service with the token.
        if not fhost:
            fhost = cherrypy.request.headers.get('X-Forwarded-Host')
        elif redirect:
            # Redirect to the requested host to set the token
            # Can't set a cookie on tmp-xxx.* from girder.*
            # self.sendAuthTokenCookie(user, domain=fhost)
            token = self.getCurrentToken()["_id"]
            redirect = "https://" + fhost + "/?token=" + token
            raise cherrypy.HTTPRedirect(redirect)

        # At this point we have a user and the fhost from  either a querystring
        # parameter or forwarded header. Check to see if the user has access
        # to the instance.
        instances = list(self._model.list(user=user, currentUser=user))
        access = False
        # TODO: hardcode for testing only
        if fhost == "whoami.local.wholetale.org":
            access = True
        for instance in instances:
            url = urlparse(instance['url'])
            if fhost == url.netloc:
                access = True
                break

        if not access:
            raise RestException('Access denied for instance', code=403)
        else:
            return fhost
