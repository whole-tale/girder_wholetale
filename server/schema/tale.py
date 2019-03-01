#!/usr/bin/env python
# -*- coding: utf-8 -*-

from .misc import containerConfigSchema, dataSetSchema, imageInfoSchema

taleModel = {
    "definitions": {
        "containerConfig": containerConfigSchema,
        "dataSet": dataSetSchema,
        'imageInfo': imageInfoSchema
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
        "folderId": {
            "type": "string",
            "description": "ID of a folder containing copy of tale['dataSet']"
        },
        "narrativeId": {
            "type": "string",
            "description": "ID of a folder containing copy of tale['narrative']"
        },
        "dataSet": {
            "$ref": "#/definitions/dataSet"
        },
        "workspaceId": {
            "type": "string",
            "description": "ID of a folder containing Tale's workspace"
        },
        "narrative": {
            "type": "array",
            "items": {
                'type': 'string',
                'description': "Girder Item id"
            },
            "description": "List of Girder Items containing Tale's narrative"
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
        "published": {
            "type": "boolean",
            "default": False,
            "description": "If set to true the Tale cannot be deleted or made unpublished."
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
            "type": "string",
            "description": (
                "BEWARE: it's a string for now, but in the future it should "
                "be a map of Author/User entities"
            )
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
        "doi": {
            "type": ["string", "null"],
            "description": "A unique identifier assigned to this tale from a "
                           "publishing source."
        },
        "publishedURI": {
            "type": ["string", "null"],
            "description": "A URI pointing to the location of the published "
                           "Tale."
        }
    },
    'example': {
        "_accessLevel": 2,
        "_id": "5c4887409759c200017b2310",
        "_modelType": "tale",
        "authors": "Kacper Kowalik",
        "category": "science",
        "config": {},
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
        "folderId": "5c4887409759c200017b2316",
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
        "narrative": [],
        "narrativeId": "5c4887409759c200017b2319",
        "public": False,
        "published": False,
        "publishedURI": "https://dev.nceas.ucsb.edu/view/urn:uuid:939e48ec-1107-45d9"
                        "-baa7-05cef08e51cd",
        "title": "My Tale",
        "updated": "2019-01-23T15:48:17.476000+00:00"
    }
}
