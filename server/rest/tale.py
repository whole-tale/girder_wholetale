#!/usr/bin/env python
# -*- coding: utf-8 -*-
import cherrypy
import json
import os
import pathlib
from urllib.parse import urlparse
from girder import events
from girder.api import access
from girder.api.rest import iterBody
from girder.api.docs import addModel
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import Resource, filtermodel, RestException,\
    setResponseHeader, setContentDisposition

from girder.constants import AccessType, SortDir, TokenScope
from girder.models.folder import Folder
from girder.models.user import User
from girder.models.token import Token
from girder.models.setting import Setting
from girder.plugins.jobs.models.job import Job
from gwvolman.tasks import publish

from girder.plugins.jobs.constants import JobStatus

from ..schema.tale import taleModel as taleSchema
from ..models.tale import Tale as taleModel
from ..models.image import Image as imageModel
from ..models.instance import Instance
from ..lib import pids_to_entities, IMPORT_PROVIDERS
from ..lib.dataone import DataONELocations  # TODO: get rid of it
from ..lib.manifest import Manifest
from ..lib.exporters.bag import BagTaleExporter
from ..lib.exporters.native import NativeTaleExporter
from ..utils import notify_event, init_progress

from girder.plugins.worker import getCeleryApp

from ..constants import ImageStatus, TaleStatus, PluginSettings, \
    DEFAULT_IMAGE_ICON, DEFAULT_ILLUSTRATION


addModel('tale', taleSchema, resources='tale')


class Tale(Resource):

    def __init__(self):
        super(Tale, self).__init__()
        self.resourceName = 'tale'
        self._model = taleModel()

        self.route('GET', (), self.listTales)
        self.route('GET', (':id',), self.getTale)
        self.route('PUT', (':id',), self.updateTale)
        self.route('POST', ('import', ), self.createTaleFromUrl)
        self.route('POST', (), self.createTale)
        self.route('POST', (':id', 'copy'), self.copyTale)
        self.route('DELETE', (':id',), self.deleteTale)
        self.route('GET', (':id', 'access'), self.getTaleAccess)
        self.route('PUT', (':id', 'access'), self.updateTaleAccess)
        self.route('PUT', (':id', 'git'), self.updateTaleWithGitRepo)
        self.route('GET', (':id', 'export'), self.exportTale)
        self.route('GET', (':id', 'manifest'), self.generateManifest)
        self.route('PUT', (':id', 'build'), self.buildImage)
        self.route('PUT', (':id', 'publish'), self.publishTale)
        self.route('PUT', (':id', 'relinquish'), self.relinquishTaleAccess)

    @access.public
    @filtermodel(model='tale', plugin='wholetale')
    @autoDescribeRoute(
        Description('Return all the tales accessible to the user')
        .param('text', ('Perform a full text search for Tale with a matching '
                        'title or description.'), required=False)
        .param('userId', "The ID of the tale's creator.", required=False)
        .param('imageId', "The ID of the tale's image.", required=False)
        .param(
            'level',
            'The minimum access level to the Tale.',
            required=False,
            dataType='integer',
            default=AccessType.READ,
            enum=[AccessType.NONE, AccessType.READ, AccessType.WRITE, AccessType.ADMIN],
        )
        .pagingParams(defaultSort='title',
                      defaultSortDir=SortDir.DESCENDING)
        .responseClass('tale', array=True)
    )
    def listTales(self, text, userId, imageId, level, limit, offset, sort,
                  params):
        currentUser = self.getCurrentUser()
        image = None
        if imageId:
            image = imageModel().load(imageId, user=currentUser, level=AccessType.READ, exc=True)

        creator = None
        if userId:
            creator = self.model('user').load(userId, force=True, exc=True)

        if text:
            filters = {}
            if creator:
                filters['creatorId'] = creator['_id']
            if image:
                filters['imageId'] = image['_id']
            return list(self._model.textSearch(
                text, user=currentUser, filters=filters,
                limit=limit, offset=offset, sort=sort, level=level))
        else:
            return list(self._model.list(
                user=creator, image=image, limit=limit, offset=offset,
                sort=sort, currentUser=currentUser, level=level))

    @access.public
    @filtermodel(model='tale', plugin='wholetale')
    @autoDescribeRoute(
        Description('Get a tale by ID.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.READ)
        .responseClass('tale')
        .errorResponse('ID was invalid.')
        .errorResponse('Read access was denied for the tale.', 403)
    )
    def getTale(self, tale, params):
        # TODO: This a temporary abomination.
        # We are adding contents of tale's data dir on the fly
        return self._model.updateDataSet(tale, self.getCurrentUser())

    @access.user
    @filtermodel(model='tale', plugin='wholetale')
    @autoDescribeRoute(
        Description('Update an existing tale.')
        .modelParam('id', model='tale', plugin='wholetale',
                    level=AccessType.WRITE, destName='taleObj')
        .jsonParam('tale', 'Updated tale', paramType='body', schema=taleSchema,
                   dataType='tale')
        .responseClass('tale')
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def updateTale(self, taleObj, tale, params):
        is_public = tale.pop('public')
        user = self.getCurrentUser()
        old_dataset = {(_['itemId'], _["_modelType"]) for _ in taleObj['dataSet']}
        new_dataset = {(_['itemId'], _["_modelType"]) for _ in tale['dataSet']}
        update_citations = old_dataset ^ new_dataset  # XOR between new and old dataSet

        if "dataDirId" not in tale:
            tale["dataDirId"] = taleObj["dataDirId"]
        self._model.updateDataSet(
            tale, user, new_ds=tale["dataSet"]
        )
        ds = tale.pop("dataSet")  # Do not store it in db

        new_imageId = tale.pop("imageId")
        if new_imageId != str(taleObj["imageId"]):
            image = imageModel().load(
                new_imageId, user=user,
                level=AccessType.READ, exc=True)
            taleObj["imageId"] = image["_id"]
            tale["icon"] = image["icon"]  # Has to be consistent...

        for keyword in self._model.modifiableFields:
            try:
                taleObj[keyword] = tale.pop(keyword)
            except KeyError:
                pass
        taleObj = self._model.updateTale(taleObj)

        was_public = taleObj.get('public', False)
        if was_public != is_public:
            access = self._model.getFullAccessList(taleObj)
            user = self.getCurrentUser()
            taleObj = self._model.setAccessList(
                taleObj, access, save=True, user=user, setPublic=is_public)

        taleObj["dataSet"] = ds  # Do not store it in db
        if update_citations:
            eventParams = {
                'tale': taleObj,
                'user': self.getCurrentUser(),
            }
            events.daemon.trigger('tale.update_citation', eventParams)
        return taleObj

    @access.user
    @autoDescribeRoute(
        Description('Delete an existing tale.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.ADMIN)
        .param("force", "If instances for the Tale exist, they will be shutdown",
               default=False, required=False, dataType="boolean")
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
        .errorResponse("This Tale has running Instances.", 409)
    )
    def deleteTale(self, tale, force):
        instances = Instance().find({"taleId": tale["_id"]})
        if instances.count() > 0 and not force:
            raise RestException("This Tale has running Instances.", 409)

        # Shutdown any running Instance
        for instance in instances:
            instance_creator = User().load(instance["creatorId"], force=True)
            Instance().deleteInstance(instance, instance_creator)
        self._model.remove(tale)
        users = [str(user["id"]) for user in tale["access"]["users"]]
        notify_event(users, "wt_tale_removed", {"taleId": str(tale["_id"])})

    @access.user
    @filtermodel(model='tale', plugin='wholetale')
    @autoDescribeRoute(
        Description('Create a new tale from an external dataset.')
        .notes('Currently, this task only handles importing raw data. '
               'A serialized Tale can be sent as the body of the request using an '
               'appropriate content-type and with the other parameters as part '
               'of the query string. The file will be stored in a temporary '
               'space. However, it is not currently being processed in any '
               'way.')
        .param('imageId', "The ID of the tale's image.", required=False)
        .param('url', 'External dataset identifier.', required=False)
        .param('spawn', 'If false, create only Tale object without a corresponding '
                        'Instance.',
               default=True, required=False, dataType='boolean')
        .param('asTale', 'If True, assume that external dataset is a Tale.',
               default=False, required=False, dataType='boolean')
        .param('git', "If True, treat the url as a location of a git repo "
               "that should be imported as the Tale's workspace.",
               default=False, required=False, dataType='boolean')
        .jsonParam('lookupKwargs', 'Optional keyword arguments passed to '
                   'GET /repository/lookup', requireObject=True, required=False)
        .jsonParam('taleKwargs', 'Optional keyword arguments passed to POST /tale',
                   required=False, default=None)
        .responseClass('tale')
        .errorResponse('You are not authorized to create tales.', 403)
    )
    def createTaleFromUrl(self, imageId, url, spawn, asTale, git, lookupKwargs, taleKwargs):
        user = self.getCurrentUser()
        if taleKwargs is None:
            taleKwargs = {}

        if cherrypy.request.headers.get('Content-Type') == 'application/zip':
            tale = taleModel().createTaleFromStream(iterBody, user=user)
        else:
            if not url:
                msg = (
                    "You need to provide either : "
                    " 1) a zipfile with an exported Tale or "
                    " 2) a url to a Tale or "
                    " 3) both 'imageId' and 'url' parameters."
                )
                raise RestException(msg)

            try:
                lookupKwargs['dataId'] = [url]
            except TypeError:
                lookupKwargs = dict(dataId=[url])

            if not git:
                dataMap = pids_to_entities(
                    lookupKwargs["dataId"],
                    user=user,
                    base_url=lookupKwargs.get("base_url", DataONELocations.prod_cn),
                    lookup=True
                )[0]
                provider = IMPORT_PROVIDERS.providerMap[dataMap["repository"]]

                if dataMap["tale"]:  # url points to a published Tale
                    return provider.import_tale(dataMap["dataId"], user)

                proto_tale = provider.proto_tale_from_datamap(dataMap, asTale)
            else:
                git_url = urlparse(url)
                if git_url.netloc == "github.com":
                    name = "/".join(pathlib.Path(git_url.path).parts[1:3])
                    title = f"A Tale for \"gh:{name}\""
                else:
                    title = f"A Tale for \"{url}\""
                proto_tale = {
                    "category": "science",
                    "relatedIdentifiers": [{"relation": "IsSupplementTo", "identifier": url}],
                    "title": title,
                }

            if "title" in taleKwargs and "title" in proto_tale:
                proto_tale.pop("title")

            all_related_ids = proto_tale.pop("relatedIdentifiers") + \
                taleKwargs.get("relatedIdentifiers", [])
            taleKwargs["relatedIdentifiers"] = [
                json.loads(rel_id)
                for rel_id in {json.dumps(_, sort_keys=True) for _ in all_related_ids}
            ]

            taleKwargs.update(proto_tale)

            if not (imageId or url):
                msg = (
                    "You need to provide either a zipfile with an exported Tale or "
                    " both 'imageId' and 'url' parameters."
                )
                raise RestException(msg)

            image = imageModel().load(imageId, user=user, level=AccessType.READ,
                                      exc=True)

            taleKwargs.setdefault("icon", image.get("icon", DEFAULT_IMAGE_ICON))
            taleKwargs.setdefault("illustration", DEFAULT_ILLUSTRATION)

            tale = taleModel().createTale(
                image,
                [],
                creator=user,
                save=True,
                public=False,
                status=TaleStatus.PREPARING,
                **taleKwargs
            )

            if not git:
                resource = {
                    "type": "wt_import_binder",
                    "tale_id": tale["_id"],
                    "tale_title": tale["title"]
                }
                total = 2 + int(spawn)
                notification = init_progress(
                    resource, user, "Importing Tale", "Initializing", total
                )

                job = Job().createLocalJob(
                    title="Import Tale from external dataset",
                    user=user,
                    type="wholetale.import_binder",
                    public=False,
                    _async=True,
                    module="girder.plugins.wholetale.tasks.import_binder",
                    args=(lookupKwargs,),
                    kwargs={"taleId": tale["_id"], "spawn": spawn, "asTale": asTale},
                    otherFields={
                        "taleId": tale["_id"],
                        "wt_notification_id": str(notification["_id"])
                    }
                )
                Job().scheduleJob(job)
            else:
                tale = self._model.addGitRepo(
                    tale,
                    url,
                    user=user,
                    spawn=spawn,
                    change_status=True,
                    title="Importing git repo as a Tale"
                )
        return tale

    @access.user
    @filtermodel(model="tale", plugin="wholetale")
    @autoDescribeRoute(
        Description('Create a new tale.')
        .jsonParam('tale', 'A new tale', paramType='body', schema=taleSchema,
                   dataType='tale')
        .responseClass('tale')
        .errorResponse('You are not authorized to create tales.', 403)
    )
    def createTale(self, tale, params):
        user = self.getCurrentUser()
        image = self.model("image", "wholetale").load(
            tale["imageId"], user=user, level=AccessType.READ, exc=True
        )
        default_authors = [
            dict(
                firstName=user["firstName"],
                lastName=user["lastName"],
                orcid="https://orcid.org/0000-0000-0000-0000"
            )
        ]

        kwargs = {
            "title": tale.get("title"),
            "description": tale.get("description") or "",
            "config": tale.get("config") or {},
            "public": tale.get("public") or False,
            "icon": image.get("icon") or DEFAULT_IMAGE_ICON,
            "illustration": tale.get("illustration") or DEFAULT_ILLUSTRATION,
            "authors": tale.get("authors", []) or default_authors,
            "category": tale.get("category") or "science",
            "licenseSPDX": tale.get("licenseSPDX"),
            "relatedIdentifiers": tale.get("relatedIdentifiers") or [],
        }
        return self._model.createTale(
            image, tale["dataSet"], creator=user, save=True, **kwargs
        )

    @access.user(scope=TokenScope.DATA_WRITE)
    @autoDescribeRoute(
        Description('Get the access control list for a tale')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.WRITE)
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def getTaleAccess(self, tale):
        return self._model.getFullAccessList(tale)

    @access.user(scope=TokenScope.DATA_OWN)
    @autoDescribeRoute(
        Description('Update the access control list for a tale.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.ADMIN)
        .jsonParam('access', 'The JSON-encoded access control list.', requireObject=True)
        .jsonParam('publicFlags', 'JSON list of public access flags.', requireArray=True,
                   required=False)
        .param('public', 'Whether the tale should be publicly visible.', dataType='boolean',
               required=False)
        .param("force", "If instances for the Tale exist, they will be shutdown",
               default=False, required=False, dataType="boolean")
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
        .errorResponse("This Tale has running Instances.", 409)
    )
    def updateTaleAccess(self, tale, access, publicFlags, public, force):
        user = self.getCurrentUser()
        orig_access = tale["access"]
        tale = self._model.setAccessList(
            tale, access, save=False, user=user, setPublic=public, publicFlags=publicFlags)

        instances_to_kill = []
        for instance in Instance().find({"taleId": tale["_id"]}):
            creator = User().load(instance["creatorId"], force=True)
            if not self._model.hasAccess(tale, user=creator, level=AccessType.WRITE):
                instances_to_kill.append((instance, creator))

        if instances_to_kill and not force:
            raise RestException("This Tale has running Instances.", 409)

        for instance, creator in instances_to_kill:
            Instance().deleteInstance(instance, creator)

        tale["access"] = orig_access  # For notifications
        return self._model.setAccessList(
            tale, access, save=True, user=user, setPublic=public, publicFlags=publicFlags)

    @access.user(scope=TokenScope.DATA_READ)
    @autoDescribeRoute(
        Description('Remove or decrease the level of user access to a tale.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.READ)
        .param(
            "level", "New access level. Must be lower than current.",
            enum=[AccessType.WRITE, AccessType.READ, AccessType.NONE],
            default=AccessType.NONE,
            dataType="integer",
        )
        .param("force", "If instances for the Tale exist, they will be shutdown",
               default=False, required=False, dataType="boolean")
        .errorResponse("No content (Tale access level set to NONE)", 204)
        .errorResponse("ID was invalid.")
        .errorResponse("Access was denied for the tale.", 403)
        .errorResponse("Request to increase access level was denied.", 403)
        .errorResponse("This Tale has running Instances.", 409)
    )
    def relinquishTaleAccess(self, tale, level, force):
        user = self.getCurrentUser()
        if level > self._model.filter(tale, user)["_accessLevel"]:
            raise RestException("Request to increase access level was denied.", 403)

        updated_tale = self._model.setUserAccess(tale, user, level, save=False)
        instances_to_kill = []
        for instance in Instance().find({"taleId": tale["_id"], "creatorId": user["_id"]}):
            if not self._model.hasAccess(updated_tale, user=user, level=AccessType.WRITE):
                instances_to_kill.append(instance)

        if len(instances_to_kill) > 0 and not force:
            raise RestException("This Tale has running Instances.", 409)

        for instance in instances_to_kill:
            Instance().deleteInstance(instance, user)
        tale = self._model.setUserAccess(tale, user, level, save=True)

        if level > AccessType.NONE:
            return self._model.filter(tale, user)
        cherrypy.response.status = 204

    @staticmethod
    def _get_version(user, tale, versionId):
        """Return a version object for a valid versionId, or the last version otherwise."""
        if not versionId:
            version_root = Folder().load(tale["versionsRootId"], user=user, level=AccessType.READ)
            return next(
                Folder().childFolders(
                    version_root,
                    "folder",
                    user=user,
                    limit=1,
                    offset=0,
                    sort=[("updated", SortDir.DESCENDING)],
                )
            )
        else:
            return Folder().load(versionId, user=user, level=AccessType.READ)

    @access.user
    @autoDescribeRoute(
        Description('Export a tale as a zipfile')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.READ)
        .param('taleFormat', 'Format of the exported Tale', required=False,
               enum=['bagit', 'native'], strip=True, default='native')
        .param('versionId', 'Specific version to export', required=False)
        .responseClass('tale')
        .produces('application/zip')
        .errorResponse('ID was invalid.', 404)
        .errorResponse('You are not authorized to export this tale.', 403)
    )
    def exportTale(self, tale, taleFormat, versionId):
        user = self.getCurrentUser()
        version = self._get_version(user, tale, versionId)

        # Get the manifest for the version, which may contain recorded run information
        manifest_doc = Manifest(
            tale, self.getCurrentUser(), expand_folders=True, versionId=version["_id"]
        )
        data_dir = self._model.getDataDir(tale, user, versionId=versionId)

        with open(os.path.join(version["fsPath"], "environment.json"), "r") as fp:
            environment = json.load(fp)

        if taleFormat == 'bagit':
            export_func = BagTaleExporter
        elif taleFormat == 'native':
            export_func = NativeTaleExporter

        exporter = export_func(user, manifest_doc.manifest, environment, data_dir)
        setResponseHeader('Content-Type', 'application/zip')
        setContentDisposition(f"{version['_id']}.zip")
        return exporter.stream

    @access.public
    @autoDescribeRoute(
        Description('Generate the Tale manifest')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.READ)
        .param('expandFolders', "If True, folders in Tale's dataSet are recursively "
               "expanded to items in the 'aggregates' section",
               required=False, dataType='boolean', default=True)
        .param(
            "versionId", "The specific Tale version that the manifest describes", required=False
        )
        .errorResponse('ID was invalid.')
    )
    def generateManifest(self, tale, expandFolders, versionId):
        """
        Creates a manifest document and returns the contents.
        :param tale: The Tale whose information is being used
        :param itemIds: An optional list of items to include in the manifest
        :return: A JSON structure representing the Tale
        """
        user = self.getCurrentUser()
        tale = self._model.updateDataSet(tale, user)
        manifest_doc = Manifest(
            tale, user, expand_folders=expandFolders, versionId=versionId
        )
        return manifest_doc.manifest

    @access.user
    @autoDescribeRoute(
        Description('Build the image for the Tale')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.WRITE,
                    description='The ID of the Tale.')
        .param('force', 'If true, force build regardless of workspace changes',
               default=False, required=False, dataType='boolean')
        .errorResponse('ID was invalid.')
        .errorResponse('Admin access was denied for the tale.', 403)
    )
    def buildImage(self, tale, force):
        user = self.getCurrentUser()
        return self._model.buildImage(tale, user, force=force)

    def updateBuildStatus(self, event):
        """
        Event handler that updates the Tale object based on the build_tale_image task.
        """
        job = event.info['job']
        if job['title'] == 'Build Tale Image' and job.get('status') is not None:
            status = int(job['status'])
            tale = self.model('tale', 'wholetale').load(
                job['args'][0], force=True)

            if 'imageInfo' not in tale:
                tale['imageInfo'] = {}

            # Store the previous status, if present.
            previousStatus = -1
            try:
                previousStatus = tale['imageInfo']['status']
            except KeyError:
                pass

            if status == JobStatus.SUCCESS:
                result = getCeleryApp().AsyncResult(job['celeryTaskId']).get()
                tale['imageInfo']['digest'] = result['image_digest']
                tale["imageInfo"]["imageId"] = tale["imageId"]
                tale['imageInfo']['repo2docker_version'] = result['repo2docker_version']
                tale['imageInfo']['last_build'] = result['last_build']
                tale['imageInfo']['status'] = ImageStatus.AVAILABLE
            elif status == JobStatus.ERROR:
                tale['imageInfo']['status'] = ImageStatus.INVALID
            elif status in (JobStatus.QUEUED, JobStatus.RUNNING):
                tale['imageInfo']['jobId'] = job['_id']
                tale['imageInfo']['status'] = ImageStatus.BUILDING

            # If the status changed, save the object
            if 'status' in tale['imageInfo'] and tale['imageInfo']['status'] != previousStatus:
                self.model('tale', 'wholetale').updateTale(tale)

    @access.user
    @autoDescribeRoute(
        Description('Copy a tale.')
        .modelParam('id', model='tale', plugin='wholetale', level=AccessType.READ)
        .responseClass('tale')
        .errorResponse('ID was invalid.')
        .errorResponse('You are not authorized to copy this tale.', 403)
    )
    @filtermodel(model='tale', plugin='wholetale')
    def copyTale(self, tale):
        user = self.getCurrentUser()
        image = self.model('image', 'wholetale').load(
            tale['imageId'], user=user, level=AccessType.READ, exc=True)
        default_authors = [
            dict(firstName=user['firstName'], lastName=user['lastName'], orcid="")
        ]
        new_tale = self._model.createTale(
            image, tale['dataSet'], creator=user, save=True,
            title=tale.get('title'), description=tale.get('description'),
            public=False, config=tale.get('config'),
            icon=image.get('icon', DEFAULT_IMAGE_ICON),
            illustration=tale.get('illustration', DEFAULT_ILLUSTRATION),
            authors=tale.get('authors', default_authors),
            category=tale.get('category', 'science'),
            licenseSPDX=tale.get('licenseSPDX'),
            status=TaleStatus.PREPARING,
            relatedIdentifiers=tale.get('relatedIdentifiers'),
        )
        new_tale['copyOfTale'] = tale['_id']
        new_tale = self._model.save(new_tale)
        # asynchronously copy the workspace of a source Tale
        job = Job().createLocalJob(
            title='Copy "{title}" workspace'.format(**tale), user=user,
            type='wholetale.copy_workspace', public=False, _async=True,
            module='girder.plugins.wholetale.tasks.copy_workspace',
            args=(tale, new_tale),
        )
        Job().scheduleJob(job)
        return new_tale

    @access.user(scope=TokenScope.DATA_WRITE)
    @filtermodel(model=Job)
    @autoDescribeRoute(
        Description("Publish a Tale to a data repository")
        .modelParam(
            "id",
            description="The ID of the tale that is going to be published.",
            model="tale",
            plugin="wholetale",
            level=AccessType.ADMIN,
        )
        .param(
            "repository",
            description="The URL to a repository, where tale is going to be published.\n"
            "Example: 'https://dev.nceas.ucsb.edu/knb/d1/mn', 'sandbox.zenodo.org'",
            required=True,
        )
        .param(
            "versionId",
            description="The identifier of the version being published",
            required=False,
        )
    )
    def publishTale(self, tale, repository, versionId):
        user = self.getCurrentUser()
        version = self._get_version(user, tale, versionId)
        publishers = {
            entry["repository"]: entry["auth_provider"]
            for entry in Setting().get(PluginSettings.PUBLISHER_REPOS)
        }

        try:
            publisher = publishers[repository]
        except KeyError:
            raise RestException("Unknown publisher repository ({})".format(repository))

        if publisher.startswith("dataone"):
            key = "provider"  # Dataone
            value = publisher
        else:
            key = "resource_server"
            value = repository

        token = next(
            (_ for _ in user.get("otherTokens", []) if _.get(key) == value), None
        )
        if not token:
            raise RestException("Missing a token for publisher ({}).".format(publisher))

        girder_token = Token().createToken(user=user, days=0.5)

        publishTask = publish.delay(
            str(tale["_id"]),
            token,
            str(version["_id"]),
            repository=repository,
            girder_client_token=str(girder_token["_id"]),
        )
        return publishTask.job

    @access.user(scope=TokenScope.DATA_WRITE)
    @filtermodel(model='tale', plugin='wholetale')
    @autoDescribeRoute(
        Description("Add git repo to the Tale workspace")
        .modelParam(
            "id",
            description="The ID of the tale that is going to be modified.",
            model="tale",
            plugin="wholetale",
            level=AccessType.ADMIN,
        )
        .param(
            "url",
            description="A location of a git repo that should be imported"
                        "as the Tale's workspace.",
            required=True,
        )
    )
    def updateTaleWithGitRepo(self, tale, url):
        return self._model.addGitRepo(
            tale,
            url,
            user=self.getCurrentUser(),
            spawn=False,
            change_status=False,
            title="Adding git repo to the Tale's workspace"
        )
