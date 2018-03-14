
import base64
import httmock
import json
import mock
import operator
import os
import six
from tests import base
from girder.constants import ROOT_DIR
from girder.api.rest import RestException


D1_QUERY_URL = (
    'https://cn.dataone.org/cn/v2/query/solr/'
    '?q=identifier:%22urn%3Auuid%3Ac878ae53-06cf-40c9-a830-7f6f564133f9%22&'
    'fl=identifier,formatType,formatId,resourceMap&rows=1000&start=0&wt=json'
)

D1_QUERY = {
    'response': {
        'docs': [{
            'formatId': 'eml://ecoinformatics.org/eml-2.1.1',
            'formatType': 'METADATA',
            'identifier': 'urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9',
            'resourceMap': [
                'resource_map_urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9'
            ]}],
        'numFound': 1,
        'start': 0
    },
    'responseHeader':
        {'QTime': 30,
         'params': {
             'fl': 'identifier,formatType,formatId,resourceMap',
             'q': 'identifier:"urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9"',
             'rows': '1000',
             'start': '0',
             'wt': 'json'},
         'status': 0}
}

D1_MAP_URL = (
    'https://cn.dataone.org/cn/v2/query/solr/'
    '?q=resourceMap:%22resource_map_urn%3A'
    'uuid%3Ac878ae53-06cf-40c9-a830-7f6f564133f9%22&'
    'fl=identifier,formatType,title,size,formatId,'
    'fileName,documents&rows=1000&start=0&wt=json'
)

D1_MAP = {
    'response': {
        'docs': [{
            'documents': [
                'urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9',
                'urn:uuid:dc29f3cf-022a-4a33-9eed-8dc9ba6e0218',
                'urn:uuid:428fcb96-03a9-42b3-81d1-2944ac686e55',
                'urn:uuid:bd7754a7-d4db-4217-8bf0-4c5d3691c0bc'],
            'formatId': 'eml://ecoinformatics.org/eml-2.1.1',
            'formatType': 'METADATA',
            'identifier': 'urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9',
            'size': 21702,
            'title': 'Thaw depth in the ITEX plots at Barrow and Atqasuk, Alaska'
        }, {
            'fileName': '2015 Barrow Atqasuk ITEX Thaw v1.csv',
            'formatId': 'text/csv',
            'formatType': 'DATA',
            'identifier': 'urn:uuid:dc29f3cf-022a-4a33-9eed-8dc9ba6e0218',
            'size': 7770
        }, {
            'fileName': '1995-20XX Barrow Atqasuk ITEX Thaw metadata - Copy.txt',
            'formatId': 'text/plain',
            'formatType': 'DATA',
            'identifier': 'urn:uuid:428fcb96-03a9-42b3-81d1-2944ac686e55',
            'size': 3971
        }, {
            'fileName': '2016 Barrow Atqasuk ITEX Thaw v1.csv',
            'formatId': 'text/csv',
            'formatType': 'DATA',
            'identifier': 'urn:uuid:bd7754a7-d4db-4217-8bf0-4c5d3691c0bc',
            'size': 7439
        }],
        'numFound': 4,
        'start': 0},
    'responseHeader': {
        'QTime': 4,
        'params': {
            'fl': 'identifier,formatType,title,size,formatId,fileName,documents',
            'q': 'resourceMap:"resource_map_urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9"',
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
    fname = os.path.join(ROOT_DIR, 'plugins', 'wholetale', 'plugin_tests',
                         'dataone_test01.json')
    with open(fname, 'r') as fp:
        data = json.load(fp)
    data['data'] = base64.b64decode(
        data['data'].encode('utf8')).decode('utf8')
    f = MockResponse(**data)
    return f


def tearDownModule():
    base.stopServer()


class DataONEHarversterTestCase(base.TestCase):

    @httmock.all_requests
    def mockOtherRequest(self, url, request):
        raise Exception('Unexpected url %s' % str(request.url))

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

    def testLookup(self):
        # TODO: mock this if it's necessary
        # resp = self.request(
        #     path='/repository/lookup', method='GET',
        #     params={'dataId': json.dumps(['blah'])})
        # self.assertStatus(resp, 400)
        # self.assertEqual(resp.json, {
        #     'type': 'rest',
        #     'message': 'No object was found in the index for blah.'
        # })

        @httmock.urlmatch(scheme='https', netloc='^cn.dataone.org$',
                          path='^/cn/v2/query/solr/$', method='GET')
        def mockSearchDataONE(url, request):
            if '944d8537' in request.url:
                raise RestException(
                    'No object was found in the index for %s.' % request.url)
            if url.query.startswith('q=identifier'):
                return json.dumps(D1_QUERY)
            elif url.query.startswith('q=resourceMap'):
                return json.dumps(D1_MAP)
            raise Exception('Unexpected query in url %s' % str(request.url))

        @httmock.urlmatch(scheme='http', netloc='^use.yt$',
                          path='^/upload/944d8537$', method='HEAD')
        def mockCurldrop(url, request):
            headers = {
                'Content-Type': 'application/octet-stream',
                'Content-Length': '8792',
                'Content-Disposition': 'attachment; filename=nginx.tmpl'
            }
            return httmock.response(200, {}, headers, None, 5, request)

        with httmock.HTTMock(mockSearchDataONE, mockCurldrop,
                             self.mockOtherRequest):
            resp = self.request(
                path='/repository/lookup', method='GET',
                params={'dataId':
                        json.dumps(['urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9',
                                    'http://use.yt/upload/944d8537'])})
            self.assertStatus(resp, 200)
            dataMap = resp.json

        self.assertEqual(
            dataMap, [
                {
                    'dataId': 'resource_map_urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9',
                    'doi': 'urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9',
                    'name': 'Thaw depth in the ITEX plots at Barrow and Atqasuk, Alaska',
                    'repository': 'DataONE',
                    'size': 21702
                }, {
                    'dataId': 'http://use.yt/upload/944d8537',
                    'doi': 'unknown',
                    'name': 'nginx.tmpl',
                    'repository': 'HTTP',
                    'size': 8792
                }]
        )

        resp = self.request(
            path='/folder', method='GET', user=self.user, params={
                'parentType': 'user',
                'parentId': str(self.user['_id']),
                'text': 'Data',
                'sort': 'name',
                'sortdir': -1
            })
        self.assertStatusOk(resp)
        dataFolder = resp.json[0]

        with httmock.HTTMock(mockSearchDataONE, mockCurldrop,
                             self.mockOtherRequest):
            resp = self.request(
                path='/dataset/register', method='POST',
                params={'dataMap': json.dumps(dataMap),
                        'copyToHome': True})
            self.assertStatus(resp, 401)

            resp = self.request(
                path='/dataset/register', method='POST',
                params={'dataMap': json.dumps(dataMap)}, user=self.user)
            self.assertStatusOk(resp)

        # Grab the default user Data folders
        resp = self.request(
            path='/folder', method='GET', user=self.user, params={
                'parentType': 'folder',
                'parentId': dataFolder['_id'],
                'text': 'Thaw',
                'sort': 'name',
                'sortdir': -1
            })
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 1)
        folder = resp.json[0]
        self.assertEqual(folder['name'], dataMap[0]['name'])
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

        resp = self.request('/folder/registered', method='GET', user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 2)
        # self.assertEqual(folder, resp.json[0])

        resp = self.request(
            path='/item', method='GET', user=self.user, params={
                'folderId': dataFolder['_id'],
                'text': 'nginx'
            })
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 1)
        item = resp.json[0]
        self.assertEqual(item['name'], 'nginx.tmpl')

        # Dataset testing
        resp = self.request('/dataset', method='GET', user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(len(resp.json), 2)
        folder_ds = next(_ for _ in resp.json if _['modelType'] == 'folder')
        item_ds = next(_ for _ in resp.json if _['modelType'] == 'item')

        resp = self.request('/dataset/{}'.format(item_ds['_id']), method='GET',
                            user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['name'], item_ds['name'])

        resp = self.request(
            '/dataset/{}'.format(item_ds['_id']), method='PUT', user=self.user,
            type='application/json', body=json.dumps(item_ds))
        self.assertStatusOk(resp)

        resp = self.request(
            '/dataset/{}'.format(folder_ds['_id']), method='PUT', user=self.user,
            type='application/json', body=json.dumps(folder_ds))
        self.assertStatusOk(resp)

        resp = self.request(
            path='/folder/{}/details'.format(dataFolder['_id']),
            method='GET', user=self.user)
        self.assertStatusOk(resp)
        self.assertEqual(resp.json['nItems'], 2)
        self.assertEqual(resp.json['nFolders'], 2)

    def tearDown(self):
        self.model('user').remove(self.user)
        self.model('user').remove(self.admin)
        self.patcher.stop()


class ListFilesTestCase(base.TestCase):

    @httmock.all_requests
    def mockOtherRequest(self, url, request):
        raise Exception('Unexpected url %s' % str(request.url))

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

    def testListFiles(self):
        """Test the listFiles endpoint"""
        @httmock.urlmatch(scheme='https', netloc='^cn.dataone.org$',
                          path='^/cn/v2/query/solr/$', method='GET')
        def mockSearchDataONE(url, request):
            if '944d8537' in request.url:
                raise RestException(
                    'No object was found in the index for %s.' % request.url)
            if url.query.startswith('q=identifier'):
                return json.dumps(D1_QUERY)
            elif url.query.startswith('q=resourceMap'):
                return json.dumps(D1_MAP)
            raise Exception('Unexpected query in url %s' % str(request.url))

        @httmock.urlmatch(scheme='http', netloc='^use.yt$',
                          path='^/upload/944d8537$', method='HEAD')
        def mockCurldrop(url, request):
            headers = {
                'Content-Type': 'application/octet-stream',
                'Content-Length': '8792',
                'Content-Disposition': 'attachment; filename=nginx.tmpl'
            }
            return httmock.response(200, {}, headers, None, 5, request)

        with httmock.HTTMock(mockSearchDataONE, mockCurldrop,
                             self.mockOtherRequest):
            resp = self.request(
                path='/repository/listFiles', method='GET',
                params={'dataId':
                        json.dumps(['urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9'])})
            self.assertStatus(resp, 200)
            dataMap = resp.json

        self.assertEqual(
            dataMap, [[{
            'id' : 'urn:uuid:c878ae53-06cf-40c9-a830-7f6f564133f9',
            'name': 'Thaw depth in the ITEX plots at Barrow and Atqasuk, Alaska',
            'packageParent': 'Thaw depth in the ITEX plots at Barrow and Atqasuk, Alaska',
            'size': 21702,
        }, {
            'id': 'urn:uuid:dc29f3cf-022a-4a33-9eed-8dc9ba6e0218',
            'name': '2015 Barrow Atqasuk ITEX Thaw v1.csv',
            'packageParent': 'Thaw depth in the ITEX plots at Barrow and Atqasuk, Alaska',
            'size': 7770,
        }, {
            'id': 'urn:uuid:428fcb96-03a9-42b3-81d1-2944ac686e55',
            'name': '1995-20XX Barrow Atqasuk ITEX Thaw metadata - Copy.txt',
            'packageParent': 'Thaw depth in the ITEX plots at Barrow and Atqasuk, Alaska',
            'size': 3971,
        }, {
            'id': 'urn:uuid:bd7754a7-d4db-4217-8bf0-4c5d3691c0bc',
            'name': '2016 Barrow Atqasuk ITEX Thaw v1.csv',
            'packageParent': 'Thaw depth in the ITEX plots at Barrow and Atqasuk, Alaska',
            'size': 7439,
        }]]
        )
