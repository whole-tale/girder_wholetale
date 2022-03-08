#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import cherrypy
from urllib.parse import urlparse, urlunparse, urlencode
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import boundHandler
from girder.exceptions import RestException

from . import DataONELocations, DataONENotATaleError
from .provider import DataOneImportProvider
from ..integration_utils import autologin, redirect_if_tale_exists
from ..entity import Entity


@access.public
@autoDescribeRoute(
    Description('Handle a DataONE import request and bounce it to the dashboard.')
    .param('uri', 'The URI of the dataset. This cna be the landing page, pid, or doi.',
           required=True)
    .param('title', 'The Dataverse database ID of a file the external tool has '
           'been launched on.', required=False)
    .param('environment', 'The environment that should be selected.', required=False)
    .param('api', 'An optional API endpoint that should be used to find the dataset.',
           required=False)
    .param('apiToken', 'The DataONE JWT of the user importing the data, '
           'if available.', required=False)
    .param(
        "force",
        "If True, create a new Tale regardless of the fact it was previously imported.",
        required=False,
        dataType="boolean",
        default=False,
    )
    .notes('apiToken is currently ignored.')
)
@boundHandler()
def dataoneDataImport(self, uri, title, environment, api, apiToken, force):
    user = self.getCurrentUser()
    if user is None:
        args = {
            "uri": uri,
            "title": title,
            "environment": environment,
            "api": api,
            "apiToken": apiToken,
            "force": force,
        }
        autologin(args=args)

    entity = Entity(uri, user)
    entity["base_url"] = api or DataONELocations.prod_cn
    data_map = DataOneImportProvider().lookup(entity)
    doi = data_map.doi or data_map.dataId
    if not force:
        redirect_if_tale_exists(user, self.getCurrentToken(), doi)

    dashboard_url = os.environ.get("DASHBOARD_URL", "https://dashboard.wholetale.org")

    try:
        tale = DataOneImportProvider().import_tale(data_map, user, force=force)
        location = urlunparse(
            urlparse(dashboard_url)._replace(
                path="/run/{}".format(tale["_id"]),
                query="token={}".format(self.getCurrentToken()["_id"]),
            )
        )
    except DataONENotATaleError:
        query = dict()
        query['uri'] = uri
        if title:
            query['name'] = title
        if environment:
            query['environment'] = environment
        if api:
            query['api'] = api

        location = urlunparse(
            urlparse(dashboard_url)._replace(path="/mine", query=urlencode(query))
        )
    except Exception as exc:
        raise RestException(
            f"Failed to import Tale. Server returned: '{str(exc)}'"
        )

    raise cherrypy.HTTPRedirect(location)
