from hashlib import sha256, md5
import json
import magic
import os
import requests
from girder.utility import hash_state, ziputil, JsonEncoder
from girder.models.folder import Folder
from girder.constants import AccessType
from ..license import WholeTaleLicense


class HashFileStream:
    """Generator that computes md5 and sha256 of data returned by it"""

    def __init__(self, gen):
        """
        This class is primarily meant to wrap Girder's download function,
        which returns iterators, hence self.x = x()
        """
        try:
            self.gen = gen()
        except TypeError:
            self.gen = gen
        self.state = {
            'md5': hash_state.serializeHex(md5()),
            'sha256': hash_state.serializeHex(sha256()),
        }

    def __iter__(self):
        return self

    def __next__(self):
        nxt = next(self.gen)
        for alg in self.state.keys():
            checksum = hash_state.restoreHex(self.state[alg], alg)
            checksum.update(nxt)
            self.state[alg] = hash_state.serializeHex(checksum)
        return nxt

    def __call__(self):
        """Needs to be callable, see comment in __init__"""
        return self

    @property
    def sha256(self):
        return hash_state.restoreHex(self.state['sha256'], 'sha256').hexdigest()

    @property
    def md5(self):
        return hash_state.restoreHex(self.state['md5'], 'md5').hexdigest()


class TaleExporter:
    default_top_readme = """This zip file contains the code, data, and information about a Tale.

    Directory Structure:
       metadata/: Holds information about the runtime environment and Tale attributes
       workspace/: Contains the files and folders that were used in the Tale
       LICENSE: The license that the code and data falls under
       README.md: This file"""
    default_bagit = "BagIt-Version: 0.97\nTag-File-Character-Encoding: UTF-8\n"

    def __init__(self, user, manifest, environment, algs=None):
        self.user = user
        self.manifest = manifest
        self.environment = environment

        if algs is None:
            self.algs = ["md5", "sha1", "sha256"]

        zipname = os.path.basename(manifest["dct:hasVersion"]["@id"])
        self.zip_generator = ziputil.ZipGenerator(zipname)
        license_spdx = next(
            (
                agg["schema:license"]
                for agg in manifest["aggregates"]
                if "schema:license" in agg
            ),
            WholeTaleLicense.default_spdx()
        )
        self.tale_license = WholeTaleLicense().license_from_spdx(license_spdx)
        self.state = {}
        for alg in self.algs:
            self.state[alg] = []

    def list_files(self):
        """
        List contents of the version workspace and run directories.

        Returns a tuple for each file:
           fullpath - absolute path to a file
           relpath - path to a file relative to workspace root
        """
        for obj in [self.manifest["dct:hasVersion"]] + self.manifest["wt:hasRecordedRuns"]:
            uri = obj["@id"]
            obj_type = obj["@type"]
            obj_id = uri.rsplit("/", 1)[-1]
            folder = Folder().load(obj_id, user=self.user, level=AccessType.READ)
            workspace_path = folder["fsPath"] + "/workspace"
            for curdir, _, files in os.walk(workspace_path):
                for fname in files:
                    fullpath = os.path.join(curdir, fname)
                    if obj_type == "wt:RecordedRun":
                        relpath = fullpath.replace(workspace_path, "runs/" + obj["schema:name"])
                    else:
                        relpath = fullpath.replace(workspace_path, "workspace")
                    yield fullpath, relpath

    @staticmethod
    def bytes_from_file(filename, chunksize=8192):
        with open(filename, mode="rb") as f:
            while True:
                chunk = f.read(chunksize)
                if chunk:
                    yield chunk
                else:
                    break

    def stream(self):
        raise NotImplementedError

    @staticmethod
    def stream_string(string):
        return (_.encode() for _ in (string,))

    def dump_and_checksum(self, func, zip_path):
        hash_file_stream = HashFileStream(func)
        for data in self.zip_generator.addFile(hash_file_stream, zip_path):
            yield data
        # MD5 is the only required alg in profile. See Manifests-Required in
        # https://raw.githubusercontent.com/fair-research/bdbag/master/profiles/bdbag-ro-profile.json
        self.state['md5'].append((zip_path, hash_file_stream.md5))

    def _agg_index_by_uri(self, uri):
        aggs = self.manifest["aggregates"]
        return next((i for (i, d) in enumerate(aggs) if d['uri'] == uri), None)

    def append_aggergate_checksums(self):
        """
        Takes the md5 checksums and adds them to the files in the 'aggregates' section
        :return: None
        """
        aggs = self.manifest["aggregates"]
        for path, chksum in self.state['md5']:
            uri = "./" + path.replace("data/", "", 1)
            index = self._agg_index_by_uri(uri)
            if index is not None:
                aggs[index]['wt:md5'] = chksum
        self.verify_aggregate_checksums()

    def verify_aggregate_checksums(self):
        """Check if every aggregate has a proper checksum."""
        algs = {f"wt:{alg}" for alg in self.algs}
        for index, agg in enumerate(self.manifest["aggregates"]):
            if algs - set(agg.keys()) == algs:
                try:
                    req = requests.get(agg["uri"], allow_redirects=True, stream=True)
                except requests.exceptions.InvalidSchema:
                    # globus...
                    continue
                md5sum = md5()
                for chunk in req.iter_content(chunk_size=4096):
                    md5sum.update(chunk)
                self.manifest["aggregates"][index]["wt:md5"] = md5sum.hexdigest()

    def append_aggregate_filesize_mimetypes(self):
        """
        Adds the file size and mimetype to the workspace files
        :return: None
        """
        magic_wrapper = magic.Magic(mime=True, uncompress=True)
        aggs = self.manifest["aggregates"]
        for fullpath, relpath in self.list_files():
            uri = "./" + relpath
            index = self._agg_index_by_uri(uri)
            if index is not None:
                aggs[index]["wt:mimeType"] = (
                    magic_wrapper.from_file(fullpath) or "application/octet-stream"
                )
                aggs[index]["wt:size"] = os.path.getsize(fullpath)

    def append_extras_filesize_mimetypes(self, extra_files):
        """
        Appends the mimetype and size to the extra files in the 'aggregates 'section
        :param extra_files: Dictionary of extra file names
        :type extra_files: dict
        :return: None
        """
        aggs = self.manifest["aggregates"]
        for path, content in extra_files.items():
            uri = "./" + path.replace("data/", "", 1)
            index = self._agg_index_by_uri(uri)
            if index is not None:
                aggs[index]["wt:mimeType"] = "text/plain"
                aggs[index]["wt:size"] = len(content)

    @staticmethod
    def formated_dump(obj, **kwargs):
        return json.dumps(
            obj, cls=JsonEncoder, sort_keys=True, allow_nan=False, **kwargs
        )
