import base64
import httmock
import json
import mock
import operator
import os
import six
import vcr
from tests import base
from girder.api.rest import RestException


DATA_PATH = os.path.join(
    os.path.dirname(os.environ['GIRDER_TEST_DATA_PREFIX']),
    'data_src', 'plugins', 'wholetale'
)

D1_MAP = {
    'response': {
        'docs': [{
            'documents': [
                'urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9',
                'urn:uuid:dc29f3cf-022a-4a33-9eed-8dc9ba6e0218',
                'urn:uuid:428fcb96-03a9-42b3-81d1-2944ac686e55'],
            'formatId': 'eml://ecoinformatics.org/eml-2.1.1',
            'formatType': 'METADATA',
            'identifier': 'urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9',
            'size': 21702,
            'title': 'Thaw depth in the ITEX plots at Barrow and Atqasuk, Alaska',
        }, {

            'fileName': '2015_Barrow_Atqasuk_ITEX_Thaw_v1.csv',
            'formatId': 'text/csv',
            'formatType': 'DATA',
            'identifier': 'urn:uuid:dc29f3cf-022a-4a33-9eed-8dc9ba6e0218',
            'size': 7770
        }, {
            'fileName': '1995-20XX_Barrow_Atqasuk_ITEX_Thaw_metadata-Copy.txt',
            'formatId': 'text/plain',
            'formatType': 'DATA',
            'identifier': 'urn:uuid:428fcb96-03a9-42b3-81d1-2944ac686e55',
            'size': 3971
        }],
        'numFound': 3,
        'start': 0},
    'responseHeader': {
        'QTime': 4,
        'params': {
            'fl': 'identifier,formatType,title,size,formatId,fileName,documents',
            'q': 'resourceMap:"resource_map_doi:10.18739/A2ND53"',
            'rows': '1000',
            'start': '0',
            'wt': 'json'},
        'status': 0
    }
}


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.startServer()


class MockResponse(object):

    def __init__(self, data=None, url=None, info={}, code=200, msg='OK'):
        self.stream = six.StringIO(data)
        self.code = code
        self.msg = msg
        self._info = info
        self.url = url
        self.headers = {'content-type': 'application/rdf xml'}

    def read(self, *args, **kwargs):
        return self.stream.read(*args, **kwargs)

    def getcode(self):
        return self.code

    def info(self):
        return self._info

    def geturl(self):
        return self.url

    def close(self):
        return self.stream.close()


def fake_urlopen(url):
    fname = os.path.join(DATA_PATH, 'harvester_test01.json')
    with open(fname, 'r') as fp:
        data = json.load(fp)
    data['data'] = base64.b64decode(
        data['data'].encode('utf8')).decode('utf8')
    f = MockResponse(**data)
    return f


def tearDownModule():
    base.stopServer()


class DataONEHarversterTestCase(base.TestCase):

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
        self.patcher = mock.patch('rdflib.parser.urlopen', fake_urlopen)
        self.patcher.start()

    @vcr.use_cassette(os.path.join(DATA_PATH, 'dataone_lookup.txt'))
    def testLookup(self):
        from girder.plugins.wholetale.lib.import_item import ImportItem
        # TODO: mock this if it's necessary
        # resp = self.request(
        #     path='/repository/lookup', method='GET',
        #     params={'dataId': json.dumps(['blah'])})
        # self.assertStatus(resp, 400)
        # self.assertEqual(resp.json, {
        #     'type': 'rest',
        #     'message': 'No object was found in the index for blah.'
        # })

        resp = self.request(
            path='/repository/lookup', method='GET',
            params={'dataId':
                    json.dumps(['doi:10.18739/A2ND53',
                                'http://use.yt/upload/944d8537'])})
        self.assertStatus(resp, 200)
        dataMap = resp.json

        self.assertEqual(
            dataMap, [
                {
                    'dataId': 'resource_map_doi:10.18739/A2ND53',
                    'doi': 'doi:10.18739/A2ND53',
                    'name': 'Thaw depth in the ITEX plots at Barrow and Atqasuk, Alaska',
                    'repository': 'DataONE',
                    'size': 27747,
                    'tale': False,
                }, {
                    'dataId': 'http://use.yt/upload/944d8537',
                    'doi': None,
                    'name': 'nginx.tmpl',
                    'repository': 'HTTP',
                    'size': 8792,
                    'tale': False,
                }]
        )

        resp = self.request(
            path='/dataset/register', method='POST',
            params={'dataMap': json.dumps(dataMap),
                    'copyToHome': True})
        self.assertStatus(resp, 401)

        resp = self.request(
            path='/dataset/register', method='POST',
            params={'dataMap': json.dumps(dataMap)}, user=self.user)
        self.assertStatusOk(resp)

        # Grab user data
        resp = self.request(
            path='/dataset', method='GET', user=self.user, params={'myData': True})
        self.assertStatusOk(resp)
        datasets = resp.json
        self.assertEqual(len(datasets), 2)
        ds_folder = next((_ for _ in datasets if _['_modelType'] == 'folder'), None)
        self.assertNotEqual(ds_folder, None)
        folder = self.model('folder').load(ds_folder['_id'], user=self.user)
        self.assertEqual(folder['name'], ImportItem(0, name=dataMap[0]['name']).name)
        self.assertEqual(folder['meta']['provider'], dataMap[0]['repository'])
        self.assertEqual(folder['meta']['identifier'], dataMap[0]['doi'])

        resp = self.request('/item', method='GET', user=self.user,
                            params={'folderId': str(folder['_id'])})
        self.assertStatusOk(resp)
        items = resp.json

        source = [_ for _ in D1_MAP['response']['docs'] if 'fileName' in _]
        source.sort(key=operator.itemgetter('fileName'))
        self.assertEqual(len(items), len(source))

        for i in range(len(items)):
            self.assertEqual(items[i]['name'], source[i]['fileName'])
            self.assertEqual(items[i]['size'], source[i]['size'])
            self.assertEqual(items[i]['meta']['identifier'],
                             source[i]['identifier'])

        # TODO: check if it's that method is still used anywhere
        resp = self.request('/folder/registered', method='GET', user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 4)
        # self.assertEqual(folder, resp.json[0])

        ds_item = next((_ for _ in datasets if _['_modelType'] == 'item'), None)
        item = self.model('item').load(ds_item['_id'], user=self.user, force=True)
        self.assertEqual(item['name'], 'nginx.tmpl')

    @vcr.use_cassette(os.path.join(DATA_PATH, 'test_list_files.txt'))
    def test_list_files(self):
        resp = self.request(
            path='/repository/listFiles', method='GET', user=self.user,
            params={'dataId': json.dumps(["doi:10.5065/D6862DM8"])}
        )
        self.assertStatus(resp, 200)
        fname = os.path.join(DATA_PATH, 'dataone_listFiles.json')
        with open(fname, 'r') as fp:
            data = json.load(fp)
        self.assertEqual(resp.json, data)

    def tearDown(self):
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        self.patcher.stop()
