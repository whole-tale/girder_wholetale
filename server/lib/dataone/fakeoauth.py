from urllib.parse import urlparse, urlunparse, quote

from girder.api.rest import getApiUrl
from girder.plugins.oauth.providers.base import ProviderBase


D1_ENV_DICT = {
    "prod": {
        "name": "Production",
        "base_url": "https://cn.dataone.org/cn",
        "host": "cn.dataone.org",
        "solr_base": "/cn/v1/query/solr/",
    },
    "stage": {
        "name": "Stage",
        "base_url": "https://cn-stage.test.dataone.org/cn",
        "host": "cn-stage.test.dataone.org",
        "solr_base": "/cn/v1/query/solr/",
    },
    "sandbox": {
        "name": "Sandbox",
        "base_url": "https://cn-sandbox.test.dataone.org/cn",
        "host": "cn-sandbox.test.dataone.org",
        "solr_base": "/cn/v1/query/solr/",
    },
    "dev": {
        "name": "Development",
        "base_url": "https://cn-dev.test.dataone.org/cn",
        "host": "cn-dev.test.dataone.org",
        "solr_base": "/cn/v1/query/solr/",
    },
}


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
