import jwt
from girder.exceptions import RestException


class DataONEVerificator:
    def __init__(self, resource_server, key):
        self.key = key
        self.resource_server = resource_server

    def verify(self):
        try:
            jwt.PyJWT().decode(
                self.key, options={"verify_signature": False, "verify_exp": True}
            )
        except jwt.exceptions.DecodeError:
            raise RestException(f"Invalid JWT Token: '{self.key}'")
