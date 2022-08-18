import json
import os
from pathlib import Path
from urllib.parse import quote, unquote

from .license import WholeTaleLicense


_NEW_DATACITE_KEY = "datacite"


def rename_dc(data):
    return {
        str(k).replace("DataCite:", f"{_NEW_DATACITE_KEY}:"): (
            rename_dc(v)
            if isinstance(v, dict)
            else v.replace("DataCite:", f"{_NEW_DATACITE_KEY}:")
        )
        for k, v in data.items()
    }


class ManifestParser:
    def __init__(self, manifest_obj):
        """
        manifest_obj: dict, str (either filename or json.dump), file-like object
        """
        if isinstance(manifest_obj, dict):
            self.manifest = manifest_obj
        elif isinstance(manifest_obj, (Path, str)) and os.path.isfile(manifest_obj):
            with open(manifest_obj, "r") as fp:
                self.manifest = json.load(fp)
        else:
            self.manifest = json.loads(manifest_obj)
        self.verify_schema()

    def is_valid(self):
        return self.manifest["@id"].startswith("https://data.wholetale.org")

    def verify_schema(self):
        if "@type" not in self.manifest:
            self.wt_ontology_update()

    def wt_ontology_update(self):
        self.manifest["@type"] = "wt:Tale"
        self.manifest["schema:schemaVersion"] = self.manifest.pop("schema:version")
        self.manifest["schema:keywords"] = self.manifest.pop("schema:category")
        self.manifest["wt:identifier"] = self.manifest.pop("schema:identifier")
        new_context = [
            obj
            for obj in self.manifest["@context"]
            if not (isinstance(obj, dict) and ("Datasets" in obj or "DataCite" in obj))
        ]
        new_context += [
            {_NEW_DATACITE_KEY: "http://datacite.org/schema/kernel-4"},
            {"wt": "https://vocabularies.wholetale.org/wt/1.1/wt#"},
            {"@base": f"arcp://uid,{self.manifest['wt:identifier']}/data/"},
        ]
        self.manifest["@context"] = new_context

        self.manifest["wt:usesDataset"] = [
            {
                "schema:identifier": ds["identifier"],
                "schema:name": ds["name"],
                "@type": "schema:Dataset",
                "@id": ds["@id"],
            }
            for ds in self.manifest.pop("Datasets")
        ]
        if not self.manifest["createdBy"]["@id"].startswith("mailto:"):
            self.manifest["createdBy"][
                "@id"
            ] = f"mailto:{self.manifest['createdBy']['@id']}"

        new_aggregates = []
        for aggregate in self.manifest["aggregates"]:
            if "bundledAs" in aggregate:
                folder = aggregate["bundledAs"]["folder"].replace("../data", ".", 1)
                aggregate["bundledAs"]["folder"] = quote(folder)
                if "filename" in aggregate["bundledAs"]:
                    aggregate["bundledAs"]["filename"] = quote(
                        aggregate["bundledAs"]["filename"]
                    )
            else:
                uri = aggregate["uri"].replace("../data", ".", 1)
                aggregate["uri"] = quote(uri)
            for key in ("md5", "mimeType", "size"):
                if key in aggregate:
                    aggregate[f"wt:{key}"] = aggregate.pop(key)
            new_aggregates.append(aggregate)
        self.manifest["aggregates"] = new_aggregates
        if "DataCite:relatedIdentifiers" in self.manifest:
            rel_ids = self.manifest.pop("DataCite:relatedIdentifiers")
        else:
            rel_ids = []
        self.manifest[f"{_NEW_DATACITE_KEY}:relatedIdentifiers"] = [
            rename_dc(_id) for _id in rel_ids
        ]

    def get_external_data_ids(self):
        dataIds = [obj["schema:identifier"] for obj in self.manifest["wt:usesDataset"]]
        dataIds += [
            obj["uri"]
            for obj in self.manifest["aggregates"]
            if obj["uri"].startswith("http") and "schema:isPartOf" not in obj
        ]
        return dataIds

    def get_extdata_from_aggs(self, data_prefix="./data"):
        data_set = []
        for obj in self.manifest["aggregates"]:
            if "schema:isPartOf" not in obj:
                continue

            bundle = obj["bundledAs"]
            folder_path = unquote(bundle["folder"]).replace(data_prefix, "", 1)
            if folder_path.endswith("/"):
                folder_path = folder_path[:-1]

            data_set.append(
                (
                    obj["schema:isPartOf"],
                    obj["wt:dsRelPath"],
                    os.path.join(folder_path, bundle["filename"]),
                )
            )
        return data_set

    def get_tale_fields(self):
        licenseSPDX = next(
            (
                _["schema:license"]
                for _ in self.manifest["aggregates"]
                if "schema:license" in _
            ),
            WholeTaleLicense.default_spdx(),
        )

        authors = [
            {
                "firstName": author["schema:givenName"],
                "lastName": author["schema:familyName"],
                "orcid": author["@id"],
            }
            for author in self.manifest["schema:author"]
        ]

        related_ids = [
            {
                "identifier": rel_id[f"{_NEW_DATACITE_KEY}:relatedIdentifier"]["@id"],
                "relation": rel_id[f"{_NEW_DATACITE_KEY}:relatedIdentifier"][
                    f"{_NEW_DATACITE_KEY}:relationType"
                ].split(":")[-1],
            }
            for rel_id in self.manifest.get(
                f"{_NEW_DATACITE_KEY}:relatedIdentifiers", []
            )
        ]
        related_ids = [
            json.loads(rel_id)
            for rel_id in {json.dumps(_, sort_keys=True) for _ in related_ids}
        ]

        imageInfo = {}
        try:
            r2d_version = next(
                iter(
                    [
                        obj["schema:softwareVersion"]
                        for obj in self.manifest["schema:hasPart"]
                        if obj["@id"] == "https://github.com/whole-tale/repo2docker_wholetale"
                    ]
                ),
                None,
            )
            if r2d_version:
                imageInfo["repo2docker_version"] = r2d_version
        except KeyError:
            pass

        try:
            image_digest = next(
                iter([
                    obj['@id']
                    for obj in self.manifest['schema:hasPart']
                    if 'schema:applicationCategory' in
                       obj and obj['schema:applicationCategory'] == 'DockerImage'
                ]), None
            )
            if (image_digest):
                imageInfo['digest'] = image_digest.replace('images', 'registry', 1)
        except KeyError:
            pass

        return {
            "title": self.manifest["schema:name"],
            "description": self.manifest["schema:description"],
            "illustration": self.manifest["schema:image"],
            "authors": authors,
            "category": self.manifest["schema:keywords"],
            "licenseSPDX": licenseSPDX,
            "relatedIdentifiers": related_ids,
            "imageInfo": imageInfo,
        }

    @staticmethod
    def get_tale_fields_from_environment(environment):
        from girder.plugins.wholetale.models.image import Image  # circular dep
        image = Image().findOne({"name": environment["name"]})
        icon = image.get(
            "icon",
            (
                "https://raw.githubusercontent.com/"
                "whole-tale/dashboard/master/public/"
                "images/whole_tale_logo.png"
            ),
        )
        return {
            "imageId": image["_id"],
            "icon": icon,
            "config": environment.get("taleConfig", {}),
        }
