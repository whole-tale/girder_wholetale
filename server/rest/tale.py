#!/usr/bin/env python
# -*- coding: utf-8 -*-
import re
import requests
import json
import os

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

publishers = {
    "DataONE":
        {
            "@id": "https://www.dataone.org/",
            "@type": "Organization",
            "legalName": "DataONE",
            "Description": "A federated data network allowing access to science data"
        },
    "Globus":
        {
            "@id": "https://www.materialsdatafacility.org/",
            "@type": "Organization",
            "legalName": "Materials Data Facility",
            "Description": "A simple way to publish, discover, and access materials datasets"
        }
}


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
        self.route('GET', (':id', 'manifest'), self.generateManifest)

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

        # Construct a sanitized name for the ZIP archive using a whitelist
        # approach
        zip_name = re.sub('[^a-zA-Z0-9-]', '_', tale['title'])

        setResponseHeader('Content-Type', 'application/zip')
        setContentDisposition(zip_name + '.zip')

        def stream():
            zip_generator = ziputil.ZipGenerator(zip_name)

            # Add files from the workspace
            folder = self.model('folder').load(tale['workspaceId'], user=user)
            for (path, f) in self.model('folder').fileList(folder,
                                                           user=user,
                                                           subpath=False):
                for data in zip.addFile(f, 'workspace/' + path):
                    yield data

            # Add manifest.json
            manifest = self._generateManifest(tale)
            for data in zip_generator.addFile(lambda: json.dumps(manifest, indent=4),
                                              'metadata/manifest.json'):
                yield data

            # Add top level README
            for data in zip_generator.addFile(lambda: 'Instructions on running the docker container',
                                              'README.txt'):
                yield data

            # Add the environment
            for data in zip_generator.addFile(lambda: str(tale['imageId']),
                                              'environment.txt'):
                yield data

            yield zip_generator.footer()
        return stream

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Generate the Tale manifest.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.ADMIN)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def generateManifest(self, tale):
        return self._generateManifest(tale)

    def _generateManifest(self, tale):
        user = self.getCurrentUser()
        data_root = 'https://data.wholetale.org/api/v1/'
        doc = {
            "@context": [
                "https://w3id.org/bundle/context",
                {"schema": "http://schema.org/"},
                {"parent_dataset": {"@type": "@id"}}
            ],

            "@id": data_root+'tale/'+str(tale['_id']),
            "createdOn": str(tale['created']),
            "schema:name": tale['title'],
            "schema:description": tale.get('description', 'None'),
            "schema:category": tale['category'],
            "schema:identifier": str(tale['_id']),
            "schema:version": tale['format'],
            "schema:image": tale['illustration'],
            "aggregates": list(),
            "Datasets": list()
        }

        tale_user = self.model('user').load(tale['creatorId'], user=user)
        doc['createdBy'] = {
            "@id": tale['authors'],
            "@type": "schema:Person",
            "schema:givenName": tale_user.get('firstName', ''),
            "schema:familyName": tale_user.get('lastName', ''),
            "schema:email": tale_user.get('email', '')
        }

        # Handle the files in the workspace
        folder = self.model('folder').load(tale['workspaceId'], user=user)
        if folder:
            workspace_folder_files = self.model('folder').fileList(folder, user=user)
            for workspace_file in workspace_folder_files:
                doc['aggregates'].append({'uri': '../workspace/' + clean_workspace_path(tale['_id'],
                                                                                        workspace_file[0])})

        folder_files = list()
        datasets = set()
        """
        Handle objects that are in the dataSet, ie files that point to external sources.
        Some of these sources may be datasets from publishers. We need to save information 
        about the source so that they can added to the Datasets section.
        """
        for obj in tale['dataSet']:
            if obj['_modelType'] == 'folder':
                folder = self.model('folder').load(obj['itemId'], user=user)
                if folder:
                    # Check if it's a dataset by checking for meta.identifier
                    folder_meta = folder.get('meta')
                    if folder_meta:
                        dataset_identifier = folder_meta.get('identifier')
                        if dataset_identifier:
                            datasets.add(obj['itemId'])
                            folder_files.append({"dataset_identifier": dataset_identifier,
                                                 "provider": folder_meta.get('provider'),
                                                 "file_iterator": get_folder_files(self,
                                                                                   folder,
                                                                                   user)
                                                 })

                    else:
                        folder_files.append({"file_iterator": get_folder_files(self,
                                                                               folder,
                                                                               user)})
            elif obj['_modelType'] == 'item':
                """
                If there is a file that was added to a tale that came from a dataset, but outside
                the dataset folder, we need to get metadata about the parent folder and the file.

                """
                root_item = self.model('item').load(obj['itemId'], user=user)
                if root_item:
                    # Should always be true since the item is in dataSet
                    if root_item.get('meta'):
                        item_folder = self.model('folder').load(root_item['folderId'], user=user)
                        folder_meta = item_folder.get('meta')
                        if folder_meta:
                            datasets.add(root_item['folderId'])
                            folder_files.append({"dataset_identifier": folder_meta.get('identifier'),
                                                 "provider": folder_meta.get('provider'),
                                                 "file_iterator": self.model('item').fileList(root_item,
                                                                                              user=user,
                                                                                              data=False)
                                                 })

        """
        Add records for the remote files that exist under a folder
        """
        for folder_record in folder_files:
            if folder_record['file_iterator'] is None:
                continue
            for file_record in folder_record['file_iterator']:
                # Check if the file points to an external resource
                if 'linkUrl' in file_record[1]:
                    bundle = create_bundle('../data/' + get_dataset_file_path(file_record),
                                           file_record[1]['name'])
                    record = create_aggregation_record(file_record[1]['linkUrl'],
                                                       bundle,
                                                       folder_record.get('dataset_identifier'))
                    doc['aggregates'].append(record)

        """
        Add Dataset records
        """
        for folder_id in datasets:
            doc['Datasets'].append(create_dataset_record(self, user, folder_id))

        """
        Add records for files that we inject (README, LICENSE, etc)
        """
        doc['aggregates'].append({'uri': '../LICENSE',
                                  'schema:license': 'CC0'})

        doc['aggregates'].append({'uri': '../README.txt',
                                  '@type': 'schema:HowTo'})

        doc['aggregates'].append({'uri': '../environment.txt'})

        return doc


def create_aggregation_record(uri, bundle=None, parent_dataset=None):
    """
    Creates an aggregation record. Externally defined aggregations should include
    a bundle and a parent_dataset if it belongs to one

    :param uri:
    :param bundle:
    :param parent_dataset:
    :return:
    """
    aggregation = dict()
    aggregation['uri'] = uri
    if bundle:
        aggregation['bundledAs'] = bundle
    if parent_dataset:
        aggregation['parent_dataset'] = parent_dataset
    return aggregation


def get_folder_files(self, folder, user):
    return self.model('folder').fileList(folder,
                                         user=user,
                                         data=False)


def create_bundle(folder, filename):
    """
    Creates a bundle for an externally referenced file

    :param folder: The name of the folder that the file is in
    :param filename:  The name of the file
    :return: A dictionary record of the bundle
    """

    # Add a trailing slash to the path if there isn't one
    os.path.join(folder, '')
    return {
        'folder': folder,
        'filename': filename
    }


def clean_workspace_path(tale_id, path):
    return path.replace(str(tale_id) + '/', '')


def create_dataset_record(self, user, folder_id):
    """
    Creates
    :param self:
    :param user:
    :param folder_id:
    :return:
    """
    folder = self.model('folder').load(folder_id, user=user)
    if folder:
        meta = folder.get('meta')
        if meta:
            provider = meta.get('provider')
            if provider:
                return {
                    "@id": meta.get('identifier'),
                    "@type": "Dataset",
                    "name": folder['name'],
                    "identifier": meta.get('identifier'),
                    "publisher": publishers[provider]
                }


def get_dataset_file_path(file_info):
    """
    Removes a filename from a full path
    :param file_info:
    :return:
    """
    res = file_info[0].replace('/' + file_info[1]['name'], '')
    if res != file_info[0]:
        return res
    return ''
