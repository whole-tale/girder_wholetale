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
        "status": {
            "type": "integer",
            "enum": [0, 1, 2],
            "description": "Status of the tale import (Preparing, Ready, Error)"
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
        "imageInfo": {
            "digest": "registry.local.wholetale.org/608/1619806964@sha256:a",
            "imageId": "5c4886279759c200017b22a3",
            "jobId": "608c4d99e909e4f4e2c6973a",
            "last_build": 1619806964,
            "repo2docker_version": "wholetale/repo2docker_wholetale:v1.0rc1",
            "status": 3
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
