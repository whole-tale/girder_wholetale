#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder.api import access
from girder.api.docs import addModel
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel, RestException
from girder.constants import AccessType, SortDir, TokenScope
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.jobs.models.job import Job
from girder.plugins.worker import getCeleryApp
from ..constants import ImageStatus
from ..schema.misc import containerConfigSchema, tagsSchema
from ..utils import \
    create_repository_file

imageModel = {
    "description": "Object representing a WT Image.",
    "required": [
        "_id",
        "fullName",
        "status",
        "imageId",
        "digest",
        "tags",
        "parentId"
    ],
    "properties": {
        "_id": {
            "type": "string",
            "description": "internal unique identifier"
        },
        "name": {
            "type": "string",
            "description": "A user-friendly name"
        },
        "fullName": {
            "type": "string",
            "description": ("An image name following docker format: "
                            "namespace/repository(@digest)"),
        },
        "description": {
            "type": "string"
        },
        "config": {
            "$ref": "#/definitions/containerConfig"
        },
        "icon": {
            "type": "string",
            "description": "A URL with an image icon"
        },
        "iframe": {
            "type": "boolean",
            "description": "If 'true', the tale can be embedded in an iframe"
        },
        "imageId": {
            "type": "string",
            "description": "A image used to build the image."
        },
        "digest": {
            "type": "string",
            "description": ("Checksum of a successfully built image "
                            "that can be used to pull a specific version "
                            " of the image."),
        },
        "tags": {
            "type": "array",
            "items": {
                "type": "string"
            },
            "description": "A human readable identification of the Recipe.",
            "default": [
                "latest"
            ]
        },
        "parentId": {
            "type": "string",
            "description": "ID of a previous version of the Image"
        },
        "status": {
            "type": "string",
            "default": "unavailable",
            "description": "Status of the image.",
            "enum": [
                "invalid",
                "unavailable",
                "building",
                "available"
            ]
        },
        "public": {
            "type": "boolean",
            "default": True,
            "description": "If set to true the image can be accessed by anyone"
        },
        "created": {
            "type": "string",
            "format": "date-time",
            "description": "The time when the image was created."
        },
        "creatorId": {
            "type": "string",
            "description": "A unique identifier of the user that created the image."
        },
        "updated": {
            "type": "string",
            "format": "date-time",
            "description": "The last time when the image was modified."
        }
    },
    'example': {
        '_accessLevel': 2,
        '_id': '5873dcdbaec030000144d233',
        '_modelType': 'image',
        'fullName': 'Xarthisius/wt_image',
        'creatorId': '18312dcdbaec030000144d233',
        'created': '2017-01-09T18:56:27.262000+00:00',
        'description': 'My fancy image',
        'digest': '123456',
        'parentId': 'null',
        'public': True,
        'tags': ['latest', 'py3'],
        'status': 'building',
        'updated': '2017-01-10T16:15:17.313000+00:00',
    },
}
addModel('image', imageModel, resources='image')


class Image(Resource):

    def __init__(self):
        super(Image, self).__init__()
        self.resourceName = 'image'

        self.route('GET', (), self.listImages)
        self.route('POST', (), self.createImage)
        self.route('GET', (':id',), self.getImage)
        self.route('PUT', (':id',), self.updateImage)
        self.route('DELETE', (':id',), self.deleteImage)
        self.route('PUT', (':id', 'build'), self.buildImage)
        self.route('PUT', (':id', 'check'), self.checkImage)
        self.route('POST', (':id', 'copy'), self.copyImage)
        self.route('GET', (':id', 'access'), self.getImageAccess)
        self.route('PUT', (':id', 'access'), self.updateImageAccess)

    @access.public
    @filtermodel(model='image', plugin='wholetale')
    @autoDescribeRoute(
        Description(('Returns all images from the system '
                     'that user has access to'))
        .responseClass('image', array=True)
        .param('parentId', "The ID of the image's parent.", required=False)
        .param('text', 'Perform a full text search for image with a matching '
               'name or description.', required=False)
        .param('tag', 'Search all images with a given tag.', required=False)
        .pagingParams(defaultSort='lowerName',
                      defaultSortDir=SortDir.DESCENDING)
    )
    def listImages(self, parentId, text, tag, limit, offset, sort, params):
        user = self.getCurrentUser()
        imageModel = self.model('image', 'wholetale')

        if parentId:
            parent = imageModel.load(
                parentId, user=user, level=AccessType.READ, exc=True)

            filters = {}
            if text:
                filters['$text'] = {
                    '$search': text
                }
            if tag:
                print('Do filtering by tag when I figure it out')

            return list(imageModel.childImages(
                parent=parent, user=user,
                offset=offset, limit=limit, sort=sort, filters=filters))
        elif text:
            return list(imageModel.textSearch(
                text, user=user, limit=limit, offset=offset, sort=sort))
        elif tag:
            raise RestException('Can filter by tag. yet...')
        else:
            return list(imageModel.list(user=user, offset=offset, limit=limit,
                                        sort=sort))

    @access.public(scope=TokenScope.DATA_READ)
    @filtermodel(model='image', plugin='wholetale')
    @autoDescribeRoute(
        Description('Get a image by ID.')
        .modelParam('id', model='image', plugin='wholetale', level=AccessType.READ)
        .responseClass('image')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the image.', 403)
    )
    def getImage(self, image, params):
        return image

    @access.user
    @autoDescribeRoute(
        Description('Update an existing image.')
        .modelParam('id', model='image', plugin='wholetale', level=AccessType.WRITE,
                    description='The ID of the image.')
        .param('name', 'A name of the image.', required=False)
        .param('description', 'A description of the image.',
               required=False)
        .param('public', 'Whether the image should be publicly visible.'
               ' Defaults to True.', dataType='boolean', required=False,
               default=True)
        .param('icon', 'An icon representing the content of the image.',
               required=False)
        .param('iframe', 'If "true", tales using this image can be embedded in an iframe',
               ' Defaults to False.', dataType='boolean', default=False, required=False)
        .jsonParam('tags', 'A human readable labels for the image.',
                   required=False, schema=tagsSchema)
        .responseClass('image')
        .errorResponse('ID was invalid.')
        .errorResponse('Read/write access was denied for the image.', 403)
        .errorResponse('Tag already exists.', 409)
    )
    def updateImage(self, image, name, description, public, icon, iframe, tags, params):
        if name is not None:
            image['name'] = name
        if description is not None:
            image['description'] = description
        if tags is not None:
            image['tags'] = tags
        if icon is not None:
            image['icon'] = icon
        if iframe is not None:
            image['iframe'] = iframe
        # TODO: tags magic
        self.model('image', 'wholetale').setPublic(image, public)
        return self.model('image', 'wholetale').updateImage(image)

    @access.admin
    @autoDescribeRoute(
        Description('Delete an existing image.')
        .modelParam('id', model='image', plugin='wholetale', level=AccessType.WRITE,
                    description='The ID of the image.')
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the image.', 403)
    )
    def deleteImage(self, image, params):
        self.model('image', 'wholetale').remove(image)

    @access.user
    @filtermodel(model='image', plugin='wholetale')
    @autoDescribeRoute(
        Description('Create a new image.')
        .param('recipeId', 'The ID of a recipe used to build the image',
               dataType='string', required=True)
        .param('fullName', 'An image name conforming to docker standard',
               dataType='string', required=True)
        .param('name', 'A name of the image.', required=False)
        .param('description', 'A description of the image.',
               required=False)
        .param('public', 'Whether the image should be publicly visible.'
               ' Defaults to True.', dataType='boolean', required=False)
        .param('icon', 'An icon representing the content of the image.',
               required=False)
        .param('iframe', 'If "true", tales using this image can be embedded in an iframe',
               ' Defaults to False.', dataType='boolean', default=False, required=False)
        .jsonParam('tags', 'A human readable labels for the image.',
                   required=False, schema=tagsSchema)
        .jsonParam('config', 'Default image runtime configuration',
                   required=False, schema=containerConfigSchema)
        .responseClass('image')
        .errorResponse('Query parameter was invalid')
    )
    def createImage(self, recipeId, fullName, name, description, public, icon,
                    iframe, tags, config, params):
        user = self.getCurrentUser()
        recipe = self.model('recipe', 'wholetale').load(
            recipeId, user=user, level=AccessType.READ, exc=True)
        return self.model('image', 'wholetale').createImage(
            recipe, fullName, name=name, tags=tags, creator=user,
            save=True, parent=None, description=description, public=public,
            config=config, icon=icon, iframe=iframe)

    @access.user
    @autoDescribeRoute(
        Description('Build an existing image')
        .modelParam('id', model='image', plugin='wholetale', level=AccessType.WRITE,
                    description='The ID of the image.')
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the image.', 403)
    )
    def buildImage(self, image, params):
        user = self.getCurrentUser()
        recipe = self.model('recipe', 'wholetale').load(
            image['recipeId'], user=user, level=AccessType.READ, exc=True)
        jobTitle = 'Building image %s' % image['fullName']
        jobModel = Job()

        # Create a filesystem structure to save the repository to
        repo_file_id = create_repository_file(recipe)
        # Create a job to be handled by the worker plugin
        args = (
            str(image['_id']),
            recipe['url'],
            recipe['commitId']
        )
        job = jobModel.createJob(
            title=jobTitle, type='build_image', handler='worker_handler',
            user=user, public=False, args=args, kwargs={
                'file_id': repo_file_id}, otherFields={
                'celeryTaskName': 'gwvolman.tasks.build_image'
            })
        jobModel.scheduleJob(job)
        return job

    def updateImageStatus(self, event):
        job = event.info['job']
        if job['type'] == 'build_image' and job.get('status') is not None:
            status = int(job['status'])
            # FIXME: Who should be able to build images?
            image = self.model('image', 'wholetale').load(
                job['args'][0], force=True)
            if status == JobStatus.SUCCESS:
                result = getCeleryApp().AsyncResult(job['celeryTaskId']).get()
                image['digest'] = result['Id']
                image['status'] = ImageStatus.AVAILABLE
            elif status == JobStatus.ERROR:
                image['status'] = ImageStatus.INVALID
            elif status in (JobStatus.QUEUED, JobStatus.RUNNING):
                image['status'] = ImageStatus.BUILDING
            self.model('image', 'wholetale').updateImage(image)

    @access.admin
    @autoDescribeRoute(
        Description('Update/verify the status of the image')
        .modelParam('id', model='image', plugin='wholetale', level=AccessType.WRITE,
                    description='The ID of the image.')
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the image.', 403)
    )
    def checkImage(self, image, params):
        return self.model('image', 'wholetale').checkImage(image)

    @access.user
    @autoDescribeRoute(
        Description('Create a copy of an image using an updated recipe')
        .notes('Create a copy of an image preserving original fullName. '
               'Operation will only succeed if the new recipe is '
               'a descendant of the recipe used by the original image.')
        .modelParam('id', model='image', plugin='wholetale', level=AccessType.READ,
                    description='The ID of the image.')
        .param('recipeId', 'The ID of the new recipe', required=True)
    )
    def copyImage(self, image, recipeId, params):
        user = self.getCurrentUser()
        recipe = self.model('recipe', 'wholetale').load(
            recipeId, user=user, level=AccessType.READ, exc=True)
        return self.model('image', 'wholetale').copyImage(image, recipe, creator=user)

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Get the access control list for an image')
        .modelParam('id', model='image', plugin='wholetale', level=AccessType.ADMIN)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the image.', 403)
    )
    def getImageAccess(self, image):
        return self.model('image', 'wholetale').getFullAccessList(image)

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Update the access control list for an image.')
        .modelParam('id', model='image', plugin='wholetale', level=AccessType.ADMIN)
        .jsonParam('access', 'The JSON-encoded access control list.', requireObject=True)
        .jsonParam('publicFlags', 'JSON list of public access flags.', requireArray=True,
                   required=False)
        .param('public', 'Whether the image should be publicly visible.', dataType='boolean',
               required=False)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the image.', 403)
    )
    def updateImageAccess(self, image, access, publicFlags, public):
        user = self.getCurrentUser()
        return self.model('image', 'wholetale').setAccessList(
            image, access, save=True, user=user, setPublic=public, publicFlags=publicFlags)
