import json
import os
from pathlib import Path
from urllib.parse import quote, unquote

from girder.exceptions import ValidationException
from girder.models.file import File
from girder.models.folder import Folder
from girder.models.item import Item

from .license import WholeTaleLicense
from ..models.image import Image


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


def fold_hierarchy_smart(objs):
    # This only works because it takes into account what can be done with current UI and
    # API easily. It's still possible to manually craft a Tale that will break this if
    # you know how. If you happen to do that and after hours/days of debugging you'll
    # end up here ask me for a refund...
    reduced = []
    processed = set()
    for obj in objs:
        obj_path = Path(obj["mountPath"])
        if len(obj_path.parts) == 1:
            reduced.append(obj)
            continue
        # Since it's '/<something>/... parts[0] is the unique thing we
        # are looking for
        key = obj_path.parts[0]
        if key in processed:
            continue
        leaf_item = Item().load(obj["itemId"], force=True)
        current = Folder().load(leaf_item["folderId"], force=True)
        for _ in range(len(obj_path.parts[1:]) - 1):
            current = Folder().load(current["parentId"], force=True)
        reduced.append(
            {
                "itemId": str(current["_id"]),
                "_modelType": "folder",
                "mountPath": key,
            }
        )
        processed.add(key)
    return reduced


def fold_hierarchy(objs):
    # shortcut for expand_folder == True, which should be the majority
    if {obj["_modelType"] for obj in objs} == {"item"}:
        return fold_hierarchy_smart(objs)
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

    def get_dataset(self, data_prefix="./data/"):
        """Creates a 'dataSet' using manifest's aggregates section."""
        dataSet = []
        for obj in self.manifest.get("aggregates", []):
            try:
                bundle = obj["bundledAs"]
            except KeyError:
                continue

            folder_path = unquote(bundle["folder"]).replace(data_prefix, "", 1)
            if folder_path.endswith("/"):
                folder_path = folder_path[:-1]
            if "filename" in bundle:
                try:
                    item = Item().load(obj["wt:identifier"], force=True, exc=True)
                    assert item["name"] == unquote(bundle["filename"])
                    itemId = item["_id"]
                except (KeyError, ValidationException, AssertionError):
                    file_obj = File().findOne(
                        {"linkUrl": obj["uri"]}, fields=["itemId"]
                    )
                    itemId = file_obj["itemId"]
                path = os.path.join(folder_path, unquote(bundle["filename"]))
                model_type = "item"
            else:
                fname = Path(unquote(bundle["folder"])).parts[-1]
                try:
                    folder = Folder().load(obj["wt:identifier"], force=True, exc=True)
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
                iter([
                    obj["schema:softwareVersion"]
                    for obj in self.manifest["schema:hasPart"]
                    if obj["@id"] == "https://github.com/whole-tale/repo2docker_wholetale"
                ]), None
            )
            if (r2d_version):
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
