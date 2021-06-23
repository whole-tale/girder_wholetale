import re
from .entity import Entity
from typing import Optional
import requests

"""Regex that matches:

http://dx.doi.org/doi:10.24431/rw1k118
http://dx.doi.org/10.24431/rw1k118
https://dx.doi.org/doi:10.24431/rw1k118
http://doi.org/doi:10.24431/rw1k118
https://hdl.handle.net/doi:10.24431/rw1k118
doi:10.24431/rw1k118
10.24431/rw1k118
http://dx.doi.org/10.24431/rw1k118
http://dx.doi.org/10.24431/rw1k118
https://dx.doi.org/10.24431/rw1k118
https://doi.org/10.24431/rw1k118
http://hdl.handle.net/10.24431/rw1k118
"""

_DOI_RESOLVERS_RE = re.compile(
    r'^(|https?://(dx.doi.org|doi.org|hdl.handle.net)/)(doi:)?(10.\d{4,9}/[-._;()/:A-Z0-9]+)$',
    re.IGNORECASE
)


class Resolver:
    def __init__(self):
        pass

    def resolve(self, entity: Entity) -> Entity:
        raise NotImplementedError()


class Resolvers:
    def __init__(self):
        self.resolvers = []

    def add(self, resolver: Resolver):
        self.resolvers.append(resolver)

    def resolve(self, entity: Entity) -> Optional[Entity]:
        while True:
            for resolver in self.resolvers:
                result = resolver.resolve(entity)
                if result is None:
                    return entity


class ResolutionException(Exception):
    def __init__(self, message: str, prev: Exception = None):
        self.message = message
        self.prev = prev

    def __str__(self):
        return self.message


class DOIResolver(Resolver):

    @staticmethod
    def extractDOI(url: str):
        doi_match = _DOI_RESOLVERS_RE.match(url)
        if doi_match:
            return doi_match.groups()[-1]

    def resolve(self, entity: Entity) -> Optional[Entity]:
        value = entity.getValue()
        doi = DOIResolver.extractDOI(value)
        if doi is None:
            return None
        else:
            self.resolveDOI(entity, doi)
            return entity

    def resolveDOI(self, entity: Entity, doi: str):
        # Expect a redirect. Basically, don't do anything fancy because I don't know
        # if I can correctly resolve a DOI using the structured record
        url = 'https://doi.org/%s' % doi
        resolved_url = requests.head(url, allow_redirects=True).url
        if url == resolved_url:
            raise ResolutionException('Could not resolve DOI %s' % (doi,))

        entity.setValue(resolved_url)
        entity['DOI'] = doi
