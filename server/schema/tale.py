#!/usr/bin/env python
# -*- coding: utf-8 -*-

from .misc import containerConfigSchema, \
    dataSetSchema, \
    imageInfoSchema, \
    publishInfoListSchema

taleModel = {
    "definitions": {
        "containerConfig": containerConfigSchema,
        "dataSet": dataSetSchema,
        'imageInfo': imageInfoSchema,
        "publishInfo": publishInfoListSchema,
    },
    "description": "Object representing a Tale.",
    "required": [
        "dataSet",
        "imageId"
    ],
    "properties": {
        "_id": {
            "type": "string",
            "description": "internal unique identifier"
        },
        "title": {
            "type": "string",
            "description": "Title of the Tale"
        },
        "description": {
            "type": ["string", "null"],
            "description": "The description of the Tale (Markdown)"
        },
        "imageId": {
            "type": "string",
            "description": "ID of a WT Image used by the Tale"
        },
        "imageInfo": {
            "$ref": "#/definitions/imageInfo"
        },
        "dataSet": {
            "$ref": "#/definitions/dataSet"
        },
        "workspaceId": {
            "type": "string",
            "description": "ID of a folder containing Tale's workspace"
        },
        "format": {
            "type": "integer",
            "description": "Tale format specification"
        },
        "public": {
            "type": "boolean",
            "description": "If set to true the Tale is accessible by anyone.",
            "default": True
        },
        "config": {
            "$ref": "#/definitions/containerConfig"
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
        "authors": {
            "type": "array",
            "items": {
                'type': 'object',
                'description': "A JSON structure representing a Tale author."
            },
            "description": "A list of authors that are associated with the Tale"
        },
        "category": {
            "type": "string",
            "description": "Keyword describing topic of the Tale"
        },
        "illustration": {
            "type": "string",
            "description": "A URL to an image depicturing the content of the Tale"
        },
        "iframe": {
            "type": "boolean",
            "description": "If 'true', the tale can be embedded in an iframe"
        },
        "icon": {
            "type": "string",
            "description": "A URL to an image icon"
        },
        "license": {
            "type": "string",
            "description": "The license that the Tale is under"
        },
        "publishInfo": {
            "$ref": "#/definitions/publishInfo"
        },
        "copyOfTale": {
            "type": ["string", "null"],
            "description": "An ID of a source Tale, if the Tale is a copy."
        },
    },
    'example': {
        "_accessLevel": 2,
        "_id": "5c4887409759c200017b2310",
        "_modelType": "tale",
        "authors": [
            {
                "firstName": "Kacper",
                "lastName": "Kowalik",
                "orcid": "https://www.orcid.org/0000-0003-1709-3744"
            },
            {
                "firstName": "Tommy",
                "lastName": "Thelen",
                "orcid": "https://www.orcid.org/0000-0003-1709-3754"
            }
        ],
        "category": "science",
        "config": {},
        "copyOfTale": "5c4887409759c200017b231f",
        "created": "2019-01-23T15:24:48.217000+00:00",
        "creatorId": "5c4887149759c200017b22c0",
        "dataSet": [
            {
                "itemId": "5c4887389759c200017b230e",
                "mountPath": "illustris.jpg"
            }
        ],
        "description": "#### Markdown Editor",
        "doi": "doi:x.xx.xxx",
        "format": 4,
        "icon": ("https://raw.githubusercontent.com/whole-tale/jupyter-base/"
                 "master/squarelogo-greytext-orangebody-greymoons.png"),
        "iframe": True,
        "illustration": ("https://raw.githubusercontent.com/whole-tale/dashboard/"
                         "master/public/images/demo-graph2.jpg"),
        "imageId": "5c4886279759c200017b22a3",
        'imageInfo': {
            'jobId': '5873dcdbaec03000014x123',
            'digest': 'sha256:9aaece098841b13cdc64ea6756767357f5c9eb1ab10f67b9e67a90960b894053',
            'fullName': 'registry.local.wholetale.org/5c3cd7faa697bf0001ce6cc0-1547494547'
        },
        "public": False,
        "publishInfo": [
            {
                "pid": "urn:uuid:939e48ec-1107-45d9-baa7-05cef08e51cd",
                "uri": "https://dev.nceas.ucsb.edu/view/urn:uuid:8ec-1107-45d9-baa7-05cef08e51cd",
                "date": "2019-01-23T15:48:17.476000+00:00"
            }
        ],
        "title": "My Tale",
        "license": "CC0-1.0",
        "updated": "2019-01-23T15:48:17.476000+00:00"
    }
}
