from tests import base


def setUpModule():

    base.enabledPlugins.append('wholetale')
    base.startServer()


def tearDownModule():

    base.stopServer()


class TestDataONEUtils(base.TestCase):

    def test_harvester_type(self):
        from server.constants import HarvesterType

        self.assertEqual(HarvesterType.DATAONE, 0)

    def test_plugin_settings(self):
        from server.constants import PluginSettings

        self.assertEqual(PluginSettings.TMPNB_URL, 'wholetale.tmpnb_url')
        self.assertEqual(PluginSettings.HUB_PRIV_KEY, 'wholetale.priv_key')
        self.assertEqual(PluginSettings.HUB_PUB_KEY, 'wholetale.pub_key')


    def test_dataone_endpoints(self):
        # Testing this to make sure the endpoints aren't accidentally changed
        from server.constants import DataONELocations

        self.assertEqual(DataONELocations.prod_cn, 'https://cn.dataone.org/cn/v2')
        self.assertEqual(DataONELocations.dev_mn, 'https://dev.nceas.ucsb.edu/knb/d1/mn/v2')
        self.assertEqual(DataONELocations.dev_cn, 'https://cn-stage-2.test.dataone.org/cn/v2')