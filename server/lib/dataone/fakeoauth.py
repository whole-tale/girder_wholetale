from urllib.parse import quote, urlparse, urlunparse

from d1_common.env import D1_ENV_DICT
from girder.api.rest import getApiUrl
from girder.plugins.oauth.providers.base import ProviderBase


class FakeDataONE(ProviderBase):
    @classmethod
    def get_cn(cls):
        key = cls.__name__.lower().replace("dataone", "")
        return D1_ENV_DICT[key]["base_url"]

    @classmethod
    def getUrl(cls, state):
        _, _, redirect = state.partition(".")

        url = "/".join(
            (getApiUrl(), "account", cls.getProviderName(external=False), "callback")
        )
        url += "?state={}&code=dataone".format(quote(state))
        auth_url = urlparse(cls.get_cn())._replace(
            path="/portal/oauth", query="action=start&target={}".format(quote(url))
        )
        return urlunparse(auth_url)

    def getToken(self, code):
        return {
            "provider": self.getProviderName(external=False),
            "resource_server": urlparse(self.get_cn()).netloc,
            "token_type": "dataone-pre",
            "access_token": "",
        }

    def getClientIdSetting(self):
        return "fake_client_id"

    def getClientSecretSetting(self):
        return "fake_secret_id"

    @classmethod
    def getTokenUrl(cls):
        return urlunparse(urlparse(cls.get_cn())._replace(path="/portal/token"))
