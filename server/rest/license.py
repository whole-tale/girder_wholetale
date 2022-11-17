#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder.api import access
from girder.api.describe import Description, describeRoute
from girder.api.rest import Resource

from ..lib.license import WholeTaleLicense


class License(Resource):
    def __init__(self):
        super(License, self).__init__()
        self.resourceName = "license"
        self.route("GET", (), self.get_licenses)

    @access.public
    @describeRoute(
        Description(
            "Returns all of the licenses that can be assigned to a Tale."
        ).notes(
            "This endpoint returns a list of all of the Whole Tale supported licenses"
        )
    )
    def get_licenses(self, params):
        return WholeTaleLicense().supported_licenses()
