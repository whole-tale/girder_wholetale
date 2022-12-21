from datetime import datetime, timezone
from hashlib import sha1, sha256, md5
import os
from urllib.parse import unquote
import requests
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
# Use repo2docker to build the image from the workspace
docker run  \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "`pwd`/data/workspace:{targetMount}/workspace" \
  -v "`pwd`/metadata/environment.json:{targetMount}/workspace/environment.json" \
  --privileged=true \
  -e DOCKER_HOST=unix:///var/run/docker.sock \
  {repo2docker} \
  jupyter-repo2docker \
    --config=/wholetale/repo2docker_config.py \
    --target-repo-dir={targetMount}/workspace \
    --user-id=1000 --user-name={user} \
    --no-clean --no-run --debug \
    --image-name {image_name} \
    {targetMount}/workspace
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

        # Create the fetch file
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

        now = datetime.now(timezone.utc)
        bag_info = bag_info_tpl.format(
            bag_profile=bag_profile,
            date=now.strftime('%Y-%m-%d'),
            time=now.strftime('%H:%M:%S %Z'),
            oxum="{size}.{num}".format(**oxum),
        )

        def dump_checksums(alg):
            dump = ""
            for path, chksum in self.state[alg]:
                dump += f"{chksum} {path}\n"
            for bundle in self.manifest['aggregates']:
                if 'bundledAs' not in bundle:
                    continue
                try:
                    chksum = bundle[f"wt:{alg}"]
                    folder = f"data{unquote(bundle['bundledAs']['folder'])[1:]}"
                    filename = unquote(bundle['bundledAs'].get('filename', ''))
                    dump += f"{chksum} {os.path.join(folder, filename)}\n"
                except KeyError:
                    pass
            return dump

        tagmanifest = dict(md5="", sha1="", sha256="")
        for payload, fname in (
            (lambda: top_readme, 'README.md'),
            (lambda: run_file, 'run-local.sh'),
            (lambda: self.default_bagit, 'bagit.txt'),
            (lambda: bag_info, 'bag-info.txt'),
            (lambda: fetch_file, 'fetch.txt'),
            (lambda: dump_checksums('md5'), 'manifest-md5.txt'),
            (lambda: dump_checksums('sha1'), 'manifest-sha1.txt'),
            (lambda: dump_checksums('sha256'), 'manifest-sha256.txt'),
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
            yield from self.zip_generator.addFile(payload, fname)

        for payload, fname in (
            (lambda: tagmanifest['md5'], 'tagmanifest-md5.txt'),
            (lambda: tagmanifest['sha1'], 'tagmanifest-sha1.txt'),
            (lambda: tagmanifest['sha256'], 'tagmanifest-sha256.txt'),
        ):
            yield from self.zip_generator.addFile(payload, fname)

        yield self.zip_generator.footer()

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

        for obj in self.manifest['schema:hasPart']:
            if ('schema:applicationCategory' in
                    obj and obj['schema:applicationCategory'] == 'DockerImage'):
                image_digest = obj['@id']
                break
        else:
            raise RuntimeError("Unable to find image in the manifest")

        image_name, reference = image_digest.split(":")
        image_name = image_name.split(":")[0]  # Tag is ignored GET /manifest"
        image_name = image_name.replace("/tale", "/v2/tale")
        response = requests.get(f"https://{image_name}/tags/list")

        build_cmd = ''
        try:
            response.raise_for_status()
            assert reference in response.json()["tags"]
        except (requests.exceptions.HTTPError, AssertionError):
            # No image
            build_cmd = build_tpl.format(
                repo2docker=container_config.get('repo2docker_version', REPO2DOCKER_VERSION),
                user=container_config['user'],
                targetMount=container_config['targetMount'],
                image_name=image_digest
            )

        return run_tpl.format(
            build_cmd=build_cmd,
            repo2docker=container_config.get('repo2docker_version', REPO2DOCKER_VERSION),
            port=container_config['port'],
            image_name=image_digest,
            command=rendered_command,
            targetMount=container_config['targetMount'],
            urlPath=urlPath,
        )
