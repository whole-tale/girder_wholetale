#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import cherrypy
import validators
from urllib.parse import urlparse, urlunparse, urlencode
from girder.api import access
from girder.api.describe import Description, autoDescribeRoute
from girder.api.rest import RestException, setResponseHeader, boundHandler

from .auth import DataverseVerificator
from .provider import DataverseImportProvider
from ..integration_utils import autologin, redirect_if_tale_exists


@access.public
@autoDescribeRoute(
    Description("Convert external tools request and bounce it to the dashboard.")
    .param(
        "siteUrl",
        "The URL of the Dataverse installation that hosts the file "
        "with the fileId above",
        required=True,
    )
    .param(
        "fileId",
        "The database ID of a file the user clicks 'Explore' on. "
        "For example, 42. This reserved word is required for file level tools "
        "unless you use {filePid} instead.",
        required=False,
    )
    .param(
        "filePid",
        "The Persistent ID (DOI or Handle) of a file the user clicks 'Explore' on. "
        "For example, doi:10.7910/DVN/TJCLKP/3VSTKY. Note that not all installations "
        "of Dataverse have Persistent IDs (PIDs) enabled at the file level. "
        "This reserved word is required for file level tools unless "
        "you use {fileId} instead.",
        required=False,
    )
    .param(
        "apiToken",
        "The Dataverse API token of the user launching the external "
        "tool, if available. Please note that API tokens should be treated with "
        "the same care as a password. For example, "
        "f3465b0c-f830-4bc7-879f-06c0745a5a5c.",
        required=False,
    )
    .param(
        "datasetId",
        "The database ID of the dataset. For example, 42. This reseved word is "
        "required for dataset level tools unless you use {datasetPid} instead.",
        required=False,
    )
    .param(
        "datasetPid",
        "The Persistent ID (DOI or Handle) of the dataset. "
        "For example, doi:10.7910/DVN/TJCLKP. This reseved word is "
        "required for dataset level tools unless you use {datasetId} instead.",
        required=False,
    )
    .param(
        "datasetVersion",
        "The friendly version number ( or :draft ) of the dataset version "
        "the tool is being launched from. For example, 1.0 or :draft.",
        required=False,
    )
    .param(
        "fullDataset",
        "If True, imports the full dataset that "
        "contains the file defined by fileId.",
        dataType="boolean",
        default=True,
        required=False,
    )
    .param(
        "force",
        "If True, create a new Tale regardless of the fact it was previously imported.",
        required=False,
        dataType="boolean",
        default=False,
    )
    .notes("apiToken is currently ignored.")
)
@boundHandler()
def dataverseExternalTools(
    self,
    siteUrl,
    fileId,
    filePid,
    apiToken,
    datasetId,
    datasetPid,
    datasetVersion,
    fullDataset,
    force,
):
    if not validators.url(siteUrl):
        raise RestException("Not a valid URL: siteUrl")

    if all(arg is None for arg in (fileId, filePid, datasetId, datasetPid)):
        raise RestException("No data Id provided")

    user = self.getCurrentUser()
    if user is None:
        args = {
            "siteUrl": siteUrl,
            "fileId": fileId,
            "filePid": filePid,
            "apiToken": apiToken,
            "datasetId": datasetId,
            "datasetPid": datasetPid,
            "datasetVersion": datasetVersion,
            "fullDataset": fullDataset,
            "force": force,
        }
        autologin(args=args)

    site = urlparse(siteUrl)
    headers = DataverseVerificator(url=siteUrl, user=user).headers
    if fileId:
        try:
            fileId = int(fileId)
        except (TypeError, ValueError):
            raise RestException("Invalid fileId (should be integer)")

        url = "{scheme}://{netloc}/api/access/datafile/{fileId}".format(
            scheme=site.scheme, netloc=site.netloc, fileId=fileId
        )
        title, _, doi = DataverseImportProvider._parse_access_url(urlparse(url), headers=headers)
    elif datasetId:
        try:
            datasetId = int(datasetId)
        except (TypeError, ValueError):
            raise RestException("Invalid datasetId (should be integer)")
        url = "{scheme}://{netloc}/api/datasets/{_id}".format(
            scheme=site.scheme, netloc=site.netloc, _id=datasetId
        )
        title, _, doi = DataverseImportProvider()._parse_dataset(urlparse(url), headers=headers)
        url = _dataset_full_url(site, doi)
    elif filePid:
        url = "{scheme}://{netloc}/file.xhtml?persistentId={doi}".format(
            scheme=site.scheme, netloc=site.netloc, doi=filePid
        )
        title, _, doi = DataverseImportProvider._parse_file_url(urlparse(url), headers=headers)
    elif datasetPid:
        url = _dataset_full_url(site, datasetPid)
        title, _, doi = DataverseImportProvider()._parse_dataset(urlparse(url), headers=headers)

    if not force:
        redirect_if_tale_exists(user, self.getCurrentToken(), doi)

    if fullDataset and (fileId or filePid):
        url = _dataset_full_url(site, doi)

    query = {"uri": url, "asTale": True, "name": title}
    # TODO: Make base url a plugin setting, defaulting to dashboard.<domain>
    dashboard_url = os.environ.get("DASHBOARD_URL", "https://dashboard.wholetale.org")
    location = urlunparse(
        urlparse(dashboard_url)._replace(path="/mine", query=urlencode(query))
    )
    setResponseHeader("Location", location)
    cherrypy.response.status = 303


def _dataset_full_url(site, doi):
    return "{scheme}://{netloc}/dataset.xhtml?persistentId={doi}".format(
        scheme=site.scheme, netloc=site.netloc, doi=doi
    )
