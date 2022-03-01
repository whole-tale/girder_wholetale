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


addProvider(type("DataONEDev", (FakeDataONE,), {}))
addProvider(type("DataONEProd", (FakeDataONE,), {}))
addProvider(type("DataONEStage", (FakeDataONE,), {}))
