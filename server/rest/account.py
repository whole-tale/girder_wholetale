import cherrypy
import datetime
from urllib.parse import urlparse

from girder.exceptions import RestException, ValidationException
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, getApiUrl
from girder.models.setting import Setting
from girder.models.token import Token
from girder.models.user import User
from girder.plugins.oauth import constants as OAuthConstants
from girder.plugins.oauth import providers

from ..constants import PluginSettings
from ..lib import Verificators


class Account(Resource):
    def __init__(self):
        super(Account, self).__init__()
        self.resourceName = "account"

        self.route("GET", (), self.listAccounts)
        self.route("GET", (":provider", "revoke"), self.revokeAccount)
        self.route("GET", (":provider", "callback"), self.callbackAccount)
        self.route("GET", (":provider", "targets"), self.listTargetsForAccount)
        self.route("POST", (":provider", "key"), self.addAccountKey)

    @staticmethod
    def supported_providers():
        """Converts list of providers into a providerName -> provider."""
        return {
            _["name"]: _ for _ in Setting().get(PluginSettings.EXTERNAL_AUTH_PROVIDERS)
        }

    @staticmethod
    def supported_apikey_flavors():
        """Converts list of apikey targets into a provider -> possible targets."""
        return {
            _["name"]: _["targets"]
            for _ in Setting().get(PluginSettings.EXTERNAL_APIKEY_GROUPS)
        }

    @staticmethod
    def _createStateToken(redirect, user=None):
        """
        Creates CSRF token that is user specific.

        This allows us to recover user, once the callback is called.
        """
        csrfToken = Token().createToken(user=user, days=0.25)

        # The delimiter is arbitrary, but a dot doesn't need to be URL-encoded
        state = "%s.%s" % (csrfToken["_id"], redirect)
        return state

    @staticmethod
    def _validateCsrfToken(state):
        """
        Tests the CSRF token value in the cookie to authenticate the user as
        the originator of the account integration. Raises a RestException if the token
        is invalid.
        """
        csrfTokenId, _, redirect = state.partition(".")

        token = Token().load(csrfTokenId, objectId=False, force=True)
        if token is None:
            raise RestException('Invalid CSRF token (state="%s").' % state, code=403)

        try:
            user = User().load(token["userId"], force=True, exc=True)
        except (KeyError, ValidationException):
            raise RestException('No valid user (state="%s").' % state)

        Token().remove(token)

        if token["expires"] < datetime.datetime.utcnow():
            raise RestException('Expired CSRF token (state="%s").' % state, code=403)

        if not redirect:
            raise RestException('No redirect location (state="%s").' % state)

        return user, redirect

    @access.user
    @autoDescribeRoute(
        Description(
            "Get the list of enabled external account providers and their URLs."
        ).param(
            "redirect",
            "Where the user should be redirected upon completion"
            " of the OAuth2 flow.",
        )
    )
    def listAccounts(self, redirect):
        user = self.getCurrentUser()

        # OAuth providers ids with configured credentials that can be used for an external account
        enabled_providers_ids = set(
            Setting().get(OAuthConstants.PluginSettings.PROVIDERS_ENABLED)
        )

        # External account providers ids that we support, can be defined in plugin settings
        supported_providers_ids = set(self.supported_providers().keys())

        # Some special handling for DataONE, since we haven't done that for a while.
        # DataONE OAuth providers are "fake" </SHOCK> They don't really use OAuth, we derive it
        # from oauth.BaseProvider but only mock a limited set of methods that we need, e.g. to
        # get the name or the url for a coordinating node.
        dataone_providers_ids = {
            provider_name
            for provider_name, provider in self.supported_providers().items()
            if provider["type"] == "dataone"
        }

        # Supported providers that happen to be OAuth providers, need CSRF token for OAuth flow
        state = None
        if enabled_providers_ids & supported_providers_ids | dataone_providers_ids:
            state = self._createStateToken(redirect, user=user)

        # All supported *AND* enabled providers will be mapped by 'enabled_providers'
        # Note: apikey providers are always enabled.
        enabled_providers = {}
        for provider_name, provider in self.supported_providers().items():
            if provider["type"] in ("apikey", "dataone") or (
                provider["type"] == "bearer"
                and provider_name  # noqa
                in enabled_providers_ids & supported_providers_ids  # noqa
            ):
                enabled_providers[provider_name] = provider

        # We need to check which tokens user already has and modify the state of relevant
        # providers in 'enabled_providers' mapping. Two things happend here:
        #  1. State is modified to 'authorized' if user already has a token (for oauth and dataone)
        #     or target is appended to list of authorized apikey providers of a given type.
        #  2. An "action" url for a given provider is constructed, which is basically:
        #     * "how to authorize" if state is "unauthorized",
        #     * "how to revoke token" if state is "authorized".
        # NOTE: for Dataone, revoke url is bogus. There's no way to truly revoke it via their API.
        user_tokens = user.get("otherTokens", [])
        for user_token in user_tokens:
            try:
                enabled_provider = enabled_providers[user_token["provider"]]
                if user_token["token_type"].lower() in ("bearer", "dataone"):
                    provider = providers.idMap[user_token["provider"]]
                    enabled_provider["url"] = "/".join(
                        (getApiUrl(), "account", user_token["provider"], "revoke")
                    )
                    enabled_provider["state"] = "authorized"
                elif user_token["token_type"].lower() == "dataone-pre":
                    provider = providers.idMap[user_token["provider"]]
                    enabled_provider["state"] = "preauthorized"
                    enabled_provider["url"] = provider.getTokenUrl()
                else:
                    enabled_provider["targets"].append(
                        {
                            "resource_server": user_token["resource_server"],
                            "url": "/".join(
                                (
                                    getApiUrl(),
                                    "account",
                                    user_token["provider"],
                                    "revoke",
                                    "?resource_server={}".format(
                                        user_token["resource_server"]
                                    ),
                                )
                            ),
                        }
                    )
            except KeyError:
                pass

        for provider_name in (
            enabled_providers_ids & supported_providers_ids | dataone_providers_ids
        ):
            if not enabled_providers[provider_name]["url"]:
                provider = providers.idMap[provider_name]
                # NOTE: for dataone it's "/oauth?", so this should be noop
                enabled_providers[provider_name]["url"] = provider.getUrl(
                    state
                ).replace("%2Foauth%2F", "%2Faccount%2F")

        return list(enabled_providers.values())

    @access.user
    @autoDescribeRoute(
        Description("Revoke authorization for a given provider.")
        .param("provider", "The provider name.", paramType="path")
        .param("resource_server", "resource_server", required=False)
    )
    def revokeAccount(self, provider, resource_server):
        """Revoke account authorization.

        In case of OAuth use the proper flow (usually calling /revoke with refreshToken).
        In case of API Key, just drop it from the user model.
        In case of DataONE, hahaha you thought that's possible via API?! You silly goose!
        (User would have to clear cookies from CN or login to ORCID and deauthorize there)
        """
        try:
            provider_obj = self.supported_providers()[provider]
        except KeyError:
            raise RestException(
                "Invalid account provider (provider={})".format(provider)
            )

        if provider_obj["type"] == "apikey" and not resource_server:
            raise RestException(
                "Missing resource_server for apikey provider (provider={})".format(
                    provider
                )
            )

        user = self.getCurrentUser()
        user_tokens = user.get("otherTokens", [])

        # In case of APIKey, it's resource_server that's unique, not provider id
        if resource_server:
            key = "resource_server"
            target_value = resource_server
        else:
            key = "provider"
            target_value = provider

        token = next((_ for _ in user_tokens if _.get(key) == target_value), None)
        if token:
            user_tokens.remove(token)
            user["otherTokens"] = user_tokens
            User().save(user)

            if provider_obj["type"] == "bearer":
                oauth_provider = providers.idMap[provider]
                # NOTE: only ORCID has that implemented
                oauth_provider("").revokeToken(token)

    @access.public
    @autoDescribeRoute(
        Description("Callback called by OAuth providers.")
        .param("provider", "The provider name.", paramType="path")
        .param("state", "Opaque state string.", required=False)
        .param("code", "Authorization code from provider.", required=False)
        .param("error", "Error message from provider.", required=False),
        hide=True,
    )
    def callbackAccount(self, provider, state, code, error):
        """Classical OAuth callback endpoint that parses incoming token.

        The main difference between this callback and /oauth/:provider/callback
        is that we store the incoming bearer token into User model, instead of using it
        to actually login to Girder.
        Note: We conveniently hid the userId in the OAuth state.
        """
        if error is not None:
            raise RestException("Provider returned error: '%s'." % error, code=502)

        providerName = provider
        provider = providers.idMap.get(providerName)
        if not provider:
            raise RestException('Unknown provider "%s".' % providerName)

        self.requireParams({"state": state, "code": code})

        user, redirect = self._validateCsrfToken(state)
        providerObj = provider(cherrypy.url())
        new_token = providerObj.getToken(code)

        if "resource_server" not in new_token:
            new_token["resource_server"] = providerObj.getProviderName(external=False)
        new_token["provider"] = providerObj.getProviderName(external=False)

        user_tokens = user.get("otherTokens", [])
        for i, user_token in enumerate(user_tokens):
            if user_token["resource_server"] == new_token["resource_server"]:
                user_tokens[i] = new_token  # update token if found.
                break
        else:
            user_tokens.append(new_token)  # not found, append

        user["otherTokens"] = user_tokens
        user = User().save(user)
        self.sendAuthTokenCookie(user)
        raise cherrypy.HTTPRedirect(redirect)

    @access.user
    @autoDescribeRoute(
        Description("List possible resource servers for a Provider.").param(
            "provider", "The provider name.", paramType="path"
        )
    )
    def listTargetsForAccount(self, provider):
        try:
            targets = self.supported_apikey_flavors()[provider]
        except KeyError:
            raise RestException('Unknown provider "%s".' % provider)

        user = self.getCurrentUser()
        user_tokens = user.get("otherTokens", [])
        for user_token in user_tokens:
            if user_token.get("provider") != provider:
                continue
            try:
                targets.remove(user_token["resource_server"])
            except ValueError:
                pass
        return targets

    @access.user
    @autoDescribeRoute(
        Description("Add apikey for a given Provider.")
        .param("provider", "The provider name.", paramType="path")
        .param("resource_server", "resource_server", required=True)
        .param("key", "API Key for resource server", required=True)
        .param(
            "key_type",
            "Type of the API key.",
            required=False,
            default="apikey",
            enum=["apikey", "dataone"],
        )
    )
    def addAccountKey(self, provider, resource_server, key, key_type):
        user = self.getCurrentUser()

        try:
            if key_type == "apikey":
                key_provider = self.supported_apikey_flavors()[provider]
                if resource_server not in key_provider:
                    raise RestException(
                        'Unsupported resource server "%s".' % resource_server
                    )
            else:
                key_provider = providers.idMap[provider]
                resource_server = urlparse(key_provider.get_cn()).netloc

        except KeyError:
            raise RestException('Unknown provider "%s".' % provider)

        Verificators[provider](resource_server=resource_server, key=key).verify()

        user_tokens = user.get("otherTokens", [])
        for i, user_token in enumerate(user_tokens):
            if user_token["resource_server"] == resource_server:
                user_tokens[i].update(  # update token if found.
                    {"access_token": key, "token_type": key_type}
                )
                break
        else:
            user_tokens.append(
                {
                    "resource_server": resource_server,
                    "access_token": key,
                    "token_type": key_type,
                    "provider": provider,
                }
            )  # not found, append

        user["otherTokens"] = user_tokens
        User().save(user)
