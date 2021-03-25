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

    old_tale, new_tale = job["args"]
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
        events.trigger("wholetale.tale.copied", (old_tale, new_tale))
        new_tale["status"] = TaleStatus.READY
        Tale().updateTale(new_tale)
        jobModel.updateJob(job, status=JobStatus.SUCCESS, log="Copying finished")
    except Exception:
        new_tale["status"] = TaleStatus.ERROR
        Tale().updateTale(new_tale)
        t, val, tb = sys.exc_info()
        log = "%s: %s\n%s" % (t.__name__, repr(val), traceback.extract_tb(tb))
        jobModel.updateJob(job, status=JobStatus.ERROR, log=log)
        raise
