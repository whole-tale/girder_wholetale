#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base64
import cherrypy
import copy
import datetime
import jsonschema
import logging
import os
import pathlib
import six
import validators

from girder import events, logprint, logger
from girder.api import access
from girder.api.describe import Description, describeRoute, autoDescribeRoute
from girder.api.rest import \
    boundHandler, loadmodel, RestException
from girder.constants import AccessType, TokenScope
from girder.exceptions import GirderException
from girder.models.assetstore import Assetstore
from girder.models.folder import Folder
from girder.models.model_base import AccessException, ValidationException
from girder.models.notification import Notification, ProgressState
from girder.models.setting import Setting
from girder.models.user import User
from girder.models.file import File
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.jobs.models.job import Job as JobModel
from girder.plugins.worker.utils import jobInfoSpec
from girder.plugins.worker import CustomJobStatus
from girder.plugins.oauth.rest import OAuth as OAuthResource
from girder.plugins.worker import getCeleryApp
from girder.utility import setting_utilities
from girder.utility.model_importer import ModelImporter

from .constants import PluginSettings, SettingDefault
from .lib import update_citation
from .lib.metrics import metricsLogger, _MetricsHandler
from .rest.account import Account
from .rest.dataset import Dataset
from .rest.image import Image
from .rest.integration import Integration
from .rest.repository import Repository
from .rest.harvester import listImportedData
from .rest.tale import Tale
from .rest.instance import Instance
from .rest.wholetale import wholeTale
from .rest.license import License
from .models.instance import finalizeInstance, cullIdleInstances
from .schema.misc import (
    external_auth_providers_schema,
    external_apikey_groups_schema,
    repository_to_provider_schema,
)


@setting_utilities.validator(PluginSettings.PUBLISHER_REPOS)
def validatePublisherRepos(doc):
    try:
        jsonschema.validate(doc['value'], repository_to_provider_schema)
    except jsonschema.ValidationError as e:
        raise ValidationException('Invalid Repository to Auth Provider map: ' + str(e))


@setting_utilities.default(PluginSettings.PUBLISHER_REPOS)
def defaultPublisherRepos():
    return copy.deepcopy(
        SettingDefault.defaults[PluginSettings.PUBLISHER_REPOS]
    )


@setting_utilities.validator(PluginSettings.EXTERNAL_APIKEY_GROUPS)
def validateExternalApikeyGroups(doc):
    try:
        jsonschema.validate(doc['value'], external_apikey_groups_schema)
    except jsonschema.ValidationError as e:
        raise ValidationException('Invalid External Apikey Groups list: ' + str(e))


@setting_utilities.validator(PluginSettings.EXTERNAL_AUTH_PROVIDERS)
def validateOtherSettings(doc):
    try:
        jsonschema.validate(doc['value'], external_auth_providers_schema)
    except jsonschema.ValidationError as e:
        raise ValidationException('Invalid External Auth Providers list: ' + str(e))


@setting_utilities.default(PluginSettings.EXTERNAL_AUTH_PROVIDERS)
def defaultExternalAuthProviders():
    return copy.deepcopy(
        SettingDefault.defaults[PluginSettings.EXTERNAL_AUTH_PROVIDERS]
    )


@setting_utilities.default(PluginSettings.EXTERNAL_APIKEY_GROUPS)
def defaultExternalApikeyGroups():
    return copy.deepcopy(
        SettingDefault.defaults[PluginSettings.EXTERNAL_APIKEY_GROUPS]
    )


@setting_utilities.validator(PluginSettings.DATAVERSE_EXTRA_HOSTS)
def validateDataverseExtraHosts(doc):
    if not doc['value']:
        doc['value'] = defaultDataverseExtraHosts()
    if not isinstance(doc['value'], list):
        raise ValidationException('Dataverse extra hosts setting must be a list.', 'value')
    for url in doc['value']:
        if not validators.domain(url):
            raise ValidationException('Invalid domain in Dataverse extra hosts', 'value')


@setting_utilities.validator(PluginSettings.ZENODO_EXTRA_HOSTS)
def validateZenodoExtraHosts(doc):
    if not doc['value']:
        doc['value'] = defaultZenodoExtraHosts()
    if not isinstance(doc['value'], list):
        raise ValidationException('Zenodo extra hosts setting must be a list.', 'value')
    for url in doc['value']:
        if not validators.url(url):
            raise ValidationException('Invalid URL in Zenodo extra hosts', 'value')


@setting_utilities.validator(PluginSettings.DERIVA_EXPORT_URLS)
def validateDerivaExportUrls(doc):
    if not doc['value']:
        doc['value'] = defaultDerivaExportUrls()
    if not isinstance(doc['value'], list):
        raise ValidationException('Deriva export URLs setting must be a list.', 'value')
    for url in doc['value']:
        if not validators.url(url):
            raise ValidationException('Invalid URL in Deriva exportURLs', 'value')


@setting_utilities.validator(PluginSettings.DERIVA_SCOPES)
def validateDerivaScopes(doc):
    if not doc['value']:
        doc['value'] = defaultDerivaScopes()
    if not isinstance(doc['value'], dict):
        raise ValidationException('Deriva scopes must be a dict.', 'value')


@setting_utilities.validator(PluginSettings.INSTANCE_CAP)
def validateInstanceCap(doc):
    if not doc['value']:
        doc['value'] = defaultInstanceCap()
    try:
        int(doc['value'])
    except ValueError:
        raise ValidationException(
            'Instance Cap needs to be an integer.', 'value')


@setting_utilities.validator(PluginSettings.DATAVERSE_URL)
def validateDataverseURL(doc):
    if not doc['value']:
        doc['value'] = defaultDataverseURL()
    if not validators.url(doc['value']):
        raise ValidationException('Invalid Dataverse URL', 'value')


@setting_utilities.validator(PluginSettings.LOGGER_URL)
def validateLoggerURL(doc):
    if not doc['value']:
        doc['value'] = defaultLoggerUrl()
    if not validators.url(doc['value']):
        raise ValidationException('Invalid Instance Logger URL', 'value')


@setting_utilities.validator(PluginSettings.DASHBOARD_LINK_TITLE)
def validateDashboardLinkTitle(doc):
    if not doc['value']:
        doc['value'] = defaultDashboardLinkTitle()
    if not isinstance(doc['value'], six.string_types):
        raise ValidationException('The setting is not a string', 'value')


@setting_utilities.validator(PluginSettings.CATALOG_LINK_TITLE)
def validateCatalogLinkTitle(doc):
    if not doc['value']:
        doc['value'] = defaultCatalogLinkTitle()
    if not isinstance(doc['value'], six.string_types):
        raise ValidationException('The setting is not a string', 'value')


@setting_utilities.validator(PluginSettings.ENABLE_DATA_CATALOG)
def validateEnableDataCatalog(doc):
    if not doc['value']:
        doc['value'] = defaultEnableDataCatalog()
    if not isinstance(doc['value'], bool):
        raise ValidationException('The setting is not a boolean', 'value')


@setting_utilities.validator(PluginSettings.WEBSITE_URL)
def validateWebsiteUrl(doc):
    if not doc['value']:
        doc['value'] = defaultWebsiteUrl()
    if not validators.url(doc['value']):
        raise ValidationException('Invalid  URL', 'value')


@setting_utilities.validator(PluginSettings.LOGO)
def _validateLogo(doc):
    try:
        logoFile = File().load(doc['value'], level=AccessType.READ, user=None, exc=True)
    except AccessException:
        raise ValidationException('Logo must be publicly readable', 'value')

    # Store this field natively as an ObjectId
    doc['value'] = logoFile['_id']


@setting_utilities.validator({
    PluginSettings.ABOUT_HREF,
    PluginSettings.CONTACT_HREF,
    PluginSettings.BUG_HREF,
    PluginSettings.MOUNTS,
})
def validateHref(doc):
    pass


@setting_utilities.default(PluginSettings.INSTANCE_CAP)
def defaultInstanceCap():
    return SettingDefault.defaults[PluginSettings.INSTANCE_CAP]


@setting_utilities.default(PluginSettings.DATAVERSE_URL)
def defaultDataverseURL():
    return SettingDefault.defaults[PluginSettings.DATAVERSE_URL]


@setting_utilities.default(PluginSettings.DATAVERSE_EXTRA_HOSTS)
def defaultDataverseExtraHosts():
    return SettingDefault.defaults[PluginSettings.DATAVERSE_EXTRA_HOSTS]


@setting_utilities.default(PluginSettings.ZENODO_EXTRA_HOSTS)
def defaultZenodoExtraHosts():
    return SettingDefault.defaults[PluginSettings.ZENODO_EXTRA_HOSTS]


@setting_utilities.default(PluginSettings.DERIVA_EXPORT_URLS)
def defaultDerivaExportUrls():
    return SettingDefault.defaults[PluginSettings.DERIVA_EXPORT_URLS]


@setting_utilities.default(PluginSettings.DERIVA_SCOPES)
def defaultDerivaScopes():
    return SettingDefault.defaults[PluginSettings.DERIVA_SCOPES]


@setting_utilities.default(PluginSettings.LOGGER_URL)
def defaultLoggerUrl():
    return SettingDefault.defaults[PluginSettings.LOGGER_URL]


@setting_utilities.default(PluginSettings.WEBSITE_URL)
def defaultWebsiteUrl():
    return SettingDefault.defaults[PluginSettings.WEBSITE_URL]


@setting_utilities.default(PluginSettings.DASHBOARD_LINK_TITLE)
def defaultDashboardLinkTitle():
    return SettingDefault.defaults[PluginSettings.DASHBOARD_LINK_TITLE]


@setting_utilities.default(PluginSettings.CATALOG_LINK_TITLE)
def defaultCatalogLinkTitle():
    return SettingDefault.defaults[PluginSettings.CATALOG_LINK_TITLE]


@setting_utilities.default(PluginSettings.ENABLE_DATA_CATALOG)
def defaultEnableDataCatalog():
    return SettingDefault.defaults[PluginSettings.ENABLE_DATA_CATALOG]


@setting_utilities.default(PluginSettings.LOGO)
def _defaultLogo():
    return None


@setting_utilities.default(PluginSettings.ABOUT_HREF)
def defaultAboutHref():
    return SettingDefault.defaults[PluginSettings.ABOUT_HREF]


@setting_utilities.default(PluginSettings.CONTACT_HREF)
def defaultContactHref():
    return SettingDefault.defaults[PluginSettings.CONTACT_HREF]


@setting_utilities.default(PluginSettings.BUG_HREF)
def defaultBugHref():
    return SettingDefault.defaults[PluginSettings.BUG_HREF]


@setting_utilities.default(PluginSettings.MOUNTS)
def defaultMounts():
    return SettingDefault.defaults[PluginSettings.MOUNTS]


@access.public(scope=TokenScope.DATA_READ)
@loadmodel(model='folder', level=AccessType.READ)
@describeRoute(
    Description('List the content of a folder.')
    .param('id', 'The ID of the folder.', paramType='path')
    .errorResponse('ID was invalid.')
    .errorResponse('Read access was denied for the folder.', 403)
)
@boundHandler()
def listFolder(self, folder, params):
    user = self.getCurrentUser()
    data = {
        "name": "/",
        "type": 0,
        "children": [],
    }
    # We have only one assetstore, so we can use the current one
    current_assetstore = Assetstore().getCurrent()
    assetstore_path = current_assetstore["root"]
    for fs_path, fobj in Folder().fileList(
        folder, user=user, data=False, subpath=False, path="",
    ):
        if fobj.get("imported", False):
            host_path = fobj["path"]
        else:
            host_path = os.path.join(assetstore_path, fobj["path"])

        current_level = data
        fs_path_parts = pathlib.Path(fs_path).parts
        for part in fs_path_parts:
            child_dict = None
            for child in current_level["children"]:
                if child["name"] == part:
                    child_dict = child
                    break
            if child_dict is None:
                child_dict = {"name": part, "type": 0, "children": []}
                current_level["children"].append(child_dict)
            current_level = child_dict
        current_level["type"] = 1
        current_level["host_path"] = host_path
    return data


@access.public(scope=TokenScope.DATA_READ)
@autoDescribeRoute(
    Description('Convert folder content into DM dataSet')
    .modelParam('id', 'The ID of the folder', model='folder',
                level=AccessType.READ)
)
@boundHandler()
def getDataSet(self, folder, params):
    dataSet = [
        {
            "itemId": item["_id"],
            "mountPath":  "/" + item["name"],
            "_modelType": "item",
        }
        for item in Folder().childItems(folder=folder)
    ]
    dataSet += [
        {
            "itemId": childFolder["_id"],
            "mountPath":  "/" + childFolder["name"],
            "_modelType": "folder",
        }
        for childFolder in Folder().childFolders(
            parentType='folder', parent=folder, user=self.getCurrentUser()
        )
    ]
    return dataSet


@access.user
@describeRoute(
    Description('Update the user settings.')
    .errorResponse('Read access was denied.', 403)
)
@boundHandler()
def getUserMetadata(self, params):
    user = self.getCurrentUser()
    return user.get('meta', {})


@access.user
@describeRoute(
    Description('Get the user settings.')
    .param('body', 'A JSON object containing the metadata keys to add',
           paramType='body')
    .errorResponse('Write access was denied.', 403)
)
@boundHandler()
def setUserMetadata(self, params):
    user = self.getCurrentUser()
    metadata = self.getBodyJson()

    # Make sure we let user know if we can't accept a metadata key
    for k in metadata:
        if not len(k):
            raise RestException('Key names must be at least one character long.')
        if '.' in k or k[0] == '$':
            raise RestException('The key name %s must not contain a period '
                                'or begin with a dollar sign.' % k)

    if 'meta' not in user:
        user['meta'] = {}

    # Add new metadata to existing metadata
    user['meta'].update(six.viewitems(metadata))

    # Remove metadata fields that were set to null (use items in py3)
    toDelete = [k for k, v in six.viewitems(user['meta']) if v is None]
    for key in toDelete:
        del user['meta'][key]

    # Validate and save the user
    return self.model('user').save(user)


@access.public
@autoDescribeRoute(
    Description('Initiate oauth login flow')
    .param('redirect', 'URL to redirect to after login', required=False)
)
@boundHandler()
def signIn(self, redirect):
    user, token = self.getCurrentUser(returnToken=True)

    # If there's no user, initiate the oauth flow with this endpoint
    # as the callback along with the fhost parameter
    if user is None:
        oauth_providers = OAuthResource().listProviders(params={"redirect": redirect})
        raise cherrypy.HTTPRedirect(oauth_providers["Globus"])
    else:
        self.sendAuthTokenCookie(user=user, token=token)
        cookie = cherrypy.response.cookie
        cookie["girderToken"].update({"samesite": None})
        raise cherrypy.HTTPRedirect(redirect)


@access.user
@autoDescribeRoute(
    Description('Get a set of items and folders.')
    .jsonParam('resources', 'A JSON-encoded set of resources to get. Each type '
               'is a list of ids. Only folders and items may be specified. '
               'For example: {"item": [(item id 1), (item id2)], "folder": '
               '[(folder id 1)]}.', requireObject=True)
    .errorResponse('Unsupport or unknown resource type.')
    .errorResponse('Invalid resources format.')
    .errorResponse('Resource type not supported.')
    .errorResponse('No resources specified.')
    .errorResponse('Resource not found.')
    .errorResponse('ID was invalid.')
)
@boundHandler()
def listResources(self, resources, params):
    user = self.getCurrentUser()
    result = {}
    for kind in resources:
        try:
            model = self.model(kind)
            result[kind] = [
                model.load(id=id, user=user, level=AccessType.READ, exc=True)
                for id in resources[kind]]
        except ImportError:
            pass
    return result


def validateFileLink(event):
    # allow globus URLs
    doc = event.info
    if doc.get('assetstoreId') is None:
        if 'linkUrl' not in doc:
            raise ValidationException(
                'File must have either an assetstore ID or a link URL.',
                'linkUrl')
            doc['linkUrl'] = doc['linkUrl'].strip()

        if not doc['linkUrl'].startswith(('http:', 'https:', 'globus:')):
            raise ValidationException(
                'Linked file URL must start with http: or https: or globus:.',
                'linkUrl')
    if 'name' not in doc or not doc['name']:
        raise ValidationException('File name must not be empty.', 'name')

    doc['exts'] = [ext.lower() for ext in doc['name'].split('.')[1:]]
    event.preventDefault().addResponse(doc)


def updateNotification(event):
    """
    Update the Whole Tale task notification for a job, if present.
    """

    job = event.info["job"]
    params = event.info["params"]
    if "wt_notification_id" in job and (
        notification := Notification().load(job["wt_notification_id"])
    ):
        resource = notification["data"]["resource"]

        # Add job IDs to the resource
        if 'jobs' not in notification['data']['resource']:
            resource['jobs'] = []

        if job['_id'] not in notification['data']['resource']['jobs']:
            resource['jobs'].append(job['_id'])

        if job["_id"] != resource['jobs'][-1]:
            return  # ignore previous jobs' out of order notifications

        # reset current job counter for a new job
        if resource["jobId"] != resource["jobs"][-1]:
            resource["jobCurrent"] = 0
            resource["jobId"] = resource["jobs"][-1]

        if not params["progressCurrent"]:
            increment = 0
        else:
            try:
                increment = params["progressCurrent"] - job["progress"]["current"]
            except (KeyError, TypeError):
                increment = params["progressCurrent"] - resource["jobCurrent"]

        resource["jobCurrent"] += increment

        # For multi-job tasks, ignore success for intermediate events
        would_be_last = \
            int(notification['data']['total']) == int(notification['data']['current']) + increment
        job_status = params["status"] or job["status"]
        if job_status == JobStatus.CANCELED:
            # ProgressState is not a real enum, but just a collection of strings..
            # as a result it can be an arbitrary value!
            state = "canceled"
        elif job_status == CustomJobStatus.CANCELING:
            state = "canceling"
        else:
            state = JobStatus.toNotificationStatus(int(job_status))
        if state == ProgressState.SUCCESS and not would_be_last:
            state = ProgressState.ACTIVE

        # Note, if expires parameter is not provided, updateProgress resets to 1 hour
        Notification().updateProgress(
            notification, state=state,
            expires=notification["expires"],
            message=params["progressMessage"] or notification["data"]["message"],
            increment=int(increment),
            total=notification["data"]["total"]
        )


@access.user
@autoDescribeRoute(
    Description('Get output from celery job.')
    .modelParam('id', 'The ID of the job.', model=JobModel, force=True, includeLog=True)
    .errorResponse('ID was invalid.')
    .errorResponse('Read access was denied for the job.', 403)
)
@boundHandler()
def getJobResult(self, job):
    user = self.getCurrentUser()
    if not job.get('public', False):
        if user:
            JobModel().requireAccess(job, user, level=AccessType.READ)
        else:
            self.ensureTokenScopes('jobs.job_' + str(job['_id']))

    if 'result' in job:
        return job['result']

    celeryTaskId = job.get('celeryTaskId')
    if celeryTaskId is None:
        logger.warn(
            "Job '{}' doesn't have a Celery task id.".format(job['_id']))
        return
    if job['status'] != JobStatus.SUCCESS:
        logger.warn(
            "Job '{}' hasn't completed sucessfully.".format(job['_id']))
    asyncResult = getCeleryApp().AsyncResult(celeryTaskId)
    try:
        result = asyncResult.get()
    except Exception as ex:
        result = str(ex)
    return result


@access.cookie
@access.public
@autoDescribeRoute(
    Description('Initiate oauth login flow')
    .param("instance", "Authorization is for instance URL",
           default=False, required=False, dataType="boolean")
)
@boundHandler()
def authorize(self, instance):
    # This endpoint must be called from a Traefik forward-auth request.
    # This requires that the core.cookie_domain is set to .(local.)wholetale.org
    # If instance=true, the X-Forwarded-Host is assumed to be the hostname
    # for a running instance.
    user = self.getCurrentUser()

    forwarded_host = cherrypy.request.headers.get('X-Forwarded-Host')
    forwarded_uri = cherrypy.request.headers.get('X-Forwarded-Uri')
    if not forwarded_host and not forwarded_uri:
        raise RestException('Forward auth request required', code=400)
    subdomain, domain = forwarded_host.split('.', 1)

    if user is None:
        # If no user, redirect to authentication endpoint to initiate oauth flow
        redirect = f'https://{forwarded_host}{forwarded_uri}'
        # As a forward-auth request, the host is the origin (e.g., tmp-xxx.*)
        # but we need to redirect to Girder.
        raise cherrypy.HTTPRedirect(
              f'https://girder.{domain}/api/v1/user/sign_in?redirect={redirect}')

    if instance:
        inst = self.model('instance', 'wholetale').findOne(
            {"containerInfo.name": subdomain, "creatorId": user["_id"]}
        )
        if inst is None:
            raise RestException('Access denied for instance', code=403)

        # Authorize can be called quite a lot. Therefore we only update db
        # once every 5 min.
        now = datetime.datetime.utcnow()
        if inst["lastActivity"] + datetime.timedelta(minutes=5) < now:
            self.model('instance', 'wholetale').update(
                {"_id": inst["_id"]}, {"$set": {"lastActivity": now}})


def store_other_globus_tokens(event):
    globus_token = event.info["token"]
    user = event.info["user"]
    user_tokens = user.get("otherTokens", [])
    for token in globus_token.get("other_tokens", []):
        for i, user_token in enumerate(user_tokens):
            if user_token["resource_server"] == token["resource_server"]:
                user_tokens[i].update(token)
                break
        else:
            user_tokens.append(token)
    user["otherTokens"] = user_tokens
    user["lastLogin"] = datetime.datetime.utcnow()
    User().save(user)
    metricsLogger.info(
        "user.login",
        extra={"details": {"userId": user["_id"]}},
    )


def attachJobInfoSpec(event):
    job = event.info
    if not job.get("module"):
        JobModel().updateJob(
            job,
            otherFields={"jobInfoSpec": jobInfoSpec(job, token=job.get("token"))}
        )


def load(info):
    from girder.plugins.oauth.providers.globus import Globus

    # Remove unnecessary scope https://github.com/whole-tale/girder_wholetale/issues/534
    Globus._AUTH_SCOPES.remove("urn:globus:auth:scope:auth.globus.org:view_identities")
    deriva_scopes = Setting().get(PluginSettings.DERIVA_SCOPES)
    Globus.addScopes(list(deriva_scopes.values()))
    info['apiRoot'].wholetale = wholeTale()
    info['apiRoot'].instance = Instance()
    tale = Tale()
    info['apiRoot'].tale = tale

    from girder.plugins.wholetale.models.tale import Tale as TaleModel
    from girder.plugins.wholetale.models.tale import _currentTaleFormat
    q = {
        '$or': [
            {'format': {'$exists': False}},
            {'format': {'$lt': _currentTaleFormat}}
        ]}
    for obj in TaleModel().find(q):
        try:
            TaleModel().save(obj, validate=True)
        except GirderException as exc:
            logprint(exc)

    info['apiRoot'].dataset = Dataset()
    info['apiRoot'].image = Image()
    events.bind('jobs.job.update.after', 'wholetale', tale.updateBuildStatus)
    events.bind('jobs.job.update.after', 'wholetale', finalizeInstance)
    events.bind('jobs.job.update.after', 'wholetale', TaleModel._track_publication)
    events.bind('jobs.job.update', 'wholetale', updateNotification)
    events.bind('model.file.validate', 'wholetale', validateFileLink)
    events.bind('oauth.auth_callback.after', 'wholetale', store_other_globus_tokens)
    events.bind('heartbeat', 'wholetale', cullIdleInstances)
    events.unbind("model.job.save.after", "worker")
    events.bind("model.job.save.after", "wholetale", attachJobInfoSpec)

    info['apiRoot'].account = Account()
    info['apiRoot'].repository = Repository()
    info['apiRoot'].license = License()
    info['apiRoot'].integration = Integration()
    info['apiRoot'].folder.route('GET', ('registered',), listImportedData)
    info['apiRoot'].folder.route('GET', (':id', 'listing'), listFolder)
    info['apiRoot'].folder.route('GET', (':id', 'dataset'), getDataSet)
    info['apiRoot'].job.route('GET', (':id', 'result'), getJobResult)
    info['apiRoot'].resource.route('GET', (), listResources)

    info['apiRoot'].user.route('PUT', ('settings',), setUserMetadata)
    info['apiRoot'].user.route('GET', ('settings',), getUserMetadata)
    info['apiRoot'].user.route('GET', ('sign_in',), signIn)
    info['apiRoot'].user.route('GET', ('authorize',), authorize)

    ModelImporter.model('user').exposeFields(
        level=AccessType.WRITE, fields=('meta', 'myData', 'lastLogin'))
    ModelImporter.model('user').exposeFields(
        level=AccessType.ADMIN, fields=('otherTokens',))

    events.bind("tale.update_citation", "wholetale", update_citation)
    path_to_assets = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "web_client/extra/img",
    )
    for ext_provider in SettingDefault.defaults[PluginSettings.EXTERNAL_AUTH_PROVIDERS]:
        logo_path = os.path.join(path_to_assets, ext_provider["name"] + '_logo.jpg')
        if os.path.isfile(logo_path):
            with open(logo_path, "rb") as image_file:
                ext_provider["logo"] = base64.b64encode(image_file.read()).decode()

    metricsLogger.setLevel(logging.INFO)
    metricsLogger.addHandler(_MetricsHandler())
