#!/usr/bin/env python
# -*- coding: utf-8 -*-
import requests

from girder import logger
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import boundHandler, filtermodel
from girder.constants import TokenScope
from girder.utility.model_importer import ModelImporter
from ..dataone_register import \
    extract_metadata_docs, \
    get_documents, \
    extract_data_docs, \
    extract_resource_docs, \
    check_multiple_metadata
from ..constants import DataONELocations


def register_http_resource(parent, parentType, progress, user, url, name):
    progress.update(increment=1, message='Processing file {}.'.format(url))
    headers = requests.head(url).headers
    size = headers.get('Content-Length') or \
        headers.get('Content-Range').split('/')[-1]
    fileModel = ModelImporter.model('file')
    fileDoc = fileModel.createLinkFile(
        url=url, parent=parent, name=name, parentType=parentType,
        creator=user, size=int(size),
        mimeType=headers.get('Content-Type', 'application/octet-stream'),
        reuseExisting=True)
    gc_file = fileModel.filter(fileDoc, user)

    gc_item = ModelImporter.model('item').load(
        gc_file['itemId'], force=True)
    gc_item['meta'] = {'identifier': 'unknown', 'provider': 'HTTP'}
    gc_item = ModelImporter.model('item').updateItem(gc_item)
    return gc_item


def register_DataONE_resource(parent,
                              parentType,
                              progress,
                              user,
                              pid,
                              name=None,
                              base_url=DataONELocations.prod_cn):
    """Create a package description (Dict) suitable for dumping to JSON."""
    progress.update(increment=1, message='Processing package {}.'.format(pid))

    # query for things in the resource map. At this point, it is assumed that the pid
    # has been correctly identified by the user in the UI.

    docs = get_documents(pid, base_url)

    # Filter the Solr result by TYPE so we can construct the package
    metadata = extract_metadata_docs(docs)
    data = extract_data_docs(docs)
    children = extract_resource_docs(docs)

    # Add in URLs to resolve each metadata/data object by
    for i in range(len(metadata)):
        metadata[i]['url'] = \
            "{}/resolve/{}".format(base_url, metadata[i]['identifier'])

    for i in range(len(data)):
        data[i]['url'] = \
            "{}/resolve/{}".format(base_url, data[i]['identifier'])

    # Determine the folder name. This is usually the title of the metadata file
    # in the package but when there are multiple metadata files in the package,
    # we need to figure out which one is the 'main' or 'documenting' one.
    primary_metadata = [doc for doc in metadata if 'documents' in doc]

    check_multiple_metadata(primary_metadata)

    # Create a Dict to store folders' information
    # the data key is a concatenation of the data and any metadata objects
    # that aren't the main or documenting metadata

    data += [doc for doc in metadata
             if doc['identifier'] != primary_metadata[0]['identifier']]
    if not name:
        name = primary_metadata[0]['title']

    gc_folder = ModelImporter.model('folder').createFolder(
        parent, name, description='',
        parentType=parentType, creator=user, reuseExisting=True)
    gc_folder = ModelImporter.model('folder').setMetadata(
        gc_folder, {'identifier': primary_metadata[0]['identifier'],
                    'provider': 'DataONE'})

    fileModel = ModelImporter.model('file')
    itemModel = ModelImporter.model('item')
    for fileObj in data:
        try:
            fileName = fileObj['fileName']
        except KeyError:
            fileName = fileObj['identifier']

        gc_item = itemModel.createItem(
            fileName, user, gc_folder, reuseExisting=True)
        gc_item = itemModel.setMetadata(
            gc_item, {'identifier': fileObj['identifier']})

        fileModel.createLinkFile(
            url=fileObj['url'], parent=gc_item,
            name=fileName, parentType='item',
            creator=user, size=int(fileObj['size']),
            mimeType=fileObj['formatId'], reuseExisting=True)

    # Recurse and add child packages if any exist
    if children is not None and len(children) > 0:
        for child in children:
            logger.debug('Registering child package, {}'.debug(child['identifier']))
            register_DataONE_resource(gc_folder,
                                      'folder',
                                      progress,
                                      user,
                                      child['identifier'],
                                      base_url)

    logger.debug('Finished registering dataset')
    return gc_folder


@access.user(scope=TokenScope.DATA_READ)
@filtermodel(model='folder')
@autoDescribeRoute(
    Description('List all folders containing references to an external data')
    .errorResponse('Write access denied for parent collection.', 403)
)
@boundHandler()
def listImportedData(self, params):
    q = {'meta.provider': {'$exists': 1}}
    return list(ModelImporter.model('folder').find(query=q))
