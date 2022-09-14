from urllib.parse import urlparse


class Verificator:
    key = None

    def __init__(self, resource_server=None, key=None, user=None, url=None):
        if not (resource_server or url):
            raise ValueError("Either 'resource_server' or 'url' must be provided")

        self.resource_server = resource_server or urlparse(url).netloc

        if not (key or user):
            raise ValueError("Either 'key' or 'user' must be provided")
        if key:
            self.key = key
        else:
            token = next(
                (
                    t
                    for t in user.get("otherTokens", [])
                    if t.get("resource_server") == self.resource_server
                ),
                None,
            )
            if token:
                self.key = token["access_token"]

    @property
    def headers(self):
        return {}

    def verify(self):
        raise NotImplementedError

    def preauth(self, user):
        pass
