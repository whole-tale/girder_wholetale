#!/usr/bin/env python
# -*- coding: utf-8 -*-
from functools import lru_cache
from urllib.request import urlopen

import html2markdown
from girder import logger
from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.models.folder import Folder
from girder.models.item import Item
from girder.utility.progress import ProgressContext

from ..models.tale import Tale
from ..utils import notify_event
from .bdbag.bdbag_provider import BDBagProvider
from .deriva.provider import DerivaProvider
from .dataone.auth import DataONEVerificator
from .dataone.provider import DataOneImportProvider
from .dataverse.auth import DataverseVerificator
from .dataverse.provider import DataverseImportProvider
from .deriva.auth import DerivaVerificator
from .entity import Entity
from .globus.globus_provider import GlobusImportProvider
from .http_provider import HTTPImportProvider
from .import_providers import ImportProviders
from .null_provider import NullImportProvider
from .openicpsr.provider import OpenICPSRImportProvider
from .openicpsr.auth import OpenICPSRVerificator
from .resolvers import DOIResolver, ResolutionException, Resolvers, MinidResolver
from .zenodo.auth import ZenodoVerificator
from .zenodo.provider import ZenodoImportProvider

RESOLVERS = Resolvers()
RESOLVERS.add(DOIResolver())
RESOLVERS.add(MinidResolver())

IMPORT_PROVIDERS = ImportProviders()
IMPORT_PROVIDERS.addProvider(DerivaProvider())
IMPORT_PROVIDERS.addProvider(BDBagProvider())
IMPORT_PROVIDERS.addProvider(DataverseImportProvider())
IMPORT_PROVIDERS.addProvider(ZenodoImportProvider())
IMPORT_PROVIDERS.addProvider(OpenICPSRImportProvider())
IMPORT_PROVIDERS.addProvider(GlobusImportProvider())
IMPORT_PROVIDERS.addProvider(DataOneImportProvider())

# (almost) last resort
IMPORT_PROVIDERS.addProvider(HTTPImportProvider())
# just throws exceptions
IMPORT_PROVIDERS.addProvider(NullImportProvider())


Verificators = {
    "zenodo": ZenodoVerificator,
    "dataverse": DataverseVerificator,
    "dataone": DataONEVerificator,
    "dataoneprod": DataONEVerificator,
    "dataonedev": DataONEVerificator,
    "dataonestage": DataONEVerificator,
    "deriva": DerivaVerificator,
    "icpsr": OpenICPSRVerificator,
}


def pids_to_entities(pids, user=None, base_url=None, lookup=True):
    """
    Resolve unique external identifiers into WholeTale Entities or file listings

    :param pids: list of external identifiers
    :param user: User performing the resolution
    :param base_url: DataONE's node endpoint url
    :param lookup: If false, a list of remote files is returned instead of Entities
    """
    results = []
    try:
        for pid in pids:
            entity = Entity(pid.strip(), user)
            entity["base_url"] = base_url
            entity = RESOLVERS.resolve(entity)
            provider = IMPORT_PROVIDERS.getProvider(entity)
            if lookup:
                results.append(provider.lookup(entity))  # list of dataMaps
            else:
                results.append(provider.listFiles(entity))  # list of FileMaps
    except ResolutionException:
        msg = 'Id "{}" was categorized as DOI, but its resolution failed.'.format(pid)
        raise RuntimeError(msg)
    except Exception as exc:
        if lookup:
            msg = 'Lookup for "{}" failed with: {}'
        else:
            msg = 'Listing files at "{}" failed with: {}'
        raise RuntimeError(msg.format(pid, str(exc)))
    return results


def register_dataMap(dataMaps, parent, parentType, user=None, base_url=None, progress=False):
    """
    Register a list of Data Maps into a given Girder object

    :param dataMaps: list of dataMaps
    :param parent: A Collection or a Folder where data should be registered
    :param parentType: Either a 'collection' or a 'folder'
    :param user: User performing the registration
    :param base_url: DataONE's node endpoint url
    :param progress: If True, emit 'progress' notification for each registered file.
    :return: List of ids of registered objects
    """
    importedData = []
    with ProgressContext(progress, user=user, title="Registering resources") as ctx:
        for dataMap in dataMaps:
            # probably would be nicer if Entity kept all details and the dataMap
            # would be merged into it
            provider = IMPORT_PROVIDERS.getFromDataMap(dataMap)
            objType, obj = provider.register(
                parent, parentType, ctx, user, dataMap, base_url=base_url
            )
            importedData.append(obj["_id"])
    return importedData


@lru_cache(maxsize=128, typed=True)
def _get_citation(url):
    return urlopen(url).read().decode()


def update_citation(event):
    tale = event.info["tale"]
    user = event.info["user"]

    dataset_top_identifiers = set()
    for obj in tale.get("dataSet", []):
        if obj["_modelType"] == "folder":
            load = Folder().load
        else:
            load = Item().load
        try:
            doc = load(obj["itemId"], user=user, level=AccessType.READ, exc=True)
            provider_name = doc["meta"]["provider"]
            if provider_name.startswith("HTTP"):
                continue
            provider = IMPORT_PROVIDERS.providerMap[provider_name]
        except (KeyError, ValidationException):
            continue
        top_identifier = provider.getDatasetUID(doc, user)
        if top_identifier:
            dataset_top_identifiers.add(top_identifier)

    citations = []
    related_ids = [
        related_id
        for related_id in tale["relatedIdentifiers"]
        if related_id["relation"] != "Cites"
    ]
    for doi in dataset_top_identifiers:
        related_ids.append(dict(identifier=doi, relation="Cites"))
        if doi.startswith("doi:"):
            doi = doi[4:]
        try:
            url = (
                "https://api.datacite.org/dois/"
                f"text/x-bibliography/{doi}?style=harvard-cite-them-right"
            )
            citation = _get_citation(url)
            citations.append(html2markdown.convert(citation))
        except Exception as ex:
            logger.info('Unable to get a citation for %s, getting "%s"', doi, str(ex))

    Tale().update({"_id": tale["_id"]}, update={"$set": {
        "dataSetCitation": citations,
        "relatedIdentifiers": related_ids,
    }})
    notify_event(
        [_["id"] for _ in tale["access"]["users"]], "wt_tale_updated", {"taleId": tale["_id"]}
    )
