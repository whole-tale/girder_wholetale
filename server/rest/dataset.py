#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder.api import access
from girder.api.docs import addModel
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource
from girder.constants import AccessType, SortDir, TokenScope
from girder.models.model_base import ValidationException
from girder.utility import path as path_util
from girder.utility.progress import ProgressContext
from ..constants import \
    CATALOG_NAME,\
    DataONELocations
from ..schema.misc import dataMapListSchema
from ..utils import getOrCreateRootFolder
from .harvester import \
    register_http_resource, \
    register_DataONE_resource


datasetModel = {
    "description": "Object representing registered data.",
    "required": [
        "_id",
        "modelType"
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
        "modelType": {
            "type": "string",
            "description": "Model of the object.",
            "enum": [
                "folder",
                "item"
            ]
        },
        "created": {
            "type": "string",
            "format": "date-time",
            "description": "The time when the tale was created."
        },
        "creatorId": {
            "type": "string",
            "description": "A unique identifier of the user that created the tale."
        },
        "updated": {
            "type": "string",
            "format": "date-time",
            "description": "The last time when the tale was modified."
        },
        "size": {
            "type": "integer",
            "description": "Total size of the dataset in bytes."
        },
        "identifier": {
            "type": "string",
            "description": "External, unique identifier"
        },
        "provider": {
            "type": "string",
            "description": "Name of the provider",
            "enum": [
                "DataONE",
                "HTTP",
                "Globus"
            ]
        }
    }
}
datasetModelKeys = set(datasetModel['properties'].keys())
addModel('dataset', datasetModel, resources='dataset')


def _itemOrFolderToDataset(obj):
    ds = {key: obj[key] for key in obj.keys() & datasetModelKeys}
    ds['provider'] = obj['meta'].get('provider', 'unknown')
    ds['identifier'] = obj['meta'].get('identifier', 'unknown')
    ds['modelType'] = obj['_modelType']
    return ds


class Dataset(Resource):

    def __init__(self):
        super(Dataset, self).__init__()
        self.resourceName = 'dataset'

        self.route('GET', (), self.listDatasets)
        self.route('GET', (':id',), self.getDataset)
        self.route('PUT', (':id',), self.copyDatasetToHome)
        self.route('POST', ('register',), self.importData)

    @access.public
    @autoDescribeRoute(
        Description(('Returns all registered datasets from the system '
                     'that user has access to'))
        .responseClass('dataset', array=True)
        .param('text', 'Perform a full text search for image with a matching '
               'name or description.', required=False)
        .pagingParams(defaultSort='lowerName',
                      defaultSortDir=SortDir.DESCENDING)
    )
    def listDatasets(self, text, limit, offset, sort, params):
        user = self.getCurrentUser()
        folderModel = self.model('folder')
        datasets = []

        parent = getOrCreateRootFolder(CATALOG_NAME)
        for folder in folderModel.childFolders(
                parentType='folder', parent=parent, user=user,
                limit=limit, offset=offset, sort=sort):
            folder['_modelType'] = 'folder'
            datasets.append(_itemOrFolderToDataset(folder))

        for item in folderModel.childItems(
                folder=parent, limit=limit, offset=offset, sort=sort):
            item['_modelType'] = 'item'
            datasets.append(_itemOrFolderToDataset(item))
        return datasets

    def _getResource(self, id, type):
        model = self._getResourceModel(type)
        return model.load(id=id, user=self.getCurrentUser(), level=AccessType.READ)

    @access.public
    @autoDescribeRoute(
        Description('Get any registered dataset by ID.')
        .param('id', 'The ID of the Dataset.', paramType='path')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the resource.', 403)
    )
    def getDataset(self, id, params):
        user = self.getCurrentUser()
        try:
            doc = self.model('folder').load(id=id, user=user, level=AccessType.READ, exc=True)
            doc['_modelType'] = 'folder'
        except ValidationException:
            doc = self.model('item').load(id=id, user=user, level=AccessType.READ, exc=True)
            doc['_modelType'] = 'item'
        if 'meta' not in doc or 'provider' not in doc['meta']:
            raise ValidationException('No such item: %s' % str(doc['_id']), 'id')
        return _itemOrFolderToDataset(doc)

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description("Copy the dataset into User's Data folder")
        .param('id', 'The ID of the Dataset.', paramType='path')
        .jsonParam('dataset', 'Dataset being copied.',
                   paramType='body', schema=datasetModel, dataType='dataset')
        .errorResponse('Write access denied for parent collection.', 403)
    )
    def copyDatasetToHome(self, id, dataset, params):
        user = self.getCurrentUser()
        modelType = dataset['modelType']
        user_target_resource = path_util.lookUpPath(
            '/user/%s/Data' % user['login'], user)
        user_folder = user_target_resource['document']
        source_object = self.model(modelType).load(
            dataset['_id'], user=user, level=AccessType.READ, exc=True)

        if modelType == 'folder':
            self.model('folder').copyFolder(
                source_object, parent=user_folder, parentType='folder',
                public='original', creator=user)
        elif modelType == 'item':
            self.model('item').copyItem(
                source_object, user, folder=user_folder)
        return dataset  # Wrong, but I cannot set it to 204, or 201

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Create a folder containing references to an external data')
        .notes('This does not upload or copy the existing data, it just creates '
               'references to it in the Girder data hierarchy. Deleting '
               'those references will not delete the underlying data. This '
               'operation is currently only supported for DataONE repositories.\n'
               'If the parentId and the parentType is not provided, data will be '
               'registered into home directory of the user calling the endpoint')
        .param('parentId', 'Parent ID for the new parent of this folder.',
               required=False)
        .param('parentType', "Type of the folder's parent", required=False,
               enum=['folder', 'user', 'collection'], strip=True, default='folder')
        .param('public', 'Whether the folder should be publicly visible. '
               'Defaults to True.',
               required=False, dataType='boolean', default=True)
        .param('copyToHome', 'Whether to copy imported data to /User/Data/. '
               'Defaults to True.',
               required=False, dataType='boolean', default=True)
        .jsonParam('dataMap', 'A list of data mappings',
                   paramType='body', schema=dataMapListSchema)
        .param('base_url', 'The node endpoint url. This can be used '
                           'to register datasets from custom networks, '
                           'such as the DataONE development network. This can '
                           'be passed in as an ordinary string. Examples '
                           'include https://dev.nceas.ucsb.edu/knb/d1/mn/v2 and '
                           'https://cn.dataone.org/cn/v2',
               required=False, dataType='string', default=DataONELocations.prod_cn)
        .errorResponse('Write access denied for parent collection.', 403)
    )
    def importData(self,
                   parentId,
                   parentType,
                   public,
                   copyToHome,
                   dataMap,
                   base_url,
                   params):
        user = self.getCurrentUser()

        if not parentId or parentType not in ('folder', 'item'):
            parent = getOrCreateRootFolder(CATALOG_NAME)
            parentType = 'folder'
        else:
            parent = self.model(parentType).load(
                parentId, user=user, level=AccessType.WRITE, exc=True)

        progress = True
        importedData = dict(folder=[], item=[])
        with ProgressContext(progress, user=user,
                             title='Registering resources') as ctx:
            for data in dataMap:
                if data['repository'] == 'DataONE':
                    importedData['folder'].append(
                        register_DataONE_resource(
                            parent,
                            parentType,
                            ctx,
                            user,
                            data['dataId'],
                            name=data['name'],
                            base_url=base_url)
                    )
                elif data['repository'] == 'HTTP':
                    importedData['item'].append(
                        register_http_resource(parent, parentType, ctx, user,
                                               data['dataId'], data['name'])
                    )

        if copyToHome:
            with ProgressContext(progress, user=user,
                                 title='Copying to workspace') as ctx:
                userDataFolder = path_util.lookUpPath('/user/%s/Data' % user['login'], user)
                for folder in importedData['folder']:
                    self.model('folder').copyFolder(
                        folder, creator=user, name=folder['name'],
                        parentType='folder', parent=userDataFolder['document'],
                        description=folder['description'],
                        public=folder['public'], progress=ctx)
                for item in importedData['item']:
                    self.model('item').copyItem(
                        item, creator=user, name=item['name'],
                        folder=userDataFolder['document'],
                        description=item['description'])
