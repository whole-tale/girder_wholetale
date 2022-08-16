import cherrypy
import os
from urllib.parse import urlparse, urlunparse, urlencode
from girder.plugins.oauth.rest import OAuth as OAuthResource


def autologin(args=None):
    args = {k: v for (k, v) in args.items() if v is not None}
    redirect = cherrypy.request.base + cherrypy.request.app.script_name
    redirect += cherrypy.request.path_info + "?"
    redirect += urlencode(args)
    redirect += "&token={girderToken}"

    oauth_providers = OAuthResource().listProviders(params={"redirect": redirect})
    raise cherrypy.HTTPRedirect(oauth_providers["Globus"])  # TODO: hardcoded var


def redirect_if_tale_exists(user, token, doi):
    from girder.plugins.wholetale.models.tale import Tale  # circular dep

    existing_tale_id = Tale().findOne(
        query={
            "creatorId": user["_id"],
            "relatedIdentifiers.identifier": {"$eq": doi},
            "relatedIdentifiers.relation": {"$in": ["IsDerivedFrom", "Cites"]},
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
