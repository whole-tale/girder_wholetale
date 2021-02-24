import cherrypy
import os
from urllib.parse import urlparse, urlunparse, urlencode
from girder.plugins.oauth.rest import OAuth as OAuthResource

from ..models.tale import Tale


def autologin(args=None):
    args = {k: v for (k, v) in args.items() if v is not None}
    redirect = cherrypy.request.base + cherrypy.request.app.script_name
    redirect += cherrypy.request.path_info + "?"
    redirect += urlencode(args)
    redirect += "&token={girderToken}"

    oauth_providers = OAuthResource().listProviders(params={"redirect": redirect})
    raise cherrypy.HTTPRedirect(oauth_providers["Globus"])  # TODO: hardcoded var


def redirect_if_tale_exists(token, doi):

    # Check to see if the incoming request is for a Tale that has been published
    existing_tale_id = Tale().findOne(
        query={
            "publishInfo.pid": {"$eq": doi},
        },
        fields={"_id"},
    )

    if existing_tale_id:
        # TODO: Make base url a plugin setting, defaulting to dashboard.<domain>
        dashboard_url = os.environ.get(
            "DASHBOARD_URL", "https://dashboard.wholetale.org"
        )
        location = urlunparse(
            urlparse(dashboard_url)._replace(
                path="/run/{}".format(existing_tale_id["_id"]),
                query="token={}".format(token["_id"]),
            )
        )
        raise cherrypy.HTTPRedirect(location)
