import json
import mock
import os
import responses
import time
import vcr
from tests import base

from girder.models.folder import Folder
from girder.models.item import Item


DATA_PATH = os.path.join(
    os.path.dirname(os.environ['GIRDER_TEST_DATA_PREFIX']),
    'data_src', 'plugins', 'wholetale'
)


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.enabledPlugins.append('wt_home_dir')
    base.enabledPlugins.append('wt_versioning')
    base.startServer()


def tearDownModule():
    base.stopServer()


class DataverseHarversterTestCase(base.TestCase):

    def setUp(self):
        users = ({
            'email': 'root@dev.null',
            'login': 'admin',
            'firstName': 'Root',
            'lastName': 'van Klompf',
            'password': 'secret'
        }, {
            'email': 'joe@dev.null',
            'login': 'joeregular',
            'firstName': 'Joe',
            'lastName': 'Regular',
            'password': 'secret'
        })
        self.admin, self.user = [self.model('user').createUser(**user)
                                 for user in users]

    @vcr.use_cassette(os.path.join(DATA_PATH, 'dataverse_lookup.txt'))
    @responses.activate
    def testLookup(self):
        responses.add_passthru("https://dataverse.harvard.edu/api/access")
        responses.add_passthru("https://dataverse.harvard.edu/api/datasets")
        responses.add_passthru("https://dataverse.harvard.edu/dataset.xhtml")
        responses.add_passthru("https://dataverse.harvard.edu/file.xhtml")
        responses.add_passthru("https://dvn-cloud.s3.amazonaws.com/")
        responses.add_passthru("https://dataverse.harvard.edu/api/search?q=filePersistentId")
        responses.add_passthru("https://dataverse.harvard.edu/citation")
        responses.add_passthru("https://doi.org")
        responses.add(
            responses.GET,
            "https://dataverse.harvard.edu/api/search?q=entityId:3040230",
            json={
                "status": "OK",
                "data": {
                    "q": "entityId:3040230",
                    "total_count": 1,
                    "start": 0,
                    "spelling_alternatives": {},
                    "items": [
                        {
                            "name": "2017-07-31.tab",
                            "type": "file",
                            "url": "https://dataverse.harvard.edu/api/access/datafile/3040230",
                            "file_id": "3040230",
                            "published_at": "2017-07-31T22:27:23Z",
                            "file_type": "Tab-Delimited",
                            "file_content_type": "text/tab-separated-values",
                            "size_in_bytes": 12025,
                            "md5": "e7dd2f725941b978d45fed3f33ff640c",
                            "checksum": {
                                "type": "MD5",
                                "value": "e7dd2f725941b978d45fed3f33ff640c",
                            },
                            "unf": "UNF:6:6wGE3C5ragT8A0qkpGaEaQ==",
                            "dataset_citation": (
                                "Durbin, Philip, 2017, \"Open Source at Harvard\", "
                                "https://doi.org/10.7910/DVN/TJCLKP, Harvard Dataverse, "
                                " V2, UNF:6:6wGE3C5ragT8A0qkpGaEaQ== [fileUNF]"
                            ),
                        }
                    ],
                    "count_in_response": 1,
                },
            }
        )

        resp = self.request(
            path='/repository/lookup', method='GET', user=self.user,
            params={'dataId': json.dumps([
                'https://doi.org/10.7910/DVN/RLMYMR',
                'https://doi.org/10.7910/DVN/RLMYMR/WNKD3W',
                'https://dataverse.harvard.edu/api/access/datafile/3040230'
            ])}
        )
        self.assertStatus(resp, 200)
        self.assertEqual(resp.json, [
            {
                "dataId": "https://dataverse.harvard.edu/dataset.xhtml"
                          "?persistentId=doi:10.7910/DVN/RLMYMR",
                "doi": "doi:10.7910/DVN/RLMYMR",
                "name": "Karnataka Diet Diversity and Food Security for "
                        "Agricultural Biodiversity Assessment",
                "repository": "Dataverse",
                "size": 495885,
                "tale": False,
            },
            {
                "dataId": "https://dataverse.harvard.edu/file.xhtml"
                          "?persistentId=doi:10.7910/DVN/RLMYMR/WNKD3W",
                "doi": "doi:10.7910/DVN/RLMYMR",
                "name": "Karnataka Diet Diversity and Food Security for "
                        "Agricultural Biodiversity Assessment",
                "repository": "Dataverse",
                "size": 2321,
                "tale": False,
            },
            {
                "dataId": "https://dataverse.harvard.edu/api/access/datafile/3040230",
                "doi": "doi:10.7910/DVN/TJCLKP",
                "name": "Open Source at Harvard",
                "repository": "Dataverse",
                "size": 12025,
                "tale": False,
            }
        ])

        resp = self.request(
            path='/repository/listFiles', method='GET', user=self.user,
            params={'dataId': json.dumps([
                'https://doi.org/10.7910/DVN/RLMYMR',
                'https://doi.org/10.7910/DVN/RLMYMR/WNKD3W',
                'https://dataverse.harvard.edu/api/access/datafile/3040230'
            ])}
        )
        self.assertStatus(resp, 200)
        self.assertEqual(resp.json, [
            {
                "Karnataka Diet Diversity and Food Security for "
                "Agricultural Biodiversity Assessment": {
                    "fileList": [
                        {"Karnataka_DDFS_Data-1.tab": {"size": 2408}},
                        {"Karnataka_DDFS_Data-1.xlsx": {"size": 700840}},
                        {"Karnataka_DDFS_Questionnaire.pdf": {"size": 493564}}
                    ]
                }
            },
            {
                "Karnataka Diet Diversity and Food Security for "
                "Agricultural Biodiversity Assessment": {
                    "fileList": [
                        {"Karnataka_DDFS_Data-1.tab": {"size": 2408}},
                        {"Karnataka_DDFS_Data-1.xlsx": {"size": 700840}}
                    ]
                }
            },
            {
                "Open Source at Harvard": {
                    "fileList": [
                        {"2017-07-31.csv": {"size": 11684}},
                        {"2017-07-31.tab": {"size": 12100}}
                    ]
                }
            }
        ])

    def testConfigValidators(self):
        from girder.plugins.wholetale.constants import PluginSettings, SettingDefault
        resp = self.request('/system/setting', user=self.admin, method='PUT',
                            params={'key': PluginSettings.DATAVERSE_URL,
                                    'value': 'random_string'})
        self.assertStatus(resp, 400)
        self.assertEqual(resp.json, {
            'field': 'value',
            'type': 'validation',
            'message': 'Invalid Dataverse URL'
        })

        resp = self.request(
            '/system/setting', user=self.admin, method='PUT',
            params={'key': PluginSettings.DATAVERSE_URL,
                    'value': SettingDefault.defaults[PluginSettings.DATAVERSE_URL]})
        self.assertStatusOk(resp)

        resp = self.request(
            '/system/setting', user=self.admin, method='PUT',
            params={'key': PluginSettings.DATAVERSE_URL,
                    'value': ''})
        self.assertStatusOk(resp)
        resp = self.request(
            '/system/setting', user=self.admin, method='GET',
            params={'key': PluginSettings.DATAVERSE_URL})
        self.assertStatusOk(resp)
        self.assertEqual(
            resp.body[0].decode(),
            '"{}"'.format(SettingDefault.defaults[PluginSettings.DATAVERSE_URL]))

    @vcr.use_cassette(os.path.join(DATA_PATH, 'dataverse_single.txt'))
    def testSingleDataverseInstance(self):
        from girder.plugins.wholetale.constants import PluginSettings, SettingDefault
        resp = self.request('/system/setting', user=self.admin, method='PUT',
                            params={'key': PluginSettings.DATAVERSE_URL,
                                    'value': 'https://demo.dataverse.org/'})
        self.assertStatusOk(resp)

        resp = self.request(
            path='/repository/lookup', method='GET', user=self.user,
            params={'dataId': json.dumps([
                "https://demo.dataverse.org/api/access/datafile/1849559"
            ])}
        )
        self.assertStatus(resp, 200)
        self.assertEqual(resp.json, [
            {
                "dataId": "https://demo.dataverse.org/api/access/datafile/1849559",
                "doi": "doi:10.70122/FK2/H60OIK",
                "name": "test file access by version",
                "repository": "Dataverse",
                "size": 4750,
                "tale": False,
            }
        ])

        resp = self.request(
            path='/repository/listFiles', method='GET', user=self.user,
            params={'dataId': json.dumps([
                'https://demo.dataverse.org/api/access/datafile/1849559'
            ])}
        )
        self.assertStatus(resp, 200)
        self.assertEqual(resp.json, [
            {
                "test file access by version": {
                    "fileList": [
                        {"images.jpg": {"size": 4750}},
                    ]
                }
            }
        ])

        resp = self.request(
            '/system/setting', user=self.admin, method='PUT',
            params={'key': PluginSettings.DATAVERSE_URL,
                    'value': SettingDefault.defaults[PluginSettings.DATAVERSE_URL]})
        self.assertStatusOk(resp)

    def testExtraHosts(self):
        from girder.plugins.wholetale.constants import PluginSettings, SettingDefault
        resp = self.request('/system/setting', user=self.admin, method='PUT',
                            params={'key': PluginSettings.DATAVERSE_EXTRA_HOSTS,
                                    'value': 'dataverse.org'})
        self.assertStatus(resp, 400)
        self.assertEqual(resp.json, {
            'field': 'value',
            'type': 'validation',
            'message': 'Dataverse extra hosts setting must be a list.'
        })

        resp = self.request('/system/setting', user=self.admin, method='PUT',
                            params={'key': PluginSettings.DATAVERSE_EXTRA_HOSTS,
                                    'value': json.dumps(['not a domain'])})
        self.assertStatus(resp, 400)
        self.assertEqual(resp.json, {
            'field': 'value',
            'type': 'validation',
            'message': 'Invalid domain in Dataverse extra hosts'
        })

        # defaults
        resp = self.request(
            '/system/setting', user=self.admin, method='PUT',
            params={'key': PluginSettings.DATAVERSE_EXTRA_HOSTS,
                    'value': ''})
        self.assertStatusOk(resp)
        resp = self.request(
            '/system/setting', user=self.admin, method='GET',
            params={'key': PluginSettings.DATAVERSE_EXTRA_HOSTS})
        self.assertStatusOk(resp)
        self.assertEqual(
            resp.body[0].decode(),
            str(SettingDefault.defaults[PluginSettings.DATAVERSE_EXTRA_HOSTS]))

        resp = self.request(
            '/system/setting', user=self.admin, method='PUT',
            params={'list': json.dumps([
                {
                    'key': PluginSettings.DATAVERSE_EXTRA_HOSTS,
                    'value': ['random.d.org', 'random2.d.org']
                },
                {
                    'key': PluginSettings.DATAVERSE_URL,
                    'value': 'https://demo.dataverse.org'
                }
            ])}
        )
        self.assertStatusOk(resp)
        from girder.plugins.wholetale.lib.dataverse.provider import DataverseImportProvider
        self.assertEqual(
            '^https?://(demo.dataverse.org|random.d.org|random2.d.org).*$',
            DataverseImportProvider().regex[-1].pattern
        )
        resp = self.request(
            '/system/setting', user=self.admin, method='PUT',
            params={'key': PluginSettings.DATAVERSE_URL,
                    'value': SettingDefault.defaults[PluginSettings.DATAVERSE_URL]})

    @vcr.use_cassette(os.path.join(DATA_PATH, 'dataverse_hierarchy.txt'))
    def testDatasetWithHierarchy(self):
        from girder.plugins.jobs.models.job import Job
        from girder.plugins.jobs.constants import JobStatus
        from server.models.image import Image
        from server.models.tale import Tale
        from server.lib.manifest import Manifest
        from server.lib.manifest_parser import ManifestParser
        doi = "doi:10.7910/DVN/Q5PV4U"
        dataMap = [
            {
                "dataId": (
                    "https://dataverse.harvard.edu/dataset.xhtml?"
                    "persistentId=" + doi
                ),
                "doi": doi,
                "name": (
                    "Replication Data for: Misgovernance and Human Rights: "
                    "The Case of Illegal Detention without Intent"
                ),
                "repository": "Dataverse",
                "size": 6326512,
                "tale": False,
            }
        ]

        resp = self.request(
            path="/dataset/register",
            method="POST",
            params={"dataMap": json.dumps(dataMap)},
            user=self.user,
        )
        self.assertStatusOk(resp)
        registration_job = resp.json

        for _ in range(100):
            job = Job().load(registration_job["_id"], force=True)
            if job["status"] > JobStatus.RUNNING:
                break
            time.sleep(0.1)
        self.assertEqual(job["status"], JobStatus.SUCCESS)

        ds_root = Folder().findOne({"meta.identifier": doi})
        ds_subfolder = Folder().findOne(
            {"name": "Source Data", "parentId": ds_root["_id"]}
        )
        ds_item = Item().findOne(
            {"name": "03_Analysis_Code.R", "folderId": ds_root["_id"]}
        )

        dataSet = [
            {
                "_modelType": "folder",
                "itemId": str(ds_root["_id"]),
                "mountPath": ds_root["name"],
            },
            {
                "_modelType": "folder",
                "itemId": str(ds_subfolder["_id"]),
                "mountPath": ds_subfolder["name"],
            },
            {
                "_modelType": "item",
                "itemId": str(ds_item["_id"]),
                "mountPath": ds_item["name"],
            }
        ]

        image = Image().createImage(name="test my name", creator=self.user, public=True)
        tale = Tale().createTale(
            image, dataSet, creator=self.user, title="Blah", public=True
        )
        with mock.patch("server.lib.manifest.ImageBuilder") as mock_builder:
            mock_builder.return_value.container_config.repo2docker_version = \
                "craigwillis/repo2docker:latest"
            mock_builder.return_value.get_tag.return_value = "some_digest"
            manifest = Manifest(tale, self.user, expand_folders=True).manifest

        restored_dataset = ManifestParser(manifest).get_dataset()
        self.assertEqual(restored_dataset, dataSet)

        Tale().remove(tale)
        Image().remove(image)

    def testProtoTale(self):
        from server.lib.dataverse.provider import DataverseImportProvider
        from server.lib.data_map import DataMap
        provider = DataverseImportProvider()

        datamap = {
            "dataId": (
                "https://dataverse.harvard.edu/dataset.xhtml?"
                "persistentId=doi:10.7910/DVN/26721"
            ),
            "doi": "doi:10.7910/DVN/26721",
            "name": (
                "Replication data for: Priming Predispositions "
                "and Changing Policy Positions"
            ),
            "repository": "Dataverse",
            "size": 44382520,
            "tale": False,
        }
        dataMap = DataMap.fromDict(datamap)

        tale = provider.proto_tale_from_datamap(dataMap, self.user, False)
        self.assertEqual(set(tale.keys()), {"title", "relatedIdentifiers", "category"})
        tale = provider.proto_tale_from_datamap(dataMap, self.user, True)
        self.assertEqual(tale["authors"][0]["lastName"], "Tesler")

        # dataverse.icrisat.org failing as of 8/15/2022
        # datamap = {
        #    "dataId": (
        #        "http://dataverse.icrisat.org/dataset.xhtml?"
        #        "persistentId=doi:10.21421/D2/TCCVS7"
        #    ),
        #    "doi": "doi:10.21421/D2/TCCVS7",
        #    "name": (
        #        "Phenotypic evaluation data of International Chickpea "
        #        "Varietal Trials (ICVTs) – Desi for Year 2016-17"
        #    ),
        #    "repository": "Dataverse",
        #    "size": 99504,
        #    "tale": False,
        # }
        # tale = provider.proto_tale_from_datamap(DataMap.fromDict(datamap), self.user, True)
        # self.assertEqual(tale["authors"][0]["firstName"], "Pooran")

    def tearDown(self):
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
