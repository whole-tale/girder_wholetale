# -*- coding: utf-8 -*-

import datetime

from girder.models.model_base import \
    AccessControlledModel, ValidationException
from girder.constants import AccessType


_DEFAULT_ICON = ('https://raw.githubusercontent.com/whole-tale/dashboard/'
                 'd1914c9896c3e87a29601760ad7d0dfaa0d98ae2'
                 '/public/images/whole_tale_logo.png')


class Image(AccessControlledModel):

    def initialize(self):
        self.name = 'image'
        self.ensureIndices(
            ('parentId', 'name', ([('parentId', 1), ('name', 1)], {}))
        )
        self.ensureTextIndex({
            'name': 10,
            'description': 1
        })
        self.exposeFields(
            level=AccessType.READ,
            fields={'_id', 'config', 'created', 'creatorId', 'description',
                    'icon', 'iframe', 'name', 'updated', 'name', 'parentId',
                    'public', 'tags', 'idleTimeout'}
        )

    def validate(self, image):
        if image is None:
            raise ValidationException('Bogus validation')
        if 'iframe' not in image:
            image['iframe'] = False
        return image

    def createImage(self, name=None, tags=None,
                    creator=None, save=True, parent=None, description=None,
                    public=None, config=None, icon=None, iframe=None, idleTimeout=None):

        # TODO: check for existing image based on name

        if creator is None:
            creatorId = None
        else:
            creatorId = creator.get('_id', None)

        if parent is not None:
            parentId = parent['_id']
        else:
            parentId = None

        if iframe is None or not isinstance(iframe, bool):
            iframe = False

        now = datetime.datetime.utcnow()
        image = {
            'config': config,
            'created': now,
            'creatorId': creatorId,
            'description': description,
            'icon': icon or _DEFAULT_ICON,
            'iframe': iframe,
            'name': name,
            'parentId': parentId,
            'public': public,
            'tags': tags,
            'updated': now,
        }
        if idleTimeout:
            image['idleTimeout'] = idleTimeout

        if public is not None and isinstance(public, bool):
            self.setPublic(image, public, save=False)
        if creator is not None:
            self.setUserAccess(image, user=creator, level=AccessType.ADMIN,
                               save=False)
        if save:
            image = self.save(image)
        return image

    def updateImage(self, image):
        """
        Updates a image.

        :param image: The image document to update.
        :type image: dict
        :returns: The image document that was edited.
        """
        image['updated'] = datetime.datetime.utcnow()
        return self.save(image)

    def setAccessList(self, doc, access, save=False, user=None, force=False,
                      setPublic=None, publicFlags=None):
        """
        Overrides AccessControlledModel.setAccessList to encapsulate ACL
        functionality for an image.

        :param doc: the image to set access settings on
        :type doc: girder.models.image
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

        doc = AccessControlledModel.setAccessList(self, doc, access,
                                                  user=user, save=save, force=force)

        return doc
