#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import cherrypy
from urllib.parse import urlparse, urlunparse, urlencode
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import setResponseHeader, boundHandler
from .. import RESOLVERS
from .provider import DerivaProvider

from ..integration_utils import autologin, redirect_if_tale_exists
from ..entity import Entity


@access.public
@autoDescribeRoute(
    Description('Handle a Deriva import request and bounce it to the dashboard.')
    .param('url', 'The URL of the dataset. This can be the landing page, pid, or doi.',
           required=True)
    .param(
        "force",
        "If True, create a new Tale regardless of the fact it was previously imported.",
        required=False,
        dataType="boolean",
        default=False,
    )
)
@boundHandler()
def derivaDataImport(self, url, force):
    user = self.getCurrentUser()
    if user is None:
        args = {
            "url": url,
            "force": force,
        }
        autologin(args=args)

    entity = Entity(url, user)
    entity["base_url"] = ''
    entity = RESOLVERS.resolve(entity)

    data_map = DerivaProvider().lookup(entity)
    doi = data_map.doi or data_map.dataId
    if not force:
        redirect_if_tale_exists(user, self.getCurrentToken(), doi)

    query = dict()
    query['uri'] = url

    # TODO: Make base url a plugin setting, defaulting to dashboard.<domain>
    dashboard_url = os.environ.get('DASHBOARD_URL', 'https://dashboard.wholetale.org')
    location = urlunparse(
        urlparse(dashboard_url)._replace(
            path='/mine',
            query=urlencode(query))
    )
    setResponseHeader('Location', location)
    cherrypy.response.status = 303
