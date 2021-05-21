#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder.api import access
from girder.api.docs import addModel
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel
from girder.constants import AccessType, SortDir, TokenScope
from ..schema.misc import containerConfigSchema, tagsSchema

imageModel = {
    "description": "Object representing a WT Image.",
    "required": [
        "_id",
        "name",
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
        "tags": {
            "type": "array",
            "items": {
                "type": "string"
            },
            "description": "A human readable identification of the environment."
        },
        "parentId": {
            "type": "string",
            "description": "ID of a previous version of the Image"
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
        'name': 'Jupyter Notebook',
        'creatorId': '18312dcdbaec030000144d233',
        'created': '2017-01-09T18:56:27.262000+00:00',
        'description': 'Jupyter Notebook environment',
        'parentId': 'null',
        'public': True,
        'tags': ['jupyter', 'py3'],
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
        .pagingParams(defaultSort='name',
                      defaultSortDir=SortDir.ASCENDING)
    )
    def listImages(self, parentId, text, tag, limit, offset, sort, params):
        user = self.getCurrentUser()
        imageModel = self.model('image', 'wholetale')

        filters = {}
        if parentId:
            parent = imageModel.load(
                parentId, user=user, level=AccessType.READ, exc=True)
            filters['parentId'] = parent['_id']
        if tag:
            filters['tags'] = tag

        if text:
            return list(imageModel.textSearch(
                text, user=user, limit=limit, offset=offset, sort=sort,
                filters=filters, level=AccessType.READ))
        else:
            cursor = imageModel.find(filters, sort=sort)
            return list(imageModel.filterResultsByPermission(
                cursor, user, AccessType.READ, limit, offset))

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
        .param('idleTimeout', 'How long an instance of this image can be idle before being culled',
               dataType='integer', required=False)
        .jsonParam('tags', 'A human readable labels for the image.',
                   required=False, schema=tagsSchema)
        .responseClass('image')
        .errorResponse('ID was invalid.')
        .errorResponse('Read/write access was denied for the image.', 403)
        .errorResponse('Tag already exists.', 409)
    )
    def updateImage(self, image, name, description, public, icon, iframe, idleTimeout, tags,
                    params):
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
        if idleTimeout is not None:
            image['idleTimeout'] = idleTimeout
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
        .param('name', 'A name of the image.', required=False)
        .param('description', 'A description of the image.',
               required=False)
        .param('public', 'Whether the image should be publicly visible.'
               ' Defaults to True.', dataType='boolean', required=False)
        .param('icon', 'An icon representing the content of the image.',
               required=False)
        .param('iframe', 'If "true", tales using this image can be embedded in an iframe',
               ' Defaults to False.', dataType='boolean', default=False, required=False)
        .param('idleTimeout', 'How long an instance of this image can be idle before being culled',
               dataType='integer', required=False)
        .jsonParam('tags', 'A human readable labels for the image.',
                   required=False, schema=tagsSchema)
        .jsonParam('config', 'Default image runtime configuration',
                   required=False, schema=containerConfigSchema)
        .responseClass('image')
        .errorResponse('Query parameter was invalid')
    )
    def createImage(self, name, description, public, icon,
                    iframe, idleTimeout, tags, config, params):
        user = self.getCurrentUser()
        return self.model('image', 'wholetale').createImage(
            name=name, tags=tags, creator=user,
            save=True, parent=None, description=description, public=public,
            config=config, icon=icon, iframe=iframe, idleTimeout=idleTimeout)

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
