import json
import os
import pathlib

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

    for obj in objs:
        mount_path = pathlib.Path(obj["mountPath"])
        if len(mount_path.parts) > 1:
            reiterate = True
            if obj["itemId"] in covered_ids:
                continue

            if obj["_modelType"] == "item":
                parentId = Item().load(obj["itemId"], force=True)["folderId"]
            else:
                parentId = Folder().load(obj["itemId"], force=True)["parentId"]

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
    @staticmethod
    def get_dataset_from_manifest(manifest, data_prefix="../data/"):
        """Creates a 'dataSet' using manifest's aggregates section."""
        dataSet = []
        for obj in manifest.get("aggregates", []):
            try:
                bundle = obj["bundledAs"]
            except KeyError:
                continue

            folder_path = bundle["folder"].replace(data_prefix, "")
            if folder_path.endswith("/"):
                folder_path = folder_path[:-1]
            if "filename" in bundle:
                try:
                    item = Item().load(obj["schema:identifier"], force=True, exc=True)
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
                fname = pathlib.Path(bundle["folder"]).parts[-1]
                try:
                    folder = Folder().load(
                        obj["schema:identifier"], force=True, exc=True
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

    @staticmethod
    def get_tale_fields_from_manifest(manifest):
        licenseSPDX = next(
            (
                _["schema:license"]
                for _ in manifest["aggregates"]
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
            for author in manifest["schema:author"]
        ]

        related_ids = [
            {
                "identifier": rel_id["DataCite:relatedIdentifier"]["@id"],
                "relation": rel_id["DataCite:relatedIdentifier"][
                    "DataCite:relationType"
                ].split(":")[-1],
            }
            for rel_id in manifest.get("DataCite:relatedIdentifiers", [])
        ]
        related_ids = [
            json.loads(rel_id)
            for rel_id in {json.dumps(_, sort_keys=True) for _ in related_ids}
        ]

        return {
            "title": manifest["schema:name"],
            "description": manifest["schema:description"],
            "illustration": manifest["schema:image"],
            "authors": authors,
            "category": manifest["schema:category"],
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
