#!/usr/bin/env python
# -*- coding: utf-8 -*-

from girder.models.user import User
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.jobs.models.job import Job

from ..lib import register_dataMap


def run(job):
    dataMap, parent, parentType, user = job["args"]
    base_url = job["kwargs"].get("base_url")
    # In case this job is a part of a more complex task, progressTotal and progressCurrent can be
    # passed as kwargs to take that into account
    progressTotal = job["kwargs"].get("progressTotal", 2)
    progressCurrent = job["kwargs"].get("progressCurrent", 0)

    progressCurrent += 1
    jobModel = Job()
    jobModel.updateJob(
        job,
        status=JobStatus.RUNNING,
        progressMessage="Registering Datasets",
        progressTotal=progressTotal,
        progressCurrent=progressCurrent,
    )

    # Notice progress=False below: we want to prevent default Girder progress notifications from
    # being emitted, since all we care about is the wt_notification encompassing this job. We lose a
    # lot of granularity here.
    # TODO: pass progress context associated with wt_notification perhaps?
    importedData = register_dataMap(
        dataMap, parent, parentType, user=user, base_url=base_url, progress=False
    )
    if importedData:
        user_data = set(user.get("myData", []))
        user["myData"] = list(user_data.union(set(importedData)))
        user = User().save(user)

    # For some reason updating both status and progress keywords swallows a notification. Let's do
    # it in two steps then.
    progressCurrent += 1
    jobModel.updateJob(
        job,
        progressMessage="Datasets registered",
        progressTotal=progressTotal,
        progressCurrent=progressCurrent,
    )
    jobModel.updateJob(job, status=JobStatus.SUCCESS)
