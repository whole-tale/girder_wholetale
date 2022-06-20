from ..verificator import Verificator


class OpenICPSRVerificator(Verificator):
    @property
    def headers(self):
        return {}

    def verify(self):
        return
