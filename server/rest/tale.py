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
from girder.utility.progress import ProgressContext
from girder.models.token import Token
from girder.models.folder import Folder
from girder.plugins.jobs.constants import REST_CREATE_JOB_TOKEN_SCOPE
from gwvolman.tasks import import_tale

from ..schema.tale import taleModel as taleSchema
from ..models.tale import Tale as taleModel
from ..models.image import Image as imageModel

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
        self.route('POST', ('import', ), self.createTaleFromDataset)
        self.route('DELETE', (':id',), self.deleteTale)
        self.route('GET', (':id', 'access'), self.getTaleAccess)
        self.route('PUT', (':id', 'access'), self.updateTaleAccess)
        self.route('GET', (':id', 'export'), self.exportTale)
        self.route('GET', (':id', 'generateTree'), self.generateTree)

    @access.public
    @filtermodel(model='tale', plugin='wholetale')
    @autoDescribeRoute(
        Description('Return all the tales accessible to the user')
        .param('text', ('Perform a full text search for Tale with a matching '
                        'title or description.'), required=False)
        .param('userId', "The ID of the tale's creator.", required=False)
        .param('imageId', "The ID of the tale's image.", required=False)
        .param(
            'level',
            'The minimum access level to the Tale.',
            required=False,
            dataType='integer',
            default=AccessType.READ,
            enum=[AccessType.NONE, AccessType.READ, AccessType.WRITE, AccessType.ADMIN],
        )
        .pagingParams(defaultSort='title',
                      defaultSortDir=SortDir.DESCENDING)
        .responseClass('tale', array=True)
    )
    def listTales(self, text, userId, imageId, level, limit, offset, sort,
                  params):
        currentUser = self.getCurrentUser()
        image = None
        if imageId:
            image = imageModel().load(imageId, user=currentUser, level=AccessType.READ, exc=True)

        creator = None
        if userId:
            creator = self.model('user').load(userId, force=True, exc=True)

        if text:
            filters = {}
            if creator:
                filters['creatorId'] = creator['_id']
            if image:
                filters['imageId'] = image['_id']
            return list(self._model.textSearch(
                text, user=currentUser, filters=filters,
                limit=limit, offset=offset, sort=sort, level=level))
        else:
            return list(self._model.list(
                user=creator, image=image, limit=limit, offset=offset,
                sort=sort, currentUser=currentUser, level=level))

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
        .param('progress', 'Whether to record progress on this task.',
               required=False, dataType='boolean', default=False)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def deleteTale(self, tale, progress):
        user = self.getCurrentUser()
        workspace = Folder().load(
            tale['workspaceId'], user=user, level=AccessType.ADMIN)
        with ProgressContext(
                progress, user=user,
                title='Deleting workspace of {title}'.format(**tale),
                message='Calculating folder size...') as ctx:
            if progress:
                ctx.update(total=Folder().subtreeCount(workspace))
            Folder().remove(workspace, progress=ctx)
        self._model.remove(tale)

    @access.user
    @autoDescribeRoute(
        Description('Create a new tale from an external dataset.')
        .notes('Currently, this task only handles importing raw data. '
               'In the future, it should also allow importing serialized Tales.')
        .param('imageId', "The ID of the tale's image.", required=True)
        .param('url', 'External dataset identifier.', required=True)
        .param('spawn', 'If false, create only Tale object without a corresponding '
                        'Instance.',
               default=True, required=False, dataType='boolean')
        .jsonParam('lookupKwargs', 'Optional keyword arguments passed to '
                   'GET /repository/lookup', requireObject=True, required=False)
        .jsonParam('taleKwargs', 'Optional keyword arguments passed to POST /tale',
                   required=False)
        .responseClass('job')
        .errorResponse('You are not authorized to create tales.', 403)
    )
    def createTaleFromDataset(self, imageId, url, spawn, lookupKwargs, taleKwargs):
        user = self.getCurrentUser()
        image = imageModel().load(imageId, user=user, level=AccessType.READ,
                                  exc=True)
        token = self.getCurrentToken()
        Token().addScope(token, scope=REST_CREATE_JOB_TOKEN_SCOPE)

        try:
            lookupKwargs['dataId'] = [url]
        except TypeError:
            lookupKwargs = dict(dataId=[url])

        try:
            taleKwargs['imageId'] = str(image['_id'])
        except TypeError:
            taleKwargs = dict(imageId=str(image['_id']))

        taleTask = import_tale.delay(
            lookupKwargs, taleKwargs, spawn=spawn,
            girder_client_token=str(token['_id'])
        )
        return taleTask.job

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
                image, tale['dataSet'], creator=user, save=True,
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

    @access.public
    @autoDescribeRoute(
        Description('Returns a tree of file and folder nodes that jsTree can parse.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.ADMIN)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def generateTree(self, tale):
        """
        Recursively iterates over the files and folders to generate an object that
        jsTree can use to create a tree.

        :param tale: The ID of the Tale that the tree is generated for
        :return: List of root nodes
        """
        current_user = self.getCurrentUser()

        # Generate the Workspace Tree
        workspace_folder = self.model('folder').load(tale['workspaceId'],
                                                     user=current_user)

        # This folder doesn't have a name, so set it to the Workspace name
        workspace_folder['name'] = 'Workspace'
        workspace_records = self.create_tree_from_root(workspace_folder,
                                                       current_user,
                                                       True)

        # Generate the Data Tree. Since there isn't a containing folder, create a fake one
        data_folder = self.create_tree_record(None, 'Data', 'linkify', None)
        for data_item in tale['dataSet']:
            if data_item['_modelType'] == 'folder':
                data_item = self.model('folder').load(data_item['itemId'], user=current_user)
            data_folder['children'].append(self.create_tree_from_root(data_item,
                                                                      current_user,
                                                                      True))
        return [workspace_records, data_folder]

    def create_tree_record(self, object_id, name, model, parent_id):
        """
        Node records make up the jsTree, and are added to the 'children'
        attribute. This method takes the needed parameters to make a
        full node. The icon attribute maps to an icon in the dashboard,
        which is why we append icon to the end. The possibilites are
        'folder icon', 'file icon', and 'linkify icon' (for the data directory)

        :param object_id: The ID of the node
        :param name: The name of the node
        :param model: The node's model
        :param parent_id: The potential parent
        :return:
        """
        record = {
            'id': object_id,
            'text': name,
            'icon': model + ' icon',
            'state': {
                'opened': False,
                'disabled': False,
                'selected': True
            },
            'children': [],
            'li_attr': {},
            'a_attr': {}
        }

        if parent_id:
            record['parent'] = parent_id
        return record

    def create_tree_from_root(self, root, user, is_root=False):
        """
        Recursively constructs a tree conforming to jsTree's JSON format
        :param root: The root node that the tree starts at
        :param user: The logged in user
        :param is_root: Set to true when there shouldn't be a parent node
        :return:
        """
        record = self.create_tree_record(str(root['_id']),
                                         root['name'],
                                         'folder',
                                         None if is_root else str(root['parentId']))
        records = list()
        records.append(record)
        folders = self.model('folder').childFolders(root,
                                                    parentType='folder',
                                                    user=user)
        for folder in folders:
            record['children'].append(self.create_tree_from_root(folder, user=user))
        child_files = self.model('folder').childItems(folder=root, user=user)
        for child_file in child_files:
            file_record = self.create_tree_record(str(child_file['_id']),
                                                  child_file['name'],
                                                  'file',
                                                  str(child_file['folderId']))
            record['children'].append(file_record)
        return record
