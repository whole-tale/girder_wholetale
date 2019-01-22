#!/usr/bin/env python
# -*- coding: utf-8 -*-

from girder import events


API_VERSION = '2.1'
CATALOG_NAME = 'WholeTale Catalog'
WORKSPACE_NAME = 'WholeTale Workspaces'
DATADIRS_NAME = 'WholeTale Data Mountpoints'
SCRIPTDIRS_NAME = 'WholeTale Narrative'


class HarvesterType:
    """
    All possible data harverster implementation types.
    """
    DATAONE = 0


class PluginSettings:
    INSTANCE_CAP = 'wholetale.instance_cap'
    DATAVERSE_URL = 'wholetale.dataverse_url'
    DATAVERSE_EXTRA_HOSTS = 'wholetale.dataverse_extra_hosts'


class SettingDefault:
    defaults = {
        PluginSettings.INSTANCE_CAP: 2,
        PluginSettings.DATAVERSE_URL:
            'https://services.dataverse.harvard.edu/miniverse/map/installations-json',
        PluginSettings.DATAVERSE_EXTRA_HOSTS: []
    }


# Constants representing the setting keys for this plugin
class InstanceStatus(object):
    LAUNCHING = 0
    RUNNING = 1
    ERROR = 2
    DELETING = 3

    @staticmethod
    def isValid(status):
        event = events.trigger('instance.status.validate', info=status)

        if event.defaultPrevented and len(event.responses):
            return event.responses[-1]

        return status in (InstanceStatus.RUNNING, InstanceStatus.ERROR,
                          InstanceStatus.LAUNCHING, InstanceStatus.DELETING)


class ImageStatus(object):
    INVALID = 0
    UNAVAILABLE = 1
    BUILDING = 2
    AVAILABLE = 3

    @staticmethod
    def isValid(status):
        event = events.trigger('wholetale.image.status.validate', info=status)

        if event.defaultPrevented and len(event.responses):
            return event.responses[-1]

        return status in (ImageStatus.INVALID, ImageStatus.UNAVAILABLE,
                          ImageStatus.BUILDING, ImageStatus.AVAILABLE)
