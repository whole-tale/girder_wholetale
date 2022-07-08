#!/usr/bin/env python
# -*- coding: utf-8 -*-
from operator import itemgetter

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.docs import addModel
from girder.api.rest import Resource, RestException
from girder.models.setting import Setting

from ..constants import PluginSettings
from ..lib.dataone import DataONELocations
from ..lib.data_map import dataMapDoc
from ..lib.file_map import fileMapDoc
from ..lib import pids_to_entities


addModel('dataMap', dataMapDoc)
addModel('fileMap', fileMapDoc)


class Repository(Resource):
    def __init__(self):
        super(Repository, self).__init__()
        self.resourceName = 'repository'

        self.route('GET', (), self.getPublishRepositories)
        self.route('GET', ('lookup',), self.lookupData)
        self.route('GET', ('listFiles',), self.listFiles)

    @access.public
    @autoDescribeRoute(
        Description('Create data mapping to an external repository.')
        .notes(
            'Given a list of external data identifiers, returns mapping to specific repository '
            'along with a basic metadata, such as size, name.'
        )
        .jsonParam(
            'dataId',
            paramType='query',
            required=True,
            description='List of external datasets identificators.',
        )
        .param(
            'base_url',
            'The node endpoint url. This can be used to register datasets from custom networks, '
            'such as the DataONE development network. This can be passed in as '
            'an ordinary string. Examples include https://dev.nceas.ucsb.edu/knb/d1/mn/v2 and '
            'https://cn.dataone.org/cn/v2',
            required=False,
            dataType='string',
            default=DataONELocations.prod_cn,
        )
        .responseClass('dataMap', array=True)
    )
    def lookupData(self, dataId, base_url):
        try:
            results = pids_to_entities(
                dataId, user=self.getCurrentUser(), base_url=base_url, lookup=True
            )
        except RuntimeError as exc:
            raise RestException(exc.args[0])
        return sorted([x.toDict() for x in results], key=lambda k: k['name'])

    @access.public
    @autoDescribeRoute(
        Description(
            'Retrieve a list of files and nested packages in a DataONE repository'
        )
        .notes(
            'Given a list of external data identifiers, returns a list of files inside '
            'along with their sizes'
        )
        .jsonParam(
            'dataId',
            paramType='query',
            required=True,
            description='List of external datasets identificators.',
        )
        .param(
            'base_url',
            'The member node base url. This can be used to search datasets from custom networks ,'
            'such as the DataONE development network.',
            required=False,
            dataType='string',
            default=DataONELocations.prod_cn,
        )
        .responseClass('fileMap', array=True)
    )
    def listFiles(self, dataId, base_url):
        try:
            results = pids_to_entities(
                dataId, user=self.getCurrentUser(), base_url=base_url, lookup=False
            )
        except RuntimeError as exc:
            raise RestException(exc.args[0])
        return sorted([x.toDict() for x in results], key=lambda k: list(k))

    @access.public
    @autoDescribeRoute(
        Description(
            "Retrieve a list of repositories where user can deposit their Tale"
        )
    )
    def getPublishRepositories(self):
        user = self.getCurrentUser()
        if not user:
            return []

        targets = []
        for entry in Setting().get(PluginSettings.PUBLISHER_REPOS):
            repository = entry["repository"]
            publisher = entry["auth_provider"]
            if publisher.startswith("dataone"):
                key = "provider"  # Dataone
                value = publisher
            else:
                key = "resource_server"
                value = repository

            token = next(
                (_ for _ in user.get("otherTokens", []) if _.get(key) == value), None
            )
            if token:
                targets.append({"repository": repository, "name": entry["name"]})

        return sorted(targets, key=itemgetter("name"))
