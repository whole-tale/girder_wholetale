import json
import mock
from tests import base

from girder.models.user import User


def setUpModule():
    base.enabledPlugins.append("wholetale")
    base.enabledPlugins.append("wt_home_dir")
    base.enabledPlugins.append("wt_versioning")
    base.startServer()

    global JobStatus, Tale
    from girder.plugins.jobs.constants import JobStatus
    from girder.plugins.wholetale.models.tale import Tale


def tearDownModule():
    base.stopServer()


class FakeJob:

    job = {}

    def delay(self, *args, **kwargs):
        return self.job


class PublishTestCase(base.TestCase):
    def setUp(self):
        super(PublishTestCase, self).setUp()
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
        self.admin, self.user = [User().createUser(**user) for user in users]
        self.image = self.model("image", "wholetale").createImage(
            name="test my name", creator=self.admin, public=True,
            config=dict(template='base.tpl', buildpack='SomeBuildPack',
                        user='someUser', port=8888, urlPath='')
        )

        self.tale = self.model("tale", "wholetale").createTale(
            self.image,
            data=[],
            authors=self.user["firstName"] + " " + self.user["lastName"],
            creator=self.user,
            public=True,
            description="blah",
            title="Test",
            illustration="linkToImage",
        )

    def testConfigValidators(self):
        from girder.plugins.wholetale.constants import PluginSettings, SettingDefault

        resp = self.request(
            "/system/setting",
            user=self.admin,
            method="PUT",
            params={"key": PluginSettings.PUBLISHER_REPOS, "value": "random_string"},
        )
        self.assertStatus(resp, 400)
        self.assertTrue(
            resp.json["message"].startswith("Invalid Repository to Auth Provider map")
        )

        resp = self.request(
            "/system/setting",
            user=self.admin,
            method="PUT",
            params={
                "key": PluginSettings.PUBLISHER_REPOS,
                "value": json.dumps(
                    SettingDefault.defaults[PluginSettings.PUBLISHER_REPOS]
                ),
            },
        )
        self.assertStatusOk(resp)

    def testPublishDataONE(self):
        with mock.patch("gwvolman.tasks.publish.apply_async"), mock.patch(
            "gwvolman.tasks.publish.delay"
        ) as dl, mock.patch(
            "girder.plugins.wholetale.lib.manifest.ImageBuilder"
        ) as mock_builder:
            mock_builder.return_value.container_config.repo2docker_version = \
                "craigwillis/repo2docker:latest"
            mock_builder.return_value.get_tag.return_value = "images.local.wholetale.org/digest123"
            dl.return_value = FakeJob()

            remoteMemberNode = "nowhere"  # non exisiting repository
            resp = self.request(
                path="/tale/{_id}/publish".format(**self.tale),
                method="PUT",
                user=self.user,
                params={"repository": remoteMemberNode},
            )
            self.assertStatus(resp, 400)
            self.assertEqual(
                resp.json["message"], "Unknown publisher repository (nowhere)"
            )

            remoteMemberNode = "https://dev.nceas.ucsb.edu/knb/d1/mn"
            resp = self.request(
                path="/tale/{_id}/publish".format(**self.tale),
                method="PUT",
                user=self.user,
                params={"repository": remoteMemberNode},
            )
            self.assertStatus(resp, 400)
            self.assertEqual(
                resp.json["message"], "Missing a token for publisher (dataone)."
            )

            # "Authenticate" with DataONE
            token = {
                "access_token": "dataone_token",
                "provider": "dataone",
                "resource_server": "cn-stage.dataone.org",
                "token_type": "apikey",
            }
            self.user["otherTokens"] = [token]
            self.user = User().save(self.user)

            resp = self.request(
                path="/tale/{_id}/publish".format(**self.tale),
                method="PUT",
                user=self.user,
                params={"repository": remoteMemberNode},
            )
            self.assertStatusOk(resp)

            job_kwargs = dl.call_args_list[-1][1]
            job_args = dl.call_args_list[-1][0]
            self.assertEqual(job_args[0], str(self.tale["_id"]))
            self.assertDictEqual(job_args[1], token)
            self.assertTrue(job_args[2] is not None)
            self.assertEqual(job_kwargs["repository"], remoteMemberNode)

    def testPublishZenodo(self):
        with mock.patch("gwvolman.tasks.publish.apply_async"), mock.patch(
            "gwvolman.tasks.publish.delay"
        ) as dl, mock.patch(
            "girder.plugins.wholetale.lib.manifest.ImageBuilder"
        ) as mock_builder:
            mock_builder.return_value.container_config.repo2docker_version = \
                "craigwillis/repo2docker:latest"
            mock_builder.return_value.get_tag.return_value = "images.local.wholetale.org/digest123"
            dl.return_value = FakeJob()

            repository = "sandbox.zenodo.org"
            resp = self.request(
                path="/tale/{_id}/publish".format(**self.tale),
                method="PUT",
                user=self.user,
                params={"repository": repository},
            )
            self.assertStatus(resp, 400)
            self.assertEqual(
                resp.json["message"], "Missing a token for publisher (zenodo)."
            )

            token = {
                "access_token": "zenodo_key",
                "provider": "zenodod",
                "resource_server": "sandbox.zenodo.org",
                "token_type": "apikey",
            }
            self.user["otherTokens"] = [token]
            self.user = User().save(self.user)

            resp = self.request(
                path="/tale/{_id}/publish".format(**self.tale),
                method="PUT",
                user=self.user,
                params={"repository": repository},
            )
            self.assertStatusOk(resp)

            job_kwargs = dl.call_args_list[-1][1]
            job_args = dl.call_args_list[-1][0]
            self.assertEqual(job_args[0], str(self.tale["_id"]))
            self.assertDictEqual(job_args[1], token)
            self.assertTrue(job_args[2] is not None)
            self.assertEqual(job_kwargs["repository"], repository)

    def tearDown(self):
        User().remove(self.user)
        User().remove(self.admin)
        super(PublishTestCase, self).tearDown()
