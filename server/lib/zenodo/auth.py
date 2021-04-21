import requests
from girder.exceptions import RestException
from ..verificator import Verificator


class ZenodoVerificator(Verificator):
    @property
    def headers(self):
        if self.key:
            return {"Authorization": f"Bearer {self.key}"}
        return {}

    def verify(self):
        headers = self.headers.copy()
        headers["Content-Type"] = "application/json"
        deposition_url = f"https://{self.resource_server}/api/deposit/depositions"
        try:
            r = requests.post(deposition_url, data="{}", headers=headers)
            r.raise_for_status()
            r = requests.delete(
                deposition_url + f"/{r.json()['id']}", headers=headers
            )
            r.raise_for_status()
        except requests.exceptions.HTTPError:
            raise RestException(
                "Key '{}' is not valid for '{}'".format(self.key, self.resource_server)
            )
