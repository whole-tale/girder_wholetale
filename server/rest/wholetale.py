#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder import events
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource
from girder.models.setting import Setting
from girder.models.collection import Collection
from girder.models.folder import Folder

from ..constants import API_VERSION, PluginSettings
from ..models.tale import Tale
import os


class wholeTale(Resource):
    def __init__(self):
        super(wholeTale, self).__init__()
        self.resourceName = 'wholetale'

        self.route('GET', (), self.get_wholetale_info)
        self.route('PUT', ('citations',), self.regenerate_citations)
        self.route('GET', ('settings',), self.get_settings)
        self.route('GET', ('assets',), self.get_assets)

    @access.public
    @autoDescribeRoute(Description('Return basic info about Whole Tale plugin'))
    def get_wholetale_info(self, params):
        return {'api_version': API_VERSION}

    @access.admin
    @autoDescribeRoute(
        Description('Regenerate dataSetCitation for all Tales').notes(
            'Hopefully DataCite will still love us, after we hammer their API'
        )
    )
    def regenerate_citations(self):
        user = self.getCurrentUser()
        for tale in Tale().find():
            eventParams = {'tale': tale, 'user': user}
            events.trigger(eventName='tale.update_citation', info=eventParams)

    @access.public
    @autoDescribeRoute(
        Description('Return Whole Tale plugin settings.')
    )
    def get_settings(self):
        settings = Setting()
        #  ${getApiRoot()}${resp['wholetale.logo']}/download?contentDisposition=inline
        if (settings.get(PluginSettings.LOGO)):
            logoId = str(settings.get(PluginSettings.LOGO))
            logoUrl = f"file/{logoId}/download?contentDisposition=inline"
        else:
            logoUrl = ""

        return {
            PluginSettings.ABOUT_HREF: settings.get(PluginSettings.ABOUT_HREF),
            PluginSettings.CONTACT_HREF: settings.get(PluginSettings.CONTACT_HREF),
            PluginSettings.BUG_HREF: settings.get(PluginSettings.BUG_HREF),
            PluginSettings.WEBSITE_URL: settings.get(PluginSettings.WEBSITE_URL),
            PluginSettings.DASHBOARD_LINK_TITLE: settings.get(PluginSettings.DASHBOARD_LINK_TITLE),
            PluginSettings.CATALOG_LINK_TITLE: settings.get(PluginSettings.CATALOG_LINK_TITLE),
            PluginSettings.ENABLE_DATA_CATALOG: settings.get(PluginSettings.ENABLE_DATA_CATALOG),
            PluginSettings.DASHBOARD_TITLE: settings.get(PluginSettings.DASHBOARD_TITLE),
            PluginSettings.HEADER_COLOR: settings.get(PluginSettings.HEADER_COLOR),
            PluginSettings.DASHBOARD_URL: os.environ.get('DASHBOARD_URL',
                                                         'https://dashboard.wholetale.org'),
            PluginSettings.LOGO: logoUrl,
        }

    @access.admin
    @autoDescribeRoute(
        Description('Return the folder IDs for uploaded asset content.')
    )
    def get_assets(self):
        return {
            PluginSettings.LOGO: self._get_assets_folder('Logo')['_id'],
        }

    def _get_assets_folder(self, folderName):
        """
        Modeled after Homepage plugin.

        Gets or creates a public folder in a private assets collection.

        :param folderName: The name of the folder to get or create.
        :return: The new folder document.
        """
        collection = Collection().createCollection(
            'WholeTale Assets',
            public=False,
            reuseExisting=True
        )
        folder = Folder().createFolder(
            collection,
            folderName,
            parentType='collection',
            public=True,
            reuseExisting=True
        )
        return folder
