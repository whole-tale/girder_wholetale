import json
from girder.utility import JsonEncoder
from . import TaleExporter


class NativeTaleExporter(TaleExporter):
    def stream(self):
        extra_files = {
            'README.md': self.default_top_readme,
            'LICENSE': self.tale_license['text'],
            'metadata/environment.json': json.dumps(
                self.get_environment(), indent=4, cls=JsonEncoder, sort_keys=True, allow_nan=False
            ),
        }

        # Add files from the workspace
        for fullpath, relpath in self.list_workspace():
            yield from self.dump_and_checksum(
                self.bytes_from_file(fullpath), 'workspace/' + relpath
            )

        # Compute checksums for extra files
        for path, content in extra_files.items():
            payload = self.stream_string(content)
            yield from self.dump_and_checksum(payload, path)

        # Update manifest with hashes
        self.append_aggergate_checksums()

        # Update manifest with filesizes and mimeTypes
        self.append_aggregate_filesize_mimetypes('../workspace/')

        # Update manifest with filesizes and mimeTypes for extra items
        self.append_extras_filesize_mimetypes(extra_files)

        for data in self.zip_generator.addFile(
            lambda: json.dumps(self.manifest, indent=4), 'metadata/manifest.json'
        ):
            yield data

        yield self.zip_generator.footer()
