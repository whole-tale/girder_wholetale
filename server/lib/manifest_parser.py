import json
import os
from pathlib import Path

from girder.exceptions import ValidationException
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item

from .license import WholeTaleLicense
from ..models.image import Image


def fold_hierarchy(objs):
    reduced = []
    covered_ids = set()
    reiterate = False

    current_ids = set([obj["itemId"] for obj in objs])

    for obj in objs:
        mount_path = Path(obj["mountPath"])
        if len(mount_path.parts) > 1:
            reiterate = True
            if obj["itemId"] in covered_ids:
                continue

            if obj["_modelType"] == "item":
                parentId = Item().load(obj["itemId"], force=True)["folderId"]
            else:
                parentId = Folder().load(obj["itemId"], force=True)["parentId"]

            if str(parentId) in current_ids:
                continue

            parent = Folder().load(parentId, force=True)
            covered_ids |= set([str(_["_id"]) for _ in Folder().childItems(parent)])
            covered_ids |= set(
                [str(_["_id"]) for _ in Folder().childFolders(parent, "folder")]
            )

            reduced.append(
                {
                    "itemId": str(parent["_id"]),
                    "_modelType": "folder",
                    "mountPath": mount_path.parent.as_posix(),
                }
            )
        else:
            reduced.append(obj)

    if reiterate:
        return fold_hierarchy(reduced)

    return reduced


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
        new_context = [
            obj
            for obj in self.manifest["@context"]
            if not (isinstance(obj, dict) and obj.get("Datasets"))
        ]
        new_context.append({"wt": "https://vocabularies.wholetale.org/wt/1.0/wt#"})
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
            self.manifest["createdBy"]["@id"] = f"mailto:{self.manifest['createdBy']['@id']}"

    def get_external_data_ids(self):
        dataIds = [obj["schema:identifier"] for obj in self.manifest["wt:usesDataset"]]
        dataIds += [
            obj["uri"]
            for obj in self.manifest["aggregates"]
            if obj["uri"].startswith("http")
        ]
        return dataIds

    def get_dataset(self, data_prefix="../data/"):
        """Creates a 'dataSet' using manifest's aggregates section."""
        dataSet = []
        for obj in self.manifest.get("aggregates", []):
            try:
                bundle = obj["bundledAs"]
            except KeyError:
                continue

            folder_path = bundle["folder"].replace(data_prefix, "")
            if folder_path.endswith("/"):
                folder_path = folder_path[:-1]
            if "filename" in bundle:
                try:
                    item = Item().load(obj["wt:identifier"], force=True, exc=True)
                    assert item["name"] == bundle["filename"]
                    itemId = item["_id"]
                except (KeyError, ValidationException, AssertionError):
                    file_obj = File().findOne(
                        {"linkUrl": obj["uri"]}, fields=["itemId"]
                    )
                    itemId = file_obj["itemId"]
                path = os.path.join(folder_path, bundle["filename"])
                model_type = "item"
            else:
                fname = Path(bundle["folder"]).parts[-1]
                try:
                    folder = Folder().load(
                        obj["wt:identifier"], force=True, exc=True
                    )
                    assert folder["name"] == fname
                except (KeyError, ValidationException, AssertionError):
                    folder = Folder().findOne(
                        {"meta.identifier": obj["uri"]}, fields=[]
                    )

                if not folder:
                    # TODO: There should be a better way to do it...
                    folder = Folder().findOne(
                        {"name": fname, "size": obj["size"]}, fields=[]
                    )
                itemId = folder["_id"]
                path = folder_path
                model_type = "folder"
            dataSet.append(
                dict(mountPath=path, _modelType=model_type, itemId=str(itemId))
            )
        return fold_hierarchy(dataSet)

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
                "identifier": rel_id["DataCite:relatedIdentifier"]["@id"],
                "relation": rel_id["DataCite:relatedIdentifier"][
                    "DataCite:relationType"
                ].split(":")[-1],
            }
            for rel_id in self.manifest.get("DataCite:relatedIdentifiers", [])
        ]
        related_ids = [
            json.loads(rel_id)
            for rel_id in {json.dumps(_, sort_keys=True) for _ in related_ids}
        ]

        return {
            "title": self.manifest["schema:name"],
            "description": self.manifest["schema:description"],
            "illustration": self.manifest["schema:image"],
            "authors": authors,
            "category": self.manifest["schema:keywords"],
            "licenseSPDX": licenseSPDX,
            "relatedIdentifiers": related_ids,
        }

    @staticmethod
    def get_tale_fields_from_environment(environment):
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
