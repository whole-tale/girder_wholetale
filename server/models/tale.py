# -*- coding: utf-8 -*-

import datetime

from bson.objectid import ObjectId

from ..constants import WORKSPACE_NAME, DATADIRS_NAME, SCRIPTDIRS_NAME
from ..utils import getOrCreateRootFolder
from ..lib.license import WholeTaleLicense
from girder.models.model_base import AccessControlledModel
from girder.models.item import Item
from girder.models.folder import Folder
from girder.constants import AccessType
from girder.exceptions import AccessException


# Whenever the Tale object schema is modified (e.g. fields are added or
# removed) increase `_currentTaleFormat` to retroactively apply those
# changes to existing Tales.
_currentTaleFormat = 6


class Tale(AccessControlledModel):

    def initialize(self):
        self.name = 'tale'
        self.ensureIndices(('imageId', ([('imageId', 1)], {})))
        self.ensureTextIndex({
            'title': 10,
            'description': 1
        })
        self.modifiableFields = {
            'title', 'description', 'public', 'config', 'updated', 'authors',
            'category', 'icon', 'iframe', 'illustration', 'dataSet', 'licenseSPDX',
            'workspaceModified', 'publishInfo'
        }
        self.exposeFields(
            level=AccessType.READ,
            fields=({'_id', 'folderId', 'imageId', 'creatorId', 'created',
                     'format', 'dataSet', 'narrative', 'narrativeId', 'licenseSPDX',
                     'imageInfo', 'publishInfo', 'workspaceId',
                     'workspaceModified'} | self.modifiableFields))

    def validate(self, tale):
        if 'iframe' not in tale:
            tale['iframe'] = False

        if '_id' not in tale:
            return tale

        if 'publishInfo' not in tale:
            tale['publishInfo'] = []

        if 'dataSet' not in tale:
            tale['dataSet'] = []

        if 'licenseSPDX' not in tale:
            tale['licenseSPDX'] = WholeTaleLicense.default_spdx()
        tale_licenses = WholeTaleLicense()
        if tale['licenseSPDX'] not in tale_licenses.supported_spdxes():
            tale['licenseSPDX'] = WholeTaleLicense.default_spdx()

        if tale.get('config') is None:
            tale['config'] = {}

        return tale

    def list(self, user=None, data=None, image=None, limit=0, offset=0,
             sort=None, currentUser=None, level=AccessType.READ):
        """
        List a page of jobs for a given user.

        :param user: The user who created the tale.
        :type user: dict or None
        :param data: The object array that's being used by the tale.
        :type data: dict or None
        :param image: The Image that's being used by the tale.
        :type image: dict or None
        :param limit: The page limit.
        :param offset: The page offset
        :param sort: The sort field.
        :param currentUser: User for access filtering.
        """
        cursor_def = {}
        if user is not None:
            cursor_def['creatorId'] = user['_id']
        if data is not None:
            cursor_def['dataSet'] = data
        if image is not None:
            cursor_def['imageId'] = image['_id']

        cursor = self.find(cursor_def, sort=sort)
        for r in self.filterResultsByPermission(
                cursor=cursor, user=currentUser, level=level,
                limit=limit, offset=offset):
            yield r

    def createTale(self, image, data, creator=None, save=True, title=None,
                   description=None, public=None, config=None, authors=None,
                   icon=None, category=None, illustration=None, narrative=None,
                   licenseSPDX=WholeTaleLicense.default_spdx()):

        if creator is None:
            creatorId = None
        else:
            creatorId = creator.get('_id', None)

        if title is None:
            title = '{} with {}'.format(image['name'], DATADIRS_NAME)
        # if illustration is None:
            # Get image from SILS

        now = datetime.datetime.utcnow()
        tale = {
            'authors': authors,
            'category': category,
            'config': config or {},
            'creatorId': creatorId,
            'dataSet': data or [],
            'description': description,
            'format': _currentTaleFormat,
            'created': now,
            'icon': icon,
            'iframe': image.get('iframe', False),
            'imageId': ObjectId(image['_id']),
            'illustration': illustration,
            'narrative': narrative or [],
            'title': title,
            'public': public,
            'updated': now,
            'licenseSPDX': licenseSPDX
        }
        if public is not None and isinstance(public, bool):
            self.setPublic(tale, public, save=False)
        else:
            public = False

        if creator is not None:
            self.setUserAccess(tale, user=creator, level=AccessType.ADMIN,
                               save=False)
        if save:
            tale = self.save(tale)
            workspace = self.createWorkspace(tale, creator=creator)
            data_folder = self.createDataMountpoint(tale, creator=creator)
            tale['folderId'] = data_folder['_id']
            tale['workspaceId'] = workspace['_id']
            narrative_folder = self.createNarrativeFolder(
                tale, creator=creator, default=not bool(tale['narrative']))
            for obj_id in tale['narrative']:
                item = Item().load(obj_id, user=creator)
                Item().copyItem(item, creator, folder=narrative_folder)
            tale['narrativeId'] = narrative_folder['_id']
            tale = self.save(tale)
        return tale

    def createNarrativeFolder(self, tale, creator=None, default=False):
        if default:
            rootFolder = getOrCreateRootFolder(SCRIPTDIRS_NAME)
            auxFolder = self.model('folder').createFolder(
                rootFolder, 'default', parentType='folder',
                public=True, reuseExisting=True)
        else:
            auxFolder = self._createAuxFolder(
                tale, SCRIPTDIRS_NAME, creator=creator)
        return auxFolder

    def createDataMountpoint(self, tale, creator=None):
        return self._createAuxFolder(tale, DATADIRS_NAME, creator=creator)

    def createWorkspace(self, tale, creator=None):
        return self._createAuxFolder(tale, WORKSPACE_NAME, creator=creator)

    def _createAuxFolder(self, tale, rootFolderName, creator=None):
        if creator is None:
            creator = self.model('user').load(tale['creatorId'], force=True)

        if tale['public'] is not None and isinstance(tale['public'], bool):
            public = tale['public']
        else:
            public = False

        rootFolder = getOrCreateRootFolder(rootFolderName)
        auxFolder = self.model('folder').createFolder(
            rootFolder, str(tale['_id']), parentType='folder',
            public=public, reuseExisting=True)
        self.setUserAccess(
            auxFolder, user=creator, level=AccessType.ADMIN,
            save=True)
        auxFolder = self.model('folder').setMetadata(
            auxFolder, {'taleId': str(tale['_id'])})
        return auxFolder

    def updateTale(self, tale):
        """
        Updates a tale.

        :param tale: The tale document to update.
        :type tale: dict
        :returns: The tale document that was edited.
        """
        tale['updated'] = datetime.datetime.utcnow()
        return self.save(tale)

    def setAccessList(self, doc, access, save=False, user=None, force=False,
                      setPublic=None, publicFlags=None):
        """
        Overrides AccessControlledModel.setAccessList to encapsulate ACL
        functionality for a tale.

        :param doc: the tale to set access settings on
        :type doc: girder.models.tale
        :param access: The access control list
        :type access: dict
        :param save: Whether the changes should be saved to the database
        :type save: bool
        :param user: The current user
        :param force: Set this to True to set the flags regardless of the passed in
            user's permissions.
        :type force: bool
        :param setPublic: Pass this if you wish to set the public flag on the
            resources being updated.
        :type setPublic: bool or None
        :param publicFlags: Pass this if you wish to set the public flag list on
            resources being updated.
        :type publicFlags: flag identifier str, or list/set/tuple of them,
            or None
        """
        if setPublic is not None:
            self.setPublic(doc, setPublic, save=False)

        if publicFlags is not None:
            doc = self.setPublicFlags(doc, publicFlags, user=user, save=False,
                                      force=force)

        doc = super().setAccessList(
            doc, access, user=user, save=save, force=force)

        for id_key in ('folderId', 'workspaceId', 'narrativeId'):
            try:
                folder = Folder().load(doc[id_key], user=user, level=AccessType.ADMIN)
            except AccessException:
                _folder = Folder().load(doc[id_key], force=True)
                if id_key != 'narrativeId' or _folder['name'] != 'default':
                    raise
                folder = None

            if folder:
                Folder().setAccessList(
                    folder, access, user=user, save=save, force=force, recurse=True,
                    setPublic=setPublic, publicFlags=publicFlags)

        return doc
