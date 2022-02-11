from girder.models.setting import Setting
from ...constants import PluginSettings, DEFAULT_DERIVA_SCOPE
from ..verificator import Verificator

from girder.plugins.oauth.providers.globus import Globus


Globus.addScopes([DEFAULT_DERIVA_SCOPE])


class DerivaVerificator(Verificator):
    def __init__(self, resource_server=None, key=None, user=None, url=None):
        super().__init__(resource_server, key, user, url)
        self.user = user

    @property
    def headers(self):
        scope_map = Setting().get(PluginSettings.DERIVA_SCOPES)
        if self.resource_server in scope_map:
            scope = scope_map[self.resource_server]
            if 'otherTokens' in self.user:
                for token in self.user['otherTokens']:
                    if token['scope'] == scope:
                        return {'Authorization': 'Bearer ' + token['access_token']}
        return {}
