#!/usr/bin/env python
# -*- coding: utf-8 -*-
import cherrypy
import os
from urllib.parse import urlparse, urlunparse, urlencode

from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import boundHandler, RestException

from . import ZenodoNotATaleError
from .. import IMPORT_PROVIDERS
from ..data_map import DataMap
from ..integration_utils import autologin


@access.public
@autoDescribeRoute(
    Description("Convert external tools request and bounce it to the dashboard.")
    .param("doi", "The DOI of the dataset.", required=False)
    .param("record_id", "ID", required=False)
    .param("resource_server", "resource server", required=False)
    .param("environment", "The environment that should be selected.", required=False)
    .param(
        "force",
        "If True, create a new Tale regardless of the fact it was previously imported.",
        required=False,
        dataType="boolean",
        default=False,
    )
)
@boundHandler()
def zenodoDataImport(self, doi, record_id, resource_server, environment, force):
    """Fetch and unpack a Zenodo record"""
    if not (doi or record_id):
        raise RestException("You need to provide either 'doi' or 'record_id'")

    if not resource_server:
        try:
            resource_server = urlparse(cherrypy.request.headers["Referer"]).netloc
        except KeyError:
            raise RestException("resource_server not set")

    # NOTE: DOI takes precedence over 'record_id' in case both were specified
    if doi:
        # TODO: don't rely on how DOI looks like, I'm not sure if it can't change
        # in the future
        record_id = int(doi.split("zenodo.")[-1])

    user = self.getCurrentUser()
    if user is None:
        args = {
            "record_id": record_id, "resource_server": resource_server,
            "environment": environment, "force": force
        }
        autologin(args=args)

    # TODO: Make base url a plugin setting, defaulting to dashboard.<domain>
    dashboard_url = os.environ.get("DASHBOARD_URL", "https://dashboard.wholetale.org")
    url = "https://{}/record/{}".format(resource_server, record_id)
    provider = IMPORT_PROVIDERS.providerMap["Zenodo"]
    try:
        data_map = DataMap(url, -1)  # mock DatMmap to pass url
        tale = provider.import_tale(data_map, user, force=force)
        location = urlunparse(
            urlparse(dashboard_url)._replace(
                path="/run/{}".format(tale["_id"]),
                query="token={}".format(self.getCurrentToken()["_id"]),
            )
        )
    except ZenodoNotATaleError as exc:
        query = {"uri": url, "asTale": True, "name": exc.record["metadata"]["title"]}
        location = urlunparse(
            urlparse(dashboard_url)._replace(path="/mine", query=urlencode(query))
        )
    except Exception as exc:
        raise RestException(
            f"Failed to import Tale. Server returned: '{str(exc)}'"
        )

    raise cherrypy.HTTPRedirect(location)
