#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder.api.docs import addModel


dataMapSchema = {
    'title': 'dataMap',
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'description': 'A schema for a WholeTale Data Map',
    'type': 'object',
    'properties': {
        'dataId': {
            'type': 'string',
            'description': ('An internal unique identifier specific '
                            'to a given repository.'),
        },
        'doi': {
            'type': 'string',
            'description': 'A unique Digital Object Identifier'
        },
        'name': {
            'type': 'string'
        },
        'repository': {
            'type': 'string',
            'description': 'A name of the repository holding the data.'
        },
        'size': {
            'type': 'integer',
            'minimum': 0,
            'description': 'The total size of the dataset in bytes.'
        }
    },
    'required': ['dataId', 'repository']
}

dataMapListSchema = {
    'title': 'list of dataMaps',
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'type': 'array',
    'items': dataMapSchema,
}

tagsSchema = {
    'title': 'tags',
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'description': 'A schema for recipe/image tags',
    'type': 'array',
    'items': {
        'type': 'string'
    }
}

containerConfigSchema = {
    'title': 'containerConfig',
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'description': 'A subset of docker runtime configuration used for Tales',
    'type': 'object',
    'properties': {
        'command': {
            'type': 'string',
        },
        'cpuShares': {
            'type': 'string',
        },
        'memLimit': {
            'type': 'string',
        },
        'port': {
            'type': 'integer',
        },
        'user': {
            'type': 'string',
        },
        'targetMount': {
            'type': 'string',
        },
        'urlPath': {
            'type': 'string',
        }
    }
}

containerInfoSchema = {
    'title': 'containerInfo',
    '$schema': 'http://json-schema.org/draft-04/schema#',
    'description': 'A subset of docker info parameters used by Tales',
    'type': 'object',
    'properties': {
        'created': {
            'type': 'string',
            'format': 'date-time',
        },
        'name': {
            'type': 'string',
        },
        'nodeId': {
            'type': 'string',
        },
        'mountPoint': {
            'type': 'string',
        },
        'volumeName': {
            'type': 'string',
        },
        'urlPath': {
            'type': 'string',
        }
    },
    'required': ['name', 'mountPoint', 'nodeId', 'volumeName'],
}

addModel('containerConfig', containerConfigSchema)
