#!/usr/bin/env python
# -*- coding: utf-8 -*-

import cherrypy
import os
import pathlib
import sys
import traceback
from webdavfs.webdavfs import WebDAVFS
from fs.osfs import OSFS
from fs.copy import copy_fs
from girder import events
from girder.api.rest import setCurrentUser
from girder.constants import TokenScope
from girder.models.folder import Folder
from girder.models.user import User
from girder.models.token import Token
from girder.utility import config
from girder.plugins.jobs.constants import JobStatus, REST_CREATE_JOB_TOKEN_SCOPE
from girder.plugins.jobs.models.job import Job

from ..constants import CATALOG_NAME, TaleStatus
from ..lib import pids_to_entities, register_dataMap
from ..lib.dataone import DataONELocations  # TODO: get rid of it
from ..lib.manifest_parser import ManifestParser
from ..models.tale import Tale
from ..utils import getOrCreateRootFolder, notify_event


def run(job):
    jobModel = Job()
    jobModel.updateJob(job, status=JobStatus.RUNNING)

    tale_dir, manifest_file = job["args"]
    user = User().load(job["userId"], force=True)
    tale = Tale().load(job["kwargs"]["taleId"], user=user)
    token = Token().createToken(
        user=user, days=0.5, scope=(TokenScope.USER_AUTH, REST_CREATE_JOB_TOKEN_SCOPE)
    )

    progressTotal = 3
    progressCurrent = 0

    try:
        notify_event([str(user["_id"])], "wt_import_started", "tale", tale['_id'])

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
        dataIds = mp.get_external_data_ids()
        if dataIds:
            dataMap = pids_to_entities(
                dataIds, user=user, base_url=DataONELocations.prod_cn, lookup=True
            )  # DataONE shouldn't be here
            register_dataMap(
                dataMap,
                getOrCreateRootFolder(CATALOG_NAME),
                "folder",
                user=user,
                base_url=DataONELocations.prod_cn,
            )

        # 2. Construct the dataSet
        dataSet = mp.get_dataset()

        # 3. Update Tale's dataSet
        update_citations = {_["itemId"] for _ in tale["dataSet"]} ^ {
            _["itemId"] for _ in dataSet
        }
        tale["dataSet"] = dataSet
        tale = Tale().updateTale(tale)

        if update_citations:
            eventParams = {"tale": tale, "user": user}
            event = events.trigger("tale.update_citation", eventParams)
            if len(event.responses):
                tale = Tale().updateTale(event.responses[-1])

        # 4. Copy data to the workspace using WebDAVFS (if it exists)
        progressCurrent += 1
        jobModel.updateJob(
            job,
            status=JobStatus.RUNNING,
            progressTotal=progressTotal,
            progressCurrent=progressCurrent,
            progressMessage="Copying files to workspace",
        )
        orig_tale_id = pathlib.Path(manifest_file).parts[0]
        for workdir in ("workspace", "data/workspace", None):
            if workdir:
                workdir = os.path.join(orig_tale_id, workdir)
                if os.path.isdir(workdir):
                    break

        if workdir:
            password = "token:{_id}".format(**token)
            root = "/tales/{_id}".format(**tale)
            url = "http://localhost:{}".format(config.getConfig()["server.socket_port"])
            with WebDAVFS(
                url, login=user["login"], password=password, root=root
            ) as webdav_handle:
                copy_fs(OSFS(workdir), webdav_handle)

        # Create a version
        if "dct:hasVersion" in mp.manifest:
            version_name = mp.manifest["dct:hasVersion"]["schema:name"]
        else:
            version_name = None
        api_root = cherrypy.tree.apps["/api"]
        version_resource = api_root.root.v1.version
        setCurrentUser(user)
        version = version_resource.create(
            taleId=tale["_id"], name=version_name, params={}
        )
        version = Folder().load(version["_id"], force=True)  # above is filtered...
        version["meta"] = {"publishInfo": tale["publishInfo"]}
        version = Folder().updateFolder(version)

        # Tale is ready to be built
        tale = Tale().load(tale["_id"], user=user)  # Refresh state
        tale["status"] = TaleStatus.READY
        tale["restoredFrom"] = version["_id"]
        tale = Tale().updateTale(tale)

        progressCurrent += 1
        jobModel.updateJob(
            job,
            status=JobStatus.SUCCESS,
            log="Tale created",
            progressTotal=progressTotal,
            progressCurrent=progressCurrent,
            progressMessage="Tale created",
        )

        notify_event([str(user["_id"])], "wt_import_completed", "tale", tale['_id'])
    except Exception:
        tale = Tale().load(tale["_id"], user=user)  # Refresh state
        tale["status"] = TaleStatus.ERROR
        tale = Tale().updateTale(tale)
        t, val, tb = sys.exc_info()
        log = "%s: %s\n%s" % (t.__name__, repr(val), traceback.extract_tb(tb))
        jobModel.updateJob(job, status=JobStatus.ERROR, log=log)
        notify_event([str(user["_id"])], "wt_import_failed", "tale", tale['_id'])
        raise
