#!/usr/bin/env python
# -*- coding: utf-8 -*-

from girder import events


API_VERSION = '2.0'
CATALOG_NAME = 'WholeTale Catalog'
WORKSPACE_NAME = 'WholeTale Workspaces'
DATADIRS_NAME = 'WholeTale Data Mountpoints'


class HarvesterType:
    """
    All possible data harverster implementation types.
    """
    DATAONE = 0


class PluginSettings:
    TMPNB_URL = 'wholetale.tmpnb_url'
    HUB_PRIV_KEY = 'wholetale.priv_key'
    HUB_PUB_KEY = 'wholetale.pub_key'


# Constants representing the setting keys for this plugin
class InstanceStatus(object):
    LAUNCHING = 0
    RUNNING = 1
    ERROR = 2

    @staticmethod
    def isValid(status):
        event = events.trigger('instance.status.validate', info=status)

        if event.defaultPrevented and len(event.responses):
            return event.responses[-1]

        return status in (InstanceStatus.RUNNING, InstanceStatus.ERROR,
                          InstanceStatus.LAUNCHING)


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


class DataONELocations:
    """
    An enumeration that describes the different DataONE
    endpoints.
    """
    # Production coordinating node
    prod_cn = 'https://cn.dataone.org/cn/v2'
    # Development member node
    dev_mn = 'https://dev.nceas.ucsb.edu/knb/d1/mn/v2'
    # Development coordinating node
    dev_cn = 'https://cn-stage-2.test.dataone.org/cn/v2'


class ExtraFileNames:
    """
    When creating data packages we'll have to create additional files, such as
     the zipped recipe, the tale.yml file, the metadata document, and possibly
      more. Keep their names store here so that they can easily be referenced and
      changed in a single place.
    """
    # Name for the tale config file
    tale_config = 'tale.yml'
