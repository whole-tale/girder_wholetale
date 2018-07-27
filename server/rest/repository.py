#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import re
import requests
from urllib.parse import urlparse
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.constants import TokenScope, AccessType
from girder.api.docs import addModel
from girder.api.rest import Resource, RestException
from girder.utility.model_importer import ModelImporter
from ..dataone_register import \
    D1_lookup, \
    get_package_list
from ..constants import DataONELocations
from ..dataone_upload import create_upload_package

dataMap = {
    'type': 'object',
    'description': ('A container with a basic information about '
                    'a set of external data resources.'),
    'properties': {
        'dataId': {
            'type': 'string',
            'description': 'External dataset identificator, such as URL.'
        },
        'repository': {
            'type': 'string',
            'description': 'Name of a data repository holding the dataset.'
        },
        'doi': {
            'type': 'string',
            'description': 'Digital Object Identifier'
        },
        'name': {
            'type': 'string',
            'description': ('A user-friendly name. Defaults to the name '
                            'provided by an external repository.')
        },
        'size': {
            'type': 'integer',
            'description': 'Size of the dataset in bytes.'
        }
    },
    'required': ['dataId', 'repository', 'doi', 'name', 'size'],
    'example': {
        'dataId': 'urn:uuid:42969280-e11c-41a9-92dc-33964bf785c8',
        'doi': '10.5063/F1Z899CZ',
        'name': ('Data from a dynamically downscaled projection of past and '
                 'future microclimates covering North America from 1980-1999 '
                 'and 2080-2099'),
        'repository': 'DataONE',
        'size': 178679
    },
}

fileMap = {
    'type': 'object',
    'description': ('A container with a list of filenames and sizes '
                    'from a DataONE repository.'),
    'properties': {
        'name': {
            'type': 'string',
            'description': 'The name of the data file.'
        },
        'size': {
            'type': 'integer',
            'description': 'Size of the file in bytes.'
        }
    },
    'required': ['name', 'fileList'],
    'example': {
        "Doctoral Dissertation Research: Mapping Community Exposure to Coastal Climate Hazards"
        "in the Arctic: A Case Study in Alaska's North Slope":
            {'fileList':
                [{'science_metadata.xml':
                    {'size': 8961}}],
             'Arctic Slope Shoreline Change Risk Spatial Data Model, 2015-16':
                 {'fileList':
                    [{'science_metadata.xml':
                        {'size': 7577}}]},
             'North Slope Borough shoreline change risk WebGIS usability workshop.':
                 {'fileList':
                    [{'science_metadata.xml':
                        {'size': 7940}}]},
             'Local community verification of shoreline change risks along the Alaskan Arctic Ocean'
                 'coast'
             ' (North Slope).':
                 {'fileList':
                    [{'science_metadata.xml':
                        {'size': 14250}}]},
             'Arctic Slope Shoreline Change Susceptibility Spatial Data Model, 2015-16':
                 {'fileList':
                    [{'science_metadata.xml':
                        {'size': 10491}}]}}
    }
}

addModel('dataMap', dataMap)
addModel('fileMap', fileMap)


def _http_lookup(pid):
    url = urlparse(pid)
    if url.scheme not in ('http', 'https'):
        return
    headers = requests.head(pid).headers

    valid_target = headers.get('Content-Type') is not None
    valid_target = valid_target and ('Content-Length' in headers or
                                     'Content-Range' in headers)
    if not valid_target:
        return

    if 'Content-Disposition' in headers:
        fname = re.search('^.*filename=([\w.]+).*$',
                          headers['Content-Disposition'])
        if fname:
            fname = fname.groups()[0]
    else:
        fname = os.path.basename(url.path.rstrip('/'))

    size = headers.get('Content-Length') or \
        headers.get('Content-Range').split('/')[-1]

    return dict(dataId=pid, doi='unknown', name=fname, repository='HTTP',
                size=int(size))


class Repository(Resource):
    def __init__(self):
        super(Repository, self).__init__()
        self.resourceName = 'repository'

        self.route('GET', ('lookup',), self.lookupData)
        self.route('GET', ('listFiles',), self.listFiles)
        self.route('GET', ('createPackage',), self.createPackage)

    @access.public
    @autoDescribeRoute(
        Description('Create data mapping to an external repository.')
        .notes('Given a list of external data identifiers, '
               'returns mapping to specific repository '
               'along with a basic metadata, such as size, name.')
        .jsonParam('dataId', paramType='query', required=True,
                   description='List of external datasets identificators.')
        .param('base_url', 'The node endpoint url. This can be used '
                           'to register datasets from custom networks, '
                           'such as the DataONE development network. This can '
                           'be passed in as an ordinary string. Examples '
                           'include https://dev.nceas.ucsb.edu/knb/d1/mn/v2 and '
                           'https://cn.dataone.org/cn/v2',
               required=False, dataType='string', default=DataONELocations.prod_cn)
        .responseClass('dataMap', array=True))
    def lookupData(self, dataId, base_url):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        futures = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            for pid in dataId:
                futures[executor.submit(D1_lookup, pid, base_url)] = pid
                futures[executor.submit(_http_lookup, pid)] = pid

            for future in as_completed(futures):
                try:
                    if future.result():
                        results.append(future.result())
                except RestException:
                    pass

            return sorted(results, key=lambda k: k['name'])

    @access.public
    @autoDescribeRoute(
        Description('Retrieve a list of files and nested packages in a DataONE repository')
        .notes('Given a list of external data identifiers, '
               'returns a list of files inside along with '
               'their sizes')
        .jsonParam('dataId', paramType='query', required=True,
                   description='List of external datasets identificators.')
        .param('base_url', 'The member node base url. This can be used '
                           'to search datasets from custom networks ,'
                           'such as the DataONE development network.',
               required=False, dataType='string',
               default=DataONELocations.prod_cn)
        .responseClass('fileMap', array=True))
    def listFiles(self, dataId, base_url):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        results = []
        futures = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            for pid in dataId:
                futures[executor.submit(get_package_list, pid, base_url)] = pid
                futures[executor.submit(_http_lookup, pid)] = pid

            for future in as_completed(futures):
                try:
                    if future.result():
                        results.append(future.result())
                except RestException:
                    pass

            return results

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Uploads files to DataONE, which creates a package out of them.')
        .notes('This endpoint takes a list of items, a tale, and a user-which are used to '
               'upload the items and tale artifacts to DataONE. During this '
               'process, any required metadata such as the EML document, system metadata, and '
               'RDF document are generated. The landing page for the package is returned as a '
               'string  The itemId parameter should look like [\'item1\', \'item2\', \'item3\']')
        .jsonParam(name='itemIds',
                   required=True,
                   description='The files that are going to be uploaded to DataONE')
        .param('taleId',
               description='The ID of the tale that the user wants to publish.',
               required=True)
        .param('repository',
               description='The url for the member node endpoint.',
               required=True)
        .param('jwt',
               description='The user\'s DataONE jwt.',
               required=True)
    )
    def createPackage(self, itemIds, taleId, repository, jwt):
        user = ModelImporter.model('user').getAdmins()[0]
        tale = self.model('tale',
                          'wholetale').load(taleId,
                                            user=user,
                                            level=AccessType.READ)

        package_url = create_upload_package(item_ids=itemIds,
                                            tale=tale,
                                            user=user,
                                            repository=repository,
                                            jwt=jwt)
        return package_url
