from urllib.parse import urlparse, urlunparse, quote
from d1_common.env import D1_ENV_DICT

from girder.api.rest import getApiUrl
from girder.plugins.oauth.providers.base import ProviderBase

# Because, why would they keep up to date list of CNs and deployments?
D1_ENV_DICT["stage"] = dict(base_url="https://cn-stage.test.dataone.org/cn")


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
