import pytest
import json
import os
from tests import base
from girder.api.rest import RestException
from girder.constants import ROOT_DIR

'''Tests for the methods in dataone_register.py. Some of these tests use live requests,
while others use mocked JSON responses/data structures.'''


def setUpModule():
    base.enabledPlugins.append('wholetale')
    base.startServer()


def tearDownModule():
    base.stopServer()


class TestDataONERegister(base.TestCase):

    def test_find_initial_pid(self):
        from server.dataone_register import find_initial_pid

        # Test that the regex is working for search.dataone urls
        pid = 'https://search.dataone.org/#view/urn:uuid:7ec733c4-aa63-405a-a58d-1d773a9025a9'
        res = find_initial_pid(pid)
        self.assertEqual (res,'urn:uuid:7ec733c4-aa63-405a-a58d-1d773a9025a9')

        # Test that the regex is working for paths coming from the coordinating node v2
        pid = 'https://cn.dataone.org/cn/v2/object/urn:uuid:6f5533ab-6508-4ac7-82a3-1df88ed4580e'
        res = find_initial_pid(pid)
        self.assertEqual(res, 'urn:uuid:6f5533ab-6508-4ac7-82a3-1df88ed4580e')

        # Test that the regex is working for paths coming from the coordinating node v1
        pid = 'https://cn.dataone.org/cn/v1/object/urn:uuid:6f5533ab-6508-4ac7-82a3-1df88ed4580e'
        res = find_initial_pid(pid)
        self.assertEqual(res, 'urn:uuid:6f5533ab-6508-4ac7-82a3-1df88ed4580e')

        # Test that the regex works for the test coordinating node
        pid = 'https://cn-stage-2.test.dataone.org/cn/v2/resolve/abcdefg'
        res = find_initial_pid(pid)
        self.assertEqual(res, 'abcdefg')

        # Test that the regex works for the test coordinating node V1
        pid = 'https://cn-stage-2.test.dataone.org/cn/v1/resolve/abcdefg'
        res = find_initial_pid(pid)
        self.assertEqual(res, 'abcdefg')

        # Test that the regex works for the production node
        pid = 'https://cn.dataone.org/cn/v2/resolve/abcdefg'
        res = find_initial_pid(pid)
        self.assertEqual(res, 'abcdefg')

        # Test that if nothing was found, the passed in path is returned
        bad_url = 'localhost_01'
        res = find_initial_pid(bad_url)
        self.assertEqual(res, bad_url)

    def test_find_resource_pid(self):
        from server.dataone_register import find_resource_pid
        from server.constants import DataONELocations

        # Test the case where no data object could be located
        with pytest.raises(RestException):
            bad_url = 'localhost_01'
            find_resource_pid(bad_url, DataONELocations.prod_cn)

    def test_get_package_files_metadata(self):
        """Test that the metadata in a package is getting added to the list of files"""
        from server.dataone_register import get_package_files

        full_meta_data = [{
            'identifier': 'urn:uuid:f438a8d5-7965-4ca2-aad6-88f694e5afe5',
            'fileName': 'iso19139.xml', 'formatId': 'http://www.isotc211.org/2005/gmd',
            'formatType': 'METADATA', 'size': 14735,
            'title': ('Collaborative Research: A Synthesis of Existing and '
                      'New Observations of Air-Snowpack Exchanges to Assess the Arctic'),
            'documents': [
                'urn:uuid:f438a8d5-7965-4ca2-aad6-88f694e5afe5',
                'resource_map_urn:uuid:23acf3bd-27c7-4736-a6ef-c141698d66b8',
                'resource_map_urn:uuid:1570fb91-69e8-4c1d-9b9a-292edb5820af'
            ]
        }]

        data = []

        expected_result = {'iso19139.xml': {'size': 14735}}

        # In this case, the primary metadata object is the same as the metadata object
        fileList = get_package_files(data, full_meta_data, full_meta_data)
        self.assertDictEqual(fileList, expected_result)

    def test_get_package_files(self):
        """
        Test that the files in a package are getting correctly parsed. This is tested on
        https://search.dataone.org/#view/urn:uuid:15403304-6eb8-4ede-8a56-332a3e92bef8
        """
        from server.dataone_register import get_package_files
        from server.constants import DataONELocations

        data = [{'identifier': 'urn:uuid:4eb73500-fa9b-46c2-a517-94c1a8b4afbb',
                 'fileName': 'HumanFootprint.ipynb', 'formatId': 'text/plain',
                 'formatType': 'DATA', 'size': 104524},
                {'identifier': 'urn:uuid:06544a24-aae8-4b80-be4b-bb03711d9fd0',
                 'fileName': 'hfp_regions.csv', 'formatId': 'text/csv',
                 'formatType': 'DATA', 'size': 1757}]

        meta_data = [{
            'identifier': 'urn:uuid:15403304-6eb8-4ede-8a56-332a3e92bef8',
            'fileName': 'HumanFootprint_SASAP.xml',
            'formatId': 'eml://ecoinformatics.org/eml-2.1.1',
            'formatType': 'METADATA', 'size': 18648,
            'title': 'Global terrestrial Human Footprint maps for Alaska, 1993 and 2009,'
                     'with SASAP regional subsetting',
            'documents': ['urn:uuid:15403304-6eb8-4ede-8a56-332a3e92bef8',
                          'urn:uuid:4eb73500-fa9b-46c2-a517-94c1a8b4afbb',
                          'urn:uuid:06544a24-aae8-4b80-be4b-bb03711d9fd0']
        }]

        expected_result = {
            'HumanFootprint.ipynb': {'size': 104524},
            'hfp_regions.csv': {'size': 1757},
            'HumanFootprint_SASAP.xml': {'size': 18648}
        }

        fileList = get_package_files(data, meta_data, meta_data)

        self.assertDictEqual(fileList, expected_result)

    def test_check_multiple_maps_empty(self):
        """Test that we get an exception when no map was found."""
        from server.dataone_register import check_multiple_maps

        with pytest.raises(RestException):
            metadata = set()
            check_multiple_maps(metadata)

    def test_get_package_list_nested(self):
        # Test that we're getting all of the files in a nested package
        from server.dataone_register import get_package_list
        from server.constants import DataONELocations

        package = get_package_list("https://search.dataone.org/#view/urn:uuid:6f5533ab-6508-4ac7-82a3-1df88ed4580e",
                                   DataONELocations.prod_cn)

        # Metadata that should be returned
        fname = os.path.join(ROOT_DIR, 'plugins', 'wholetale', 'plugin_tests',
                             'dataone_register_test01.json')
        with open(fname, 'r') as fp:
            expected_result = json.load(fp)

        self.assertDictEqual(package, expected_result)

    def test_get_package_list_flat(self):
        # Test that we're getting all of the files in a non-nested package
        from server.dataone_register import get_package_list
        from server.constants import DataONELocations

        package = get_package_list('https://search.dataone.org/#view/urn:uuid:7ec733c4-aa63-405a-a58d-1d773a9025a9',
                                   DataONELocations.prod_cn)
        expected_result ={
            "Doctoral Dissertation Research: Mapping Community Exposure to Coastal Climate Hazards in the Arctic:"
             " A Case Study in Alaska's North Slope":
                 {'fileList':
                      [{'science_metadata.xml':
                            {'size': 8961}}],
                  'Arctic Slope Shoreline Change Risk Spatial Data Model, 2015-16':
                      {'fileList': [{'science_metadata.xml':
                                         {'size': 7577}}]},
                  'North Slope Borough shoreline change risk WebGIS usability workshop.':
                      {'fileList':
                           [{'science_metadata.xml':
                                 {'size': 7940}}]},
                  'Local community verification of shoreline change risks along the Alaskan Arctic Ocean coast'
                  ' (North Slope).':
                      {'fileList':
                           [{'science_metadata.xml':
                                 {'size': 14250}}]},
                  'Arctic Slope Shoreline Change Susceptibility Spatial Data Model, 2015-16':
                      {'fileList': [{'science_metadata.xml':
                                         {'size': 10491}}]}}}

        self.assertDictEqual(package, expected_result)
