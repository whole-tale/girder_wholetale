from girder.plugins.oauth.providers import addProvider
from .fakeoauth import FakeDataONE


class DataONELocations:
    """
    An enumeration that describes the different DataONE
    endpoints.
    """

    # Production coordinating node
    prod_cn = "https://cn.dataone.org/cn/v2"
    # Development member node
    dev_mn = "https://dev.nceas.ucsb.edu/knb/d1/mn/v2"
    # Development coordinating node
    dev_cn = "https://cn-stage.test.dataone.org/cn/v2"


class DataONENotATaleError(Exception):
    """Exception raised if DataONE record is not a Tale.

    Attributes:
        pid - identifier of the record.
        base_url - CN url used to query the record.

    """

    def __init__(
        self, pid, base_url, message="DataONE package ({}) is not a Tale (CN: {})"
    ):
        self.pid = pid
        self.base_url = base_url
        self.message = message.format(self.pid, self.base_url)
        super().__init__(self.message)


addProvider(type("DataONEDev", (FakeDataONE,), {}))
addProvider(type("DataONEProd", (FakeDataONE,), {}))
addProvider(type("DataONEStage", (FakeDataONE,), {}))
