#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import sys
import traceback
from girder import events
from girder.constants import AccessType
from girder.models.folder import Folder
from girder.models.user import User
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.jobs.models.job import Job

from ..constants import TaleStatus
from ..models.tale import Tale


def run(job):
    jobModel = Job()
    jobModel.updateJob(job, status=JobStatus.RUNNING)

    old_tale = job["args"][0]
    new_tale = job["args"][1]
    user = User().load(new_tale["creatorId"], force=True)

    try:
        source_workspace = Folder().load(
            old_tale["workspaceId"], user=user, exc=True, level=AccessType.READ
        )
        workspace = Folder().load(new_tale["workspaceId"], user=user, exc=True)

        shutil.copytree(
            Path(source_workspace["fsPath"]),
            Path(workspace["fsPath"]),
            dirs_exist_ok=True,
        )

        # Copy data
        source_data_root = Folder().load(
            old_tale["dataDirId"], user=user, exc=True, level=AccessType.READ
        )
        dest_data_root = Folder().load(
            new_tale["dataDirId"], user=user, exc=True, level=AccessType.WRITE
        )
        # Remove 'current' that was created during Tale initialization
        Folder().clean(dest_data_root)
        # Copy data_dirs
        Folder().copyFolderComponents(source_data_root, dest_data_root, user, None)

        events.trigger("wholetale.tale.copied", job["args"])
        Tale().update(
            {"_id": new_tale["_id"]}, update={"$set": {"status": TaleStatus.READY}}
        )
        jobModel.updateJob(job, status=JobStatus.SUCCESS, log="Copying finished")
    except Exception:
        Tale().update(
            {"_id": new_tale["_id"]}, update={"$set": {"status": TaleStatus.ERROR}}
        )
        t, val, tb = sys.exc_info()
        log = "%s: %s\n%s" % (t.__name__, repr(val), traceback.extract_tb(tb))
        jobModel.updateJob(job, status=JobStatus.ERROR, log=log)
        raise
