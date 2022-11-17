#!/usr/bin/env python
# -*- coding: utf-8 -*-

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import boundHandler, filtermodel
from girder.constants import TokenScope
from girder.utility.model_importer import ModelImporter


@access.user(scope=TokenScope.DATA_READ)
@filtermodel(model="folder")
@autoDescribeRoute(
    Description(
        "List all folders containing references to an external data"
    ).errorResponse("Write access denied for parent collection.", 403)
)
@boundHandler()
def listImportedData(self, params):
    q = {"meta.provider": {"$exists": 1}}
    return list(ModelImporter.model("folder").find(query=q))
