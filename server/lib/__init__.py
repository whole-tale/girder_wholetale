#!/usr/bin/env python
# -*- coding: utf-8 -*-

from .entity import Entity
from .resolvers import Resolvers, DOIResolver, ResolutionException
from .import_providers import ImportProviders
from .http_provider import HTTPImportProvider
from .null_provider import NullImportProvider
from .dataone.provider import DataOneImportProvider
from .dataverse.provider import DataverseImportProvider
from .globus.globus_provider import GlobusImportProvider


RESOLVERS = Resolvers()
RESOLVERS.add(DOIResolver())

IMPORT_PROVIDERS = ImportProviders()
IMPORT_PROVIDERS.addProvider(DataverseImportProvider())
IMPORT_PROVIDERS.addProvider(GlobusImportProvider())
IMPORT_PROVIDERS.addProvider(DataOneImportProvider())
# (almost) last resort
IMPORT_PROVIDERS.addProvider(HTTPImportProvider())
# just throws exceptions
IMPORT_PROVIDERS.addProvider(NullImportProvider())


def pids_to_entities(pids, user=None, base_url=None, lookup=True):
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
