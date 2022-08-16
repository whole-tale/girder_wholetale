#!/usr/bin/env python
# -*- coding: utf-8 -*-
from girder.utility.progress import ProgressContext

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
