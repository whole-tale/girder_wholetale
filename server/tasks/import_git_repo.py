#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import re
import shutil
import time

import git
from girder.models.folder import Folder
from girder.models.user import User
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.jobs.models.job import Job
from girder.utility import JsonEncoder

from ..constants import InstanceStatus, TaleStatus
from ..models.instance import Instance
from ..models.tale import Tale
from ..utils import notify_event


def run(job):
    jobModel = Job()
    jobModel.updateJob(job, status=JobStatus.RUNNING)

    (url,) = job["args"]
    if "@" in url:
        repo_url, branch = url.split("@")
    else:
        repo_url = url
        branch = None

    user = User().load(job["userId"], force=True)
    tale = Tale().load(job["kwargs"]["taleId"], user=user)
    spawn = job["kwargs"]["spawn"]
    change_status = job["kwargs"].get("change_status", True)
    # Get users for notifications since job can be called after a tale is shared
    users = [str(user["id"]) for user in tale["access"]["users"]]

    progressTotal = 1 + int(spawn)
    progressCurrent = 0

    try:
        notify_event(users, "wt_import_started", {"taleId": tale["_id"]})

        workspace = Folder().load(tale["workspaceId"], force=True)
        has_dot_git_already = os.path.isdir(os.path.join(workspace["fsPath"], ".git"))
        if has_dot_git_already:
            raise RuntimeError(
                "Workspace is already a git repository. You need to remove it "
                "before trying to add a new one."
            )

        # 1. Checkout the git repo
        jobModel.updateJob(
            job,
            status=JobStatus.RUNNING,
            progressTotal=progressTotal,
            progressCurrent=progressCurrent,
            progressMessage="Cloning the git repo",
        )

        try:
            repo = git.Repo.init(workspace["fsPath"])
            origin = repo.create_remote("origin", repo_url)
            origin.fetch()
            if not branch:
                gcmd = git.cmd.Git(workspace["fsPath"])
                remote_info = gcmd.execute(["git", "remote", "show", "origin"])
                branch = re.search("HEAD branch: (?P<branch>.*)\n", remote_info).group(
                    "branch"
                )
            repo.create_head(
                branch, origin.refs[branch]
            )  # create a local branch default from remote HEAD symref
            repo.heads[branch].set_tracking_branch(
                origin.refs[branch]
            )  # set the local branch to track the remote default branch
            repo.heads[branch].checkout()  # checkout the default branch to working tree
        except git.exc.GitCommandError as exc:
            raise RuntimeError("Failed to import from git:\n {}".format(str(exc)))

        # Tale is ready to be built
        Tale().update(
            {"_id": tale["_id"]}, update={"$set": {"status": TaleStatus.READY}}
        )

        # 4. Wait for container to show up
        if spawn:
            instance = Instance().createInstance(tale, user, spawn=spawn)
            progressCurrent += 1
            jobModel.updateJob(
                job,
                status=JobStatus.RUNNING,
                log="Waiting for a Tale container",
                progressTotal=progressTotal,
                progressCurrent=progressCurrent,
                progressMessage="Waiting for a Tale container",
            )

            sleep_step = 1
            timeout = 15 * 60
            while instance["status"] == InstanceStatus.LAUNCHING and timeout > 0:
                time.sleep(sleep_step)
                instance = Instance().load(instance["_id"], user=user)
                timeout -= sleep_step
                sleep_step = min(sleep_step * 2, 10)
            if timeout <= 0:
                raise RuntimeError(
                    "Failed to launch instance {}".format(instance["_id"])
                )
        else:
            instance = None

        notify_event(users, "wt_import_completed", {"taleId": tale["_id"]})

    except Exception as exc:
        dot_git = os.path.join(workspace["fsPath"], ".git")
        if not has_dot_git_already and os.path.isdir(dot_git):
            shutil.rmtree(dot_git, ignore_errors=True)
        if change_status:
            Tale().update(
                {"_id": tale["_id"]}, update={"$set": {"status": TaleStatus.ERROR}}
            )
        jobModel.updateJob(
            job,
            progressTotal=progressTotal,
            progressCurrent=progressTotal,
            progressMessage="Task failed",
            status=JobStatus.ERROR,
            log=str(exc),
        )
        notify_event(users, "wt_import_failed", {"taleId": tale["_id"]})
        raise

    # To get rid of ObjectId's, dates etc.
    tale = json.loads(
        json.dumps(tale, sort_keys=True, allow_nan=False, cls=JsonEncoder)
    )
    instance = json.loads(
        json.dumps(instance, sort_keys=True, allow_nan=False, cls=JsonEncoder)
    )

    jobModel.updateJob(
        job,
        status=JobStatus.SUCCESS,
        log="Tale created",
        progressTotal=progressTotal,
        progressCurrent=progressTotal,
        progressMessage="Tale created",
        otherFields={"result": {"tale": tale, "instance": instance}},
    )
