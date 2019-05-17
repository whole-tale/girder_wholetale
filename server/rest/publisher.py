#!/usr/bin/env python
# -*- coding: utf-8 -*-

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource
from girder.constants import SettingDefault
from girder.models.setting import Setting

from ..constants import PluginSettings


class Publisher(Resource):
    """
    Endpoint for publishers' metadata.
    """

    def __init__(self):
        super(Publisher, self).__init__()
        self.resourceName = 'publisher'
        self.route('GET', (), self.getPublishers)

    @access.user
    @autoDescribeRoute(
        Description('Get list of publishers.').param(
            'default',
            'Whether to return the default list of publishers.',
            required=False,
            dataType='boolean',
            default=False,
        )
    )
    def getPublishers(self, default):
        if default:
            return SettingDefault.defaults[PluginSettings.PUBLISHERS]
        return Setting().get(PluginSettings.PUBLISHERS)
