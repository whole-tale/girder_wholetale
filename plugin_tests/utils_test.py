from tests import base


def setUpModule():

    base.enabledPlugins.append("wholetale")
    base.startServer()


def tearDownModule():

    base.stopServer()


class TestDataONEUtils(base.TestCase):
    def test_getOrCreateRootFolder(self):
        from server.utils import getOrCreateRootFolder

        folder_name = "folder_name"
        folder_desc = "folder_description"
        folder = getOrCreateRootFolder(folder_name, folder_desc)

        self.assertEqual(folder["name"], folder_name)
        self.assertEqual(folder["description"], folder_desc)
