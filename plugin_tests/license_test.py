from tests import base


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.startServer()


def tearDownModule():
    base.stopServer()


class LicenseTestCase(base.TestCase):
    def setUp(self):
        super(LicenseTestCase, self).setUp()

    def testGetLicenses(self):
        resp = self.request(path="/license", method="GET", type="application/json")

        # Make sure that we support CC0
        is_supported = all(x for x in resp.json if (x["spdx"] == "CC0-1.0"))
        self.assertTrue(is_supported)
        # Make sure that we support CC-BY
        is_supported = all(x for x in resp.json if (x["spdx"] == "CC-BY-4.0"))
        self.assertTrue(is_supported)

    def testMinimumLicenses(self):
        from server.lib.license import WholeTaleLicense

        # Test that we're supporting a non-zero number of licenses
        wholetale_license = WholeTaleLicense()
        self.assertTrue(len(wholetale_license.get_defaults()) > 0)
        self.assertTrue(len(wholetale_license.get_spdx() > 0))
        self.assertTrue(len(WholeTaleLicense.default_spdx()) > 0)

    def tearDown(self):
        super(LicenseTestCase, self).tearDown()
