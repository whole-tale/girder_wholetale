#!/usr/bin/env python
# -*- coding: utf-8 -*-

import html2markdown
from urllib.request import urlopen

from girder import events, logger
from girder.constants import AccessType
from girder.exceptions import ValidationException
from girder.utility.model_importer import ModelImporter
from girder.utility.progress import ProgressContext
from .data_map import DataMap
from .entity import Entity
from .resolvers import Resolvers, DOIResolver, ResolutionException
from .import_providers import ImportProviders
from .http_provider import HTTPImportProvider
from .null_provider import NullImportProvider
from .dataone.provider import DataOneImportProvider
from .dataverse.provider import DataverseImportProvider
from .globus.globus_provider import GlobusImportProvider
from .agave.provider import DesignSafeImportProvider


RESOLVERS = Resolvers()
RESOLVERS.add(DOIResolver())

IMPORT_PROVIDERS = ImportProviders()
IMPORT_PROVIDERS.addProvider(DataverseImportProvider())
IMPORT_PROVIDERS.addProvider(GlobusImportProvider())
IMPORT_PROVIDERS.addProvider(DataOneImportProvider())
#IMPORT_PROVIDERS.addProvider(DesignSafeImportProvider())
# (almost) last resort
IMPORT_PROVIDERS.addProvider(HTTPImportProvider())
# just throws exceptions
IMPORT_PROVIDERS.addProvider(NullImportProvider())


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
            entity['base_url'] = base_url
            entity = RESOLVERS.resolve(entity)
            provider = IMPORT_PROVIDERS.getProvider(entity)
            if lookup:
                results.append(provider.lookup(entity))
            else:
                results.append(provider.listFiles(entity))
    except ResolutionException:
        msg = 'Id "{}" was categorized as DOI, but its resolution failed.'.format(pid)
        raise RuntimeError(msg)
    except Exception as exc:
        if lookup:
            msg = 'Lookup for "{}" failed with: {}'
        else:
            msg = 'Listing files at "{}" failed with: {}'
        raise RuntimeError(msg.format(pid, str(exc)))
    return [x.toDict() for x in results]


def register_dataMap(dataMaps, parent, parentType, user=None, base_url=None):
    """
    Register a list of Data Maps into a given Girder object

    :param dataMaps: list of dataMaps
    :param parent: A Collection or a Folder where data should be registered
    :param parentType: Either a 'collection' or a 'folder'
    :param user: User performing the registration
    :param base_url: DataONE's node endpoint url
    :return: List of ids of registered objects
    """
    progress = True
    importedData = []
    with ProgressContext(progress, user=user, title='Registering resources') as ctx:
        for dataMap in DataMap.fromList(dataMaps):
            # probably would be nicer if Entity kept all details and the dataMap
            # would be merged into it
            provider = IMPORT_PROVIDERS.getFromDataMap(dataMap)
            objType, obj = provider.register(
                parent, parentType, ctx, user, dataMap, base_url=base_url
            )
            importedData.append(obj['_id'])
    return importedData


def update_citation(event):
    tale = event.info['tale']
    user = event.info['user']

    dataset_top_identifiers = set()
    for obj in tale.get('dataSet', []):
        try:
            doc = ModelImporter.model(obj['_modelType']).load(
                obj['itemId'], user=user, level=AccessType.READ, exc=True
            )
            provider_name = doc['meta']['provider']
            if provider_name.startswith('HTTP'):
                continue
            provider = IMPORT_PROVIDERS.providerMap[provider_name]
        except (KeyError, ValidationException):
            continue
        top_identifier = provider.getDatasetUID(doc, user)
        if top_identifier:
            dataset_top_identifiers.add(top_identifier)

    citations = []
    for doi in dataset_top_identifiers:
        if doi.startswith('doi:'):
            doi = doi[4:]
        try:
            url = (
                'https://api.datacite.org/dois/'
                'text/x-bibliography/{}?style=harvard-cite-them-right'
            )
            citations.append(
                html2markdown.convert(urlopen(url.format(doi)).read().decode())
            )
        except Exception as ex:
            logger.info('Unable to get a citation for %s, getting "%s"', doi, str(ex))

    tale['dataSetCitation'] = citations
    event.preventDefault().addResponse(tale)


events.bind('tale.update_citation', 'wholetale', update_citation)
