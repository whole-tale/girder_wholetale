import jwt
from girder.exceptions import RestException
from ..verificator import Verificator


class DataONEVerificator(Verificator):
    def __init__(self, resource_server=None, key=None, url=None, user=None):
        self.key = key
        self.resource_server = resource_server

    @property
    def headers(self):
        if self.key:
            return {"Authorization": f"Bearer {self.key}"}
        return {}

    def verify(self):
        try:
            jwt.PyJWT().decode(
                self.key, options={"verify_signature": False, "verify_exp": True}
            )
        except jwt.exceptions.DecodeError:
            raise RestException(f"Invalid JWT Token: '{self.key}'")
