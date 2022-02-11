import responses
from girder.exceptions import RestException
from girder.models.user import User
from tests import base


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.startServer()


def tearDownModule():
    base.stopServer()


class VerificatorTestCase(base.TestCase):
    def setUp(self):
        super(VerificatorTestCase, self).setUp()
        users = (
            {
                "email": "root@dev.null",
                "login": "admin",
                "firstName": "Root",
                "lastName": "van Klompf",
                "password": "secret",
            },
            {
                "email": "joe@dev.null",
                "login": "joeregular",
                "firstName": "Joe",
                "lastName": "Regular",
                "password": "secret",
            },
        )
        self.admin, self.user = [
            self.model("user").createUser(**user) for user in users
        ]

    def testBaseErrors(self):
        from server.lib.verificator import Verificator

        msg = "Either 'resource_server' or 'url' must be provided"
        with self.assertRaises(ValueError, msg=msg):
            Verificator()
        msg = "Either 'key' or 'user' must be provided"
        with self.assertRaises(ValueError, msg=msg):
            Verificator(resource_server="zenodo.org")

        verificator = Verificator(resource_server="some server", key="some key")
        self.assertEqual(verificator.headers, {})
        with self.assertRaises(NotImplementedError):
            verificator.verify()

    @responses.activate
    def testDataverseVerificator(self):
        responses.add(
            responses.GET,
            "https://dataverse.harvard.edu/api/users/token",
            json={"status": "ERROR", "message": "Token blah not found."},
            status=404,
        )
        from server.lib.dataverse.auth import DataverseVerificator

        verificator = DataverseVerificator(
            resource_server="dataverse.harvard.edu", user=self.user
        )
        self.assertEqual(verificator.headers, {})

        self.user["otherTokens"] = [
            {"resource_server": "dataverse.harvard.edu", "access_token": "blah"}
        ]
        self.user = User().save(self.user)
        verificator = DataverseVerificator(
            resource_server="dataverse.harvard.edu", user=self.user
        )
        self.assertEqual(verificator.headers, {"X-Dataverse-key": "blah"})

        with self.assertRaises(RestException):
            verificator.verify()  # Invalid key

    @responses.activate
    def testZenodoVerificator(self):
        responses.add(
            responses.POST,
            "https://sandbox.zenodo.org/api/deposit/depositions",
            json={
                "message": (
                    "The server could not verify that you are authorized to access the URL "
                    "requested. You either supplied the wrong credentials (e.g. a bad passw"
                    "ord), or your browser doesn't understand how to supply the credentials"
                    "required."
                ),
                "status": 401,
            },
            status=401,
        )
        from server.lib.zenodo.auth import ZenodoVerificator

        verificator = ZenodoVerificator(
            resource_server="sandbox.zenodo.org", user=self.user
        )
        self.assertEqual(verificator.headers, {})

        self.user["otherTokens"] = [
            {"resource_server": "sandbox.zenodo.org", "access_token": "blah"}
        ]
        self.user = User().save(self.user)
        verificator = ZenodoVerificator(
            resource_server="sandbox.zenodo.org", user=self.user
        )
        self.assertEqual(verificator.headers, {"Authorization": "Bearer blah"})

        with self.assertRaises(RestException):
            verificator.verify()  # Invalid key

    def tearDown(self):
        User().remove(self.user)
        User().remove(self.admin)
        super(VerificatorTestCase, self).tearDown()
