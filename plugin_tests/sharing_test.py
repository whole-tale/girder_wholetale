import json
import time

import mock
from girder.constants import AccessType
from tests import base


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.startServer()


def tearDownModule():
    base.stopServer()


class SharingTestCase(base.TestCase):
    def setUp(self):
        super(SharingTestCase, self).setUp()

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

        self.image = self.model("image", "wholetale").createImage(
            name="image my name", creator=self.user, idleTimeout=0.25, public=True
        )

    def testTaleWithInstanceDelete(self):
        tale_model = self.model("tale", "wholetale")
        instance_model = self.model("instance", "wholetale")

        tale = tale_model.createTale(
            self.image, [], creator=self.admin, title="Some Title"
        )

        tale = tale_model.setUserAccess(
            tale, user=self.user, level=AccessType.WRITE, save=True
        )
        instance = instance_model.createInstance(
            tale, self.user, name="instance_1", save=True, spawn=False
        )

        resp = self.request(
            path="/tale/{_id}".format(**tale),
            method="DELETE",
            user=self.admin,
            exception=True,
        )
        self.assertStatus(resp, 409)

        from girder.plugins.wholetale.models.instance import Instance

        with mock.patch.object(Instance, "deleteInstance") as delete_mocked:
            delete_mocked.return_value = None
            resp = self.request(
                path="/tale/{_id}".format(**tale),
                params={"force": True},
                method="DELETE",
                user=self.admin,
            )
            delete_mocked.assert_called_once()
            call = delete_mocked.mock_calls[0]
            self.assertEqual(call.args[0]["_id"], instance["_id"])
            self.assertEqual(call.args[1]["_id"], self.user["_id"])
            instance_model.remove(instance)
            self.assertStatusOk(resp)

    def testTaleWithInstanceUnshare(self):
        tale_model = self.model("tale", "wholetale")
        instance_model = self.model("instance", "wholetale")

        tale = tale_model.createTale(
            self.image, [], creator=self.admin, title="Some Title"
        )

        tale = tale_model.setUserAccess(
            tale, user=self.user, level=AccessType.WRITE, save=True
        )
        instance = instance_model.createInstance(
            tale, self.user, name="instance_1", save=True, spawn=False
        )

        resp = self.request(
            path="/tale/{_id}/relinquish".format(**tale),
            method="PUT",
            user=self.user,
            exception=True,
            params={"level": 0},
        )
        self.assertStatus(resp, 409)

        from girder.plugins.wholetale.models.instance import Instance

        with mock.patch.object(Instance, "deleteInstance") as delete_mocked:
            delete_mocked.return_value = None
            resp = self.request(
                path="/tale/{_id}/relinquish".format(**tale),
                method="PUT",
                user=self.user,
                params={"level": 0, "force": True},
            )
            self.assertStatusOk(resp)
            delete_mocked.assert_called_once()
            call = delete_mocked.mock_calls[0]
            self.assertEqual(call.args[0]["_id"], instance["_id"])
            self.assertEqual(call.args[1]["_id"], self.user["_id"])
            instance_model.remove(instance)
            self.assertEqual(resp.json["_id"], str(tale["_id"]))
            self.assertEqual(resp.json["_accessLevel"], 0)

        resp = self.request(
            path=f"/tale/{tale['_id']}/access", method="GET", user=self.admin
        )
        self.assertStatusOk(resp)
        orig_access = resp.json

        tale = tale_model.setUserAccess(
            tale, user=self.user, level=AccessType.WRITE, save=True
        )
        instance = instance_model.createInstance(
            tale, self.user, name="instance_1", save=True, spawn=False
        )

        resp = self.request(
            path=f"/tale/{tale['_id']}/access",
            params={"access": json.dumps(orig_access)},
            method="PUT",
            user=self.admin,
            exception=True,
        )
        self.assertStatus(resp, 409)
        with mock.patch.object(Instance, "deleteInstance") as delete_mocked:
            delete_mocked.return_value = None
            resp = self.request(
                path=f"/tale/{tale['_id']}/access",
                method="PUT",
                user=self.admin,
                params={"force": True, "access": json.dumps(orig_access)},
            )
            self.assertStatusOk(resp)
            delete_mocked.assert_called_once()
            call = delete_mocked.mock_calls[0]
            self.assertEqual(call.args[0]["_id"], instance["_id"])
            self.assertEqual(call.args[1]["_id"], self.user["_id"])
            instance_model.remove(instance)
        tale_model.remove(tale)

    def tearDown(self):
        self.model("image", "wholetale").remove(self.image)
        self.model("user").remove(self.user)
        self.model("user").remove(self.admin)
        super(SharingTestCase, self).tearDown()
