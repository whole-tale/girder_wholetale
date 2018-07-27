from tests import base
from girder.api.rest import RestException
from girder.constants import ROOT_DIR
from girder.models.model_base import ValidationException

from d1_client.mnclient_2_0 import MemberNodeClient_2_0
from d1_common.types import dataoneTypes
import uuid


def setUpModule():

    base.enabledPlugins.append('wholetale')
    base.startServer()


def tearDownModule():
    base.stopServer()


class TestDataONEUpload(base.TestCase):

    def test_create_client(self):
        # Test that a client to a DataONE member node is being created
        from server.dataone_upload import create_client

        member_node='https://dev.nceas.ucsb.edu/knb/d1/mn/'
        header = {"headers": {
            "Authorization": "Bearer TOKEN"}}
        client = create_client(member_node, header)
        self.assertIsNotNone(client)


    def test_create_upload_eml(self):
        # Test for create_upload_eml that will generate metadata and attempt to upload it.
        # Note that the upload should not go thorugh, and we should catch an exception

        from server.dataone_upload import upload_file
        from server.dataone_upload import create_client
        from server.dataone_upload import create_upload_eml

        member_node = 'https://dev.nceas.ucsb.edu/knb/d1/mn/'
        header = {"headers": {
            "Authorization": "Bearer TOKEN"}}
        client = create_client(member_node, header)
        pid = str(uuid.uuid4())
        object = 'test data'
        tale = {'title': 'test_title', 'description': 'Test tale description'}
        user = {'lastName': 'testLastName', 'firstName': 'testFirstName'}

        self.assertRaises(ValidationException, create_upload_eml, tale, client, user, [], dict())

    def test_create_upload_resmap(self):
        # Test for create_upload_eml that will generate metadata and attempt to upload it.
        # Note that the upload should not go thorugh, and we should catch an exception

        from server.dataone_upload import create_upload_resmap
        from server.dataone_upload import create_client
        from server.dataone_upload import create_upload_eml

        member_node = 'https://dev.nceas.ucsb.edu/knb/d1/mn/'
        header = {"headers": {
            "Authorization": "Bearer TOKEN"}}
        client = create_client(member_node, header)
        res_pid = str(uuid.uuid4())
        eml_pid = str(uuid.uuid4())
        obj_pids =['12345', '54321']

        self.assertRaises(ValidationException,
                          create_upload_resmap,
                          res_pid,
                          eml_pid,
                          obj_pids,
                          client)
