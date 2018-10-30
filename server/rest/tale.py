#!/usr/bin/env python
# -*- coding: utf-8 -*-
import re
import requests

from girder.api import access
from girder.api.docs import addModel
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel, RestException,\
    setResponseHeader, setContentDisposition

from girder.constants import AccessType, SortDir, TokenScope
from girder.utility import ziputil
from ..schema.tale import taleModel as taleSchema
from ..models.tale import Tale as taleModel


addModel('tale', taleSchema, resources='tale')


class Tale(Resource):

    def __init__(self):
        super(Tale, self).__init__()
        self.resourceName = 'tale'
        self._model = taleModel()

        self.route('GET', (), self.listTales)
        self.route('GET', (':id',), self.getTale)
        self.route('PUT', (':id',), self.updateTale)
        self.route('POST', (), self.createTale)
        self.route('DELETE', (':id',), self.deleteTale)
        self.route('GET', (':id', 'access'), self.getTaleAccess)
        self.route('PUT', (':id', 'access'), self.updateTaleAccess)
        self.route('GET', (':id', 'export'), self.exportTale)

    @access.public
    @filtermodel(model='tale', plugin='wholetale')
    @autoDescribeRoute(
        Description('Return all the tales accessible to the user')
        .param('userId', "The ID of the tale's creator.", required=False)
        .param('imageId', "The ID of the tale's image.", required=False)
        .param('text', ('Perform a full text search for recipe with matching '
                        'Title or description.'), required=False)
        .responseClass('tale', array=True)
        .pagingParams(defaultSort='lowerName',
                      defaultSortDir=SortDir.DESCENDING)
    )
    def listTales(self, userId, imageId, text, limit, offset, sort,
                  params):
        currentUser = self.getCurrentUser()
        if imageId:
            image = self.model('image', 'wholetale').load(
                imageId, user=currentUser, level=AccessType.READ, exc=True)
        else:
            image = None

        if userId:
            user = self.model('user').load(userId, force=True, exc=True)
        else:
            user = None

        if text:
            return list(self._model.textSearch(
                text, user=user, limit=limit, offset=offset, sort=sort))
        else:
            return list(self._model.list(
                user=user, data=None, image=image,
                currentUser=currentUser,
                offset=offset, limit=limit, sort=sort))

    @access.public
    @filtermodel(model='tale', plugin='wholetale')
    @autoDescribeRoute(
        Description('Get a tale by ID.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.READ)
        .responseClass('tale')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the tale.', 403)
    )
    def getTale(self, tale, params):
        return tale

    @access.user
    @autoDescribeRoute(
        Description('Update an existing tale.')
        .modelParam('id', model='tale', plugin='wholetale',
                    level=AccessType.WRITE, destName='taleObj')
        .jsonParam('tale', 'Updated tale', paramType='body', schema=taleSchema,
                   dataType='tale')
        .responseClass('tale')
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def updateTale(self, taleObj, tale, params):
        is_public = tale.pop('public')

        for keyword in self._model.modifiableFields:
            try:
                taleObj[keyword] = tale.pop(keyword)
            except KeyError:
                pass
        taleObj = self._model.updateTale(taleObj)

        was_public = taleObj.get('public', False)
        if was_public != is_public:
            access = self._model.getFullAccessList(taleObj)
            user = self.getCurrentUser()
            taleObj = self._model.setAccessList(
                taleObj, access, save=True, user=user, setPublic=is_public)

        # if taleObj['published']:
        #     self._model.setPublished(taleObj, True)
        return taleObj

    @access.user
    @autoDescribeRoute(
        Description('Delete an existing tale.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.ADMIN)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def deleteTale(self, tale, params):
        self._model.remove(tale)

    @access.user
    @autoDescribeRoute(
        Description('Create a new tale.')
        .jsonParam('tale', 'A new tale', paramType='body', schema=taleSchema,
                   dataType='tale')
        .responseClass('tale')
        .errorResponse('You are not authorized to create tales.', 403)
    )
    def createTale(self, tale, params):

        user = self.getCurrentUser()
        if 'instanceId' in tale:
            # check if instance exists
            # save disk state to a new folder
            # save config
            # create a tale
            raise RestException('Not implemented yet')
        else:
            image = self.model('image', 'wholetale').load(
                tale['imageId'], user=user, level=AccessType.READ, exc=True)
            default_author = ' '.join((user['firstName'], user['lastName']))
            return self._model.createTale(
                image, tale['involatileData'], creator=user, save=True,
                title=tale.get('title'), description=tale.get('description'),
                public=tale.get('public'), config=tale.get('config'),
                icon=image.get('icon', ('https://raw.githubusercontent.com/'
                                        'whole-tale/dashboard/master/public/'
                                        'images/whole_tale_logo.png')),
                illustration=tale.get(
                    'illustration', ('https://raw.githubusercontent.com/'
                                     'whole-tale/dashboard/master/public/'
                                     'images/demo-graph2.jpg')),
                authors=tale.get('authors', default_author),
                category=tale.get('category', 'science'),
                published=False, narrative=tale.get('narrative'),
                doi=tale.get('doi'), publishedURI=tale.get('publishedURI')
            )

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Get the access control list for a tale')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.ADMIN)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def getTaleAccess(self, tale):
        return self._model.getFullAccessList(tale)

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Update the access control list for a tale.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.ADMIN)
        .jsonParam('access', 'The JSON-encoded access control list.', requireObject=True)
        .jsonParam('publicFlags', 'JSON list of public access flags.', requireArray=True,
                   required=False)
        .param('public', 'Whether the tale should be publicly visible.', dataType='boolean',
               required=False)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def updateTaleAccess(self, tale, access, publicFlags, public):
        user = self.getCurrentUser()
        return self._model.setAccessList(
            tale, access, save=True, user=user, setPublic=public, publicFlags=publicFlags)

    @access.user
    @autoDescribeRoute(
        Description('Export a tale.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.READ)
        .responseClass('tale')
        .produces('application/zip')
        .errorResponse('ID was invalid.', 404)
        .errorResponse('You are not authorized to export this tale.', 403)
    )
    def exportTale(self, tale, params):
        user = self.getCurrentUser()
        folder = self.model('folder').load(
            tale['folderId'],
            user=user,
            level=AccessType.READ,
            exc=True)
        image = self.model('image', 'wholetale').load(
            tale['imageId'], user=user, level=AccessType.READ, exc=True)
        recipe = self.model('recipe', 'wholetale').load(
            image['recipeId'], user=user, level=AccessType.READ, exc=True)

        # Construct a sanitized name for the ZIP archive using a whitelist
        # approach
        zip_name = re.sub('[^a-zA-Z0-9-]', '_', tale['title'])

        setResponseHeader('Content-Type', 'application/zip')
        setContentDisposition(zip_name + '.zip')

        # Temporary: Fetch the GitHub archive of the recipe. Note that this is
        # done in a streaming fashion because ziputil makes use of generators
        # when files are added to the zip
        url = '{}/archive/{}.tar.gz'.format(recipe['url'], recipe['commitId'])
        req = requests.get(url, stream=True)

        def stream():
            zip = ziputil.ZipGenerator(zip_name)

            # Add files from the Tale folder
            for (path, f) in self.model('folder').fileList(folder,
                                                           user=user,
                                                           subpath=False):

                for data in zip.addFile(f, path):
                    yield data

            # Temporary: Add Image metadata
            for data in zip.addFile(lambda: image.__str__(), 'image.txt'):
                yield data

            # Temporary: Add Recipe metadata
            for data in zip.addFile(lambda: recipe.__str__(), 'recipe.txt'):
                yield data

            # Temporary: Add a zip of the recipe archive
            # TODO: Grab proper filename from header
            # e.g. 'Content-Disposition': 'attachment; filename= \
            # jupyter-base-b45f9a575602e6038b4da6333f2c3e679ee01c58.tar.gz'
            for data in zip.addFile(req.iter_content, 'archive.tar.gz'):
                yield data

            yield zip.footer()

        return stream
