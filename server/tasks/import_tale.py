#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cherrypy
import datetime
import os
import pathlib
import sys
import traceback
from fs.osfs import OSFS
from fs.copy import copy_fs
from girder import events
from girder.api.rest import setCurrentUser
from girder.models.folder import Folder
from girder.models.upload import Upload
from girder.models.user import User
from girder.utility import parseTimestamp
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.jobs.models.job import Job
from urllib.parse import unquote

from ..constants import TaleStatus
from ..lib.manifest_parser import ManifestParser
from ..models.tale import Tale
from ..utils import notify_event


def run(job):
    jobModel = Job()
    jobModel.updateJob(job, status=JobStatus.RUNNING)

    tale_dir, manifest_file = job["args"]
    user = User().load(job["userId"], force=True)
    tale = Tale().load(job["kwargs"]["taleId"], user=user)

    progressTotal = 3
    progressCurrent = 0

    try:
        notify_event([user["_id"]], "wt_import_started", {"taleId": tale["_id"]})

        os.chdir(tale_dir)
        mp = ManifestParser(manifest_file)

        # 1. Register data
        progressCurrent += 1
        jobModel.updateJob(
            job,
            status=JobStatus.RUNNING,
            progressTotal=progressTotal,
            progressCurrent=progressCurrent,
            progressMessage="Registering external data",
        )
        Tale().restore_external_data(tale, mp, user=user)

        # 1a. Upload raw data
        orig_tale_id = pathlib.Path(manifest_file).parts[0]
        for agg in mp.manifest["aggregates"]:
            if not agg["uri"].startswith("./data"):
                continue
            target_path = pathlib.Path(unquote(agg["uri"][7:]))
            target_folder = Tale().getDataDir(tale)
            for subfolder in target_path.parts[:-1]:
                target_folder = Folder().createFolder(
                    target_folder,
                    subfolder,
                    parentType="folder",
                    creator=user,
                    reuseExisting=True,
                )
            data_path = os.path.join(orig_tale_id, "data", unquote(agg["uri"][2:]))
            with open(data_path, "rb") as fp:
                Upload().uploadFromFile(
                    fp,
                    agg["wt:size"],
                    target_path.parts[-1],
                    parentType="folder",
                    parent=target_folder,
                    user=user,
                    mimeType=agg["wt:mimeType"],
                )

        events.daemon.trigger(
            eventName="tale.update_citation", info={"tale": tale, "user": user}
        )

        # 4. Copy data to the workspace
        progressCurrent += 1
        jobModel.updateJob(
            job,
            status=JobStatus.RUNNING,
            progressTotal=progressTotal,
            progressCurrent=progressCurrent,
            progressMessage="Copying files to workspace",
        )
        for workdir in ("workspace", "data/workspace"):
            workdir = os.path.join(orig_tale_id, workdir)
            if os.path.isdir(workdir):
                workspace = Folder().load(tale["workspaceId"], force=True)
                workspace_path = pathlib.Path(workspace["fsPath"])
                copy_fs(OSFS(workdir), OSFS(workspace_path))
                break

        # Create a version
        version_obj = mp.manifest.get(
            "dct:hasVersion",
            {
                "schema:name": None,
                "schema:dateModified": datetime.datetime.utcnow(),
                "schema:dateCreated": datetime.datetime.utcnow(),
            },
        )
        for date_key in ("schema:dateCreated", "schema:dateModified"):
            if isinstance(version_obj.get(date_key), str):
                version_obj[date_key] = parseTimestamp(version_obj[date_key])
            else:
                version_obj[date_key] = datetime.datetime.utcnow()
        api_root = cherrypy.tree.apps["/api"]
        version_resource = api_root.root.v1.version
        setCurrentUser(user)
        version = version_resource.create(
            taleId=tale["_id"], name=version_obj["schema:name"], params={}
        )
        version = Folder().load(version["_id"], force=True)  # above is filtered...
        version["meta"] = {"publishInfo": tale["publishInfo"]}
        version["updated"] = version_obj["schema:dateModified"]
        version["created"] = version_obj["schema:dateCreated"]
        version = Folder().save(version)

        # Create potential runs
        orig_tale_id = pathlib.Path(manifest_file).parts[0]
        orig_runs_dir = pathlib.Path(orig_tale_id) / "data" / "runs"
        run_resource = api_root.root.v1.run
        for run_obj in mp.manifest.get("wt:hasRecordedRuns", []):
            orig_run_dir = orig_runs_dir / run_obj["schema:name"]
            run = run_resource.create(
                versionId=version["_id"], name=run_obj["schema:name"], params={}
            )
            run = Folder().load(run["_id"], force=True)  # we need fsPath
            dest_run_dir = pathlib.Path(run["fsPath"]) / "workspace"
            if orig_run_dir.is_dir():
                copy_fs(OSFS(orig_run_dir), OSFS(dest_run_dir))
            run["updated"] = parseTimestamp(run_obj["schema:dateModified"])
            run["created"] = parseTimestamp(run_obj["schema:dateCreated"])
            # vv calls save()
            run_resource.setStatus(
                id=run["_id"], status=int(run_obj["wt:runStatus"]), params={}
            )

        # Tale is ready to be built
        Tale().update(
            {"_id": tale["_id"]},
            update={
                "$set": {"status": TaleStatus.READY, "restoredFrom": version["_id"]}
            },
        )

        progressCurrent += 1
        jobModel.updateJob(
            job,
            status=JobStatus.SUCCESS,
            log="Tale created",
            progressTotal=progressTotal,
            progressCurrent=progressCurrent,
            progressMessage="Tale created",
        )

        notify_event([user["_id"]], "wt_import_completed", {"taleId": tale["_id"]})
    except Exception:
        Tale().update(
            {"_id": tale["_id"]}, update={"$set": {"status": TaleStatus.ERROR}}
        )
        t, val, tb = sys.exc_info()
        log = "%s: %s\n%s" % (t.__name__, repr(val), traceback.extract_tb(tb))
        jobModel.updateJob(job, status=JobStatus.ERROR, log=log)
        notify_event([user["_id"]], "wt_import_failed", {"taleId": tale["_id"]})
        raise
