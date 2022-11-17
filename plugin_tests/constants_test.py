from tests import base


def setUpModule():

    base.enabledPlugins.append("wholetale")
    base.startServer()


def tearDownModule():

    base.stopServer()


class TestDataONEUtils(base.TestCase):
    def test_harvester_type(self):
        from server.constants import HarvesterType

        self.assertEqual(HarvesterType.DATAONE, 0)

    def test_dataone_endpoints(self):
        # Testing this to make sure the endpoints aren't accidentally changed
        from server.lib.dataone import DataONELocations

        self.assertEqual(DataONELocations.prod_cn, "https://cn.dataone.org/cn/v2")
        self.assertEqual(
            DataONELocations.dev_mn, "https://dev.nceas.ucsb.edu/knb/d1/mn/v2"
        )
        self.assertEqual(
            DataONELocations.dev_cn, "https://cn-stage.test.dataone.org/cn/v2"
        )
