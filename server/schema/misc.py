#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder.api.docs import addModel

publishInfoSchema = {
    "title": "publishInfo",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "A schema representing publishing information",
    "type": "object",
    "properties": {
        "pid": {
            "type": ["string", "null"],
            "description": "A unique identifier assigned to this tale from a "
            "publishing source.",
        },
        "uri": {
            "type": ["string", "null"],
            "description": "A URI pointing to the location of the published Tale.",
        },
        "date": {
            "type": "string",
            "format": "date-time",
            "description": "Date Tale was published.",
        },
        "repository": {
            "type": "string",
            "description": "The repository where Tale was published.",
        },
        "repository_id": {
            "type": "string",
            "description": "The repository specific id assigned to the publication.",
        },
    },
    "required": ["pid", "uri", "date"],
}

publishInfoListSchema = {
    "title": "list of publishInfos",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "type": "array",
    "items": publishInfoSchema,
}

dataResourceSchema = {
    "title": "dataResource",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "A schema representing data elements used in WholeTale",
    "type": "object",
    "properties": {
        "type": {
            "type": "string",
            "enum": ["item", "folder"],
            "description": "Either a Girder item or a Girder folder",
        },
        "id": {"type": "string", "description": "Girder object id"},
    },
    "required": ["type", "id"],
}


dataMapSchema = {
    "title": "dataMap",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "A schema for a WholeTale Data Map",
    "type": "object",
    "properties": {
        "dataId": {
            "type": "string",
            "description": (
                "An internal unique identifier specific " "to a given repository."
            ),
        },
        "doi": {
            "type": ["string", "null"],
            "description": "A unique Digital Object Identifier",
        },
        "name": {"type": "string"},
        "repository": {
            "type": "string",
            "description": "A name of the repository holding the data.",
        },
        "size": {
            "type": "integer",
            "minimum": -1,
            "description": "The total size of the dataset in bytes.",
        },
    },
    "required": ["dataId", "repository"],
}

dataMapListSchema = {
    "title": "list of dataMaps",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "type": "array",
    "items": dataMapSchema,
}

dataSetItemSchema = {
    "title": "dataSetItem",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "A schema representing data elements used in DMS dataSets",
    "type": "object",
    "properties": {
        "_modelType": {
            "type": "string",
            "enum": ["item", "folder"],
            "description": "Either a Girder item or a Girder folder",
        },
        "itemId": {
            "type": "string",
            "description": "ID of a Girder item or a Girder folder",
        },
        "mountPath": {
            "type": "string",
            "description": "An absolute path where the item/folder are mounted in the EFS",
        },
    },
    "required": ["itemId", "mountPath"],
}

dataSetSchema = {
    "title": "A list of resources with a corresponding mount points in the ESF",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "type": "array",
    "items": dataSetItemSchema,
}

tagsSchema = {
    "title": "tags",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "A schema for image tags",
    "type": "array",
    "items": {"type": "string"},
}

containerConfigSchema = {
    "title": "containerConfig",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "A subset of docker runtime configuration used for Tales",
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Command to run when the container starts",
        },
        "cpuShares": {"type": "string"},
        "environment": {
            "type": "array",
            "description": "List of environment variables passed to a container",
            "items": {
                "type": "string",
                "description": "Environment variable, in the form KEY=val",
            },
        },
        "memLimit": {"type": "string"},
        "port": {
            "type": "integer",
            "description": (
                "The exposed internal port that is going to be "
                "accessbile through HTTP(S)"
            ),
        },
        "user": {
            "type": "string",
            "description": "Username used inside the running container",
        },
        "targetMount": {
            "type": "string",
            "description": ("Path where the Whole Tale filesystem " "will be mounted"),
        },
        "urlPath": {
            "type": "string",
            "description": (
                "Subpath appended to the randomly generated " "container URL"
            ),
        },
    },
}

containerInfoSchema = {
    "title": "containerInfo",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "A subset of docker info parameters used by Tales",
    "type": "object",
    "properties": {
        "created": {"type": "string", "format": "date-time"},
        "name": {"type": "string"},
        "imageId": {
            "type": "string",
            "description": (
                "ID of the successfully built image "
                "that was used to run this instance."
            ),
        },
        "digest": {
            "type": "string",
            "description": (
                "Checksum of the successfully built image "
                "that was used to run this instance."
            ),
        },
        "nodeId": {"type": "string"},
        "mountPoint": {"type": "string"},
        "volumeName": {"type": "string"},
        "urlPath": {"type": "string"},
    },
    "required": ["name", "mountPoint", "nodeId", "volumeName"],
}

imageInfoSchema = {
    "title": "imageInfo",
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "Attributes describing a Tale image",
    "type": "object",
    "properties": {
        "created": {"type": "string", "format": "date-time"},
        "jobId": {"type": "string"},
        "digest": {"type": "string"},
        "fullName": {"type": "string"},
    },
}

addModel("containerConfig", containerConfigSchema)
addModel("dataSet", dataSetSchema)

external_auth_providers_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "type": "array",
    "items": [
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "logo": {"type": "string"},
                "fullName": {"type": "string"},
                "state": {"type": "string"},
                "tags": {"type": "array", "items": [{"type": ["string", "null"]}]},
                "type": {"type": "string"},
                "url": {"type": ["string", "null"]},
                "docs_href": {"type": "string"},
                "targets": {"type": "array", "items": [{"type": ["string", "null"]}]},
            },
            "required": ["name", "logo", "fullName", "tags", "type"],
        }
    ],
}

external_apikey_groups_schema = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "type": "array",
    "items": [
        {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "targets": {"type": "array", "items": [{"type": ["string", "null"]}]},
            },
            "required": ["name", "targets"],
        }
    ],
}

repository_to_provider_schema = {
    "definitions": {},
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "array",
    "title": "The Repositories to Auth Providers mapping schema",
    "items": {
        "$id": "#/items",
        "type": "object",
        "title": "The Repository to Auth Provider Schema",
        "required": ["repository", "auth_provider"],
        "properties": {
            "repository": {
                "$id": "#/items/properties/repository",
                "type": "string",
                "title": "The address of the repository",
                "default": "",
                "examples": ["sandbox.zenodo.org"],
                "pattern": "^(.*)$",
            },
            "auth_provider": {
                "$id": "#/items/properties/auth_provider",
                "type": "string",
                "title": "The name of the auth provider",
                "default": "",
                "examples": ["zenodo"],
                "pattern": "^(.*)$",
            },
        },
    },
}
