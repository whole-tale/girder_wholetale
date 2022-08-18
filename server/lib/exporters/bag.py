from datetime import datetime, timezone
from hashlib import sha1, sha256, md5, sha512
import os
from urllib.parse import unquote
from girder.models.file import File

from . import TaleExporter
from gwvolman.constants import REPO2DOCKER_VERSION


bag_profile = (
    "https://raw.githubusercontent.com/fair-research/bdbag/"
    "master/profiles/bdbag-ro-profile.json"
)
bag_info_tpl = """Bag-Software-Agent: WholeTale version: 0.7
BagIt-Profile-Identifier: {bag_profile}
Bagging-Date: {date}
Bagging-Time: {time}
Payload-Oxum: {oxum}
"""

build_tpl = r"""
# Use repo2docker to build the image from the workspace when no image digest
docker run  \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "`pwd`/data/workspace:/WholeTale/workspace" \
  -v "`pwd`/metadata/environment.json:/WholeTale/workspace/environment.json" \
  --privileged=true \
  -e DOCKER_HOST=unix:///var/run/docker.sock \
  {repo2docker} \
  jupyter-repo2docker \
    --config=/wholetale/repo2docker_config.py \
    --target-repo-dir=/WholeTale/workspace \
    --user-id=1000 --user-name={user} \
    --no-clean --no-run --debug \
    --image-name {image_name} \
    /WholeTale/workspace
"""

run_tpl = r"""#!/bin/sh

{build_cmd}

docker run --rm \
    -v "`pwd`:/bag" \
    -ti {repo2docker} bdbag --resolve-fetch all /bag

echo "========================================================================"
echo " Open your browser and go to: http://localhost:{port}/{urlPath} "
echo "========================================================================"

# Run the built image
docker run -p {port}:{port} \
  -v "`pwd`/data/data:{targetMount}/data" \
  -v "`pwd`/data/workspace:{targetMount}/workspace" \
  {image_name} {command}
"""


readme_tpl = """# Tale: "{title}" in BDBag Format

{description}

# Running locally

If you have Docker installed, you can run this Tale locally using the
following command:

```
sh ./run-local.sh
```

Access on http://localhost:{port}/{urlPath}
"""


class BagTaleExporter(TaleExporter):
    def stream(self):
        token = 'wholetale'
        container_config = self.environment["config"]
        urlPath = container_config['urlPath'].format(token=token)

        run_file = self.format_run_file(container_config, urlPath, token)

        top_readme = readme_tpl.format(
            title=self.manifest["schema:name"],
            description=self.manifest["schema:description"],
            port=container_config['port'],
            urlPath=urlPath,
        )
        extra_files = {
            'data/LICENSE': self.tale_license['text'],
        }
        oxum = dict(size=0, num=0)

        # Add files from the workspace computing their checksum
        for fullpath, relpath in self.list_files():
            yield from self.dump_and_checksum(
                self.bytes_from_file(fullpath), 'data/' + relpath
            )
            oxum["num"] += 1
            oxum["size"] += os.path.getsize(fullpath)

        # Compute checksums for the extrafiles
        for path, content in extra_files.items():
            oxum['num'] += 1
            oxum['size'] += len(content)
            payload = self.stream_string(content)
            yield from self.dump_and_checksum(payload, path)

        for agg in self.manifest["aggregates"]:
            if not (agg["uri"].startswith("./data") and "wt:identifier" in agg):
                continue
            fobj = File().load(agg["wt:identifier"], force=True)
            path = "data/" + unquote(agg["uri"][2:])
            yield from self.zip_generator.addFile(File().download(fobj), path)
            oxum["num"] += 1
            oxum["size"] += agg["wt:size"]

        # Update manifest with hashes
        self.append_aggergate_checksums()

        # Update oxum with external data files
        external_data_oxum = self.calculate_data_oxum()
        oxum["num"] += external_data_oxum["num"]
        oxum["size"] += external_data_oxum["size"]

        # Update manifest with filesizes and mimeTypes for workspace items
        self.append_aggregate_filesize_mimetypes()

        # Update manifest with filesizes and mimeTypes for extra items
        self.append_extras_filesize_mimetypes(extra_files)

        now = datetime.now(timezone.utc)
        bag_info = bag_info_tpl.format(
            bag_profile=bag_profile,
            date=now.strftime('%Y-%m-%d'),
            time=now.strftime('%H:%M:%S %Z'),
            oxum="{size}.{num}".format(**oxum),
        )

        tagmanifest = dict(md5="", sha1="", sha256="", sha512="")
        for payload, fname in (
            (lambda: top_readme, 'README.md'),
            (lambda: run_file, 'run-local.sh'),
            (lambda: self.default_bagit, 'bagit.txt'),
            (lambda: bag_info, 'bag-info.txt'),
            (lambda: self.create_fetch_file(), 'fetch.txt'),
            (lambda: self.dump_checksums('md5'), 'manifest-md5.txt'),
            (lambda: self.dump_checksums('sha1'), 'manifest-sha1.txt'),
            (lambda: self.dump_checksums('sha256'), 'manifest-sha256.txt'),
            (lambda: self.dump_checksums('sha512'), 'manifest-sha512.txt'),
            (lambda: self.formated_dump(self.environment, indent=4), 'metadata/environment.json'),
            (lambda: self.formated_dump(self.manifest, indent=4), 'metadata/manifest.json'),
        ):
            tagmanifest['md5'] += "{} {}\n".format(
                md5(payload().encode()).hexdigest(), fname
            )
            tagmanifest['sha1'] += "{} {}\n".format(
                sha1(payload().encode()).hexdigest(), fname
            )
            tagmanifest['sha256'] += "{} {}\n".format(
                sha256(payload().encode()).hexdigest(), fname
            )
            tagmanifest['sha512'] += "{} {}\n".format(
                sha512(payload().encode()).hexdigest(), fname
            )
            yield from self.zip_generator.addFile(payload, fname)

        for payload, fname in (
            (lambda: tagmanifest['md5'], 'tagmanifest-md5.txt'),
            (lambda: tagmanifest['sha1'], 'tagmanifest-sha1.txt'),
            (lambda: tagmanifest['sha256'], 'tagmanifest-sha256.txt'),
            (lambda: tagmanifest['sha512'], 'tagmanifest-sha512.txt'),
        ):
            yield from self.zip_generator.addFile(payload, fname)

        yield self.zip_generator.footer()

    def create_fetch_file(self):
        fetch_file = ""
        for bundle in self.manifest['aggregates']:
            if 'bundledAs' not in bundle:
                continue
            # 'folder' is relative to root of a Tale, we need to adjust it
            # to make it relative to the root of the bag. It always startswith
            # "./"
            folder = f"data{unquote(bundle['bundledAs']['folder'])[1:]}"
            fetch_file += f"{bundle['uri']} {bundle['wt:size']} {folder}"
            fetch_file += unquote(bundle['bundledAs'].get('filename', ''))
            fetch_file += '\n'
        return fetch_file

    def dump_checksums(self, alg):
        dump = ""
        for path, chksum in self.state[alg]:
            dump += f"{chksum} {path}\n"
        for bundle in self.manifest['aggregates']:
            if 'bundledAs' not in bundle:
                path = "data/" + unquote(bundle["uri"][2:])
            else:
                folder = f"data{unquote(bundle['bundledAs']['folder'])[1:]}"
                filename = unquote(bundle['bundledAs'].get('filename', ''))
                path = os.path.join(folder, filename)
            try:
                chksum = bundle[f"wt:{alg}"]
                line = f"{chksum} {path}\n"
                if line not in dump:
                    dump += line
            except KeyError:
                pass
        return dump

    def calculate_data_oxum(self):
        oxum = {"num": 0, "size": 0}
        for agg in self.manifest["aggregates"]:
            if "bundledAs" not in agg:
                continue
            oxum["num"] += 1
            oxum["size"] += int(agg["wt:size"])
        return oxum

    def format_run_file(self, container_config, urlPath, token):

        rendered_command = container_config.get('command', '').format(
            base_path='', port=container_config['port'], ip='0.0.0.0', token=token
        )

        taleId = self.manifest["wt:identifier"]
        image_name = None
        for obj in self.manifest['schema:hasPart']:
            if ('schema:applicationCategory' in
                    obj and obj['schema:applicationCategory'] == 'DockerImage'):
                image_name = obj['@id']

        # If the tale doesn't have a built image, output the command
        # to build the image with r2d
        build_cmd = ''
        if image_name is None:
            image_name = f"wholetale/tale_{taleId}"
            build_cmd = build_tpl.format(
                repo2docker=container_config.get('repo2docker_version', REPO2DOCKER_VERSION),
                user=container_config['user'],
                image_name=image_name
            )

        return run_tpl.format(
            build_cmd=build_cmd,
            repo2docker=container_config.get('repo2docker_version', REPO2DOCKER_VERSION),
            port=container_config['port'],
            image_name=image_name,
            command=rendered_command,
            targetMount=container_config['targetMount'],
            urlPath=urlPath,
        )
