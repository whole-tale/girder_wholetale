#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder import events
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource

from ..constants import API_VERSION
from ..models.tale import Tale


class wholeTale(Resource):
    def __init__(self):
        super(wholeTale, self).__init__()
        self.resourceName = "wholetale"

        self.route("GET", (), self.get_wholetale_info)
        self.route("PUT", ("citations",), self.regenerate_citations)

    @access.public
    @autoDescribeRoute(Description("Return basic info about Whole Tale plugin"))
    def get_wholetale_info(self, params):
        return {"api_version": API_VERSION}

    @access.admin
    @autoDescribeRoute(
        Description("Regenerate dataSetCitation for all Tales").notes(
            "Hopefully DataCite will still love us, after we hammer their API"
        )
    )
    def regenerate_citations(self):
        user = self.getCurrentUser()
        for tale in Tale().find():
            eventParams = {"tale": tale, "user": user}
            events.trigger(eventName="tale.update_citation", info=eventParams)
