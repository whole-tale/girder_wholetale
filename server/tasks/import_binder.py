#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import stat
import sys
import time
import traceback
from fs.base import FS
from fs.copy import copy_fs
from fs.enums import ResourceType
from fs.errors import FileExpected
from fs.error_tools import convert_os_errors
from fs.info import Info
from fs.mode import Mode
from fs.osfs import OSFS
from fs.path import basename
from fs.permissions import Permissions
from fs.tarfs import ReadTarFS
from fs.zipfs import ReadZipFS
from girder import events
from girderfs.dms import WtDmsGirderFS
from girder_client import GirderClient
from girder.models.folder import Folder
from girder.models.notification import Notification
from girder.models.token import Token
from girder.models.user import User
from girder.utility import config, JsonEncoder
from girder.plugins.jobs.constants import JobStatus
from girder.plugins.jobs.models.job import Job

from ..constants import InstanceStatus, TaleStatus
from ..lib import pids_to_entities, register_dataMap
from ..lib.dataone import DataONELocations  # TODO: get rid of it
from ..models.instance import Instance
from ..models.tale import Tale
from ..utils import notify_event


def sanitize_binder(root):
    root_listdir = list(root.listdir("/"))

    if len(root_listdir) != 1:
        return

    single_file_or_dir = root_listdir[0]

    if root.isdir(single_file_or_dir):
        with root.opendir(single_file_or_dir) as subdir:
            copy_fs(subdir, root)
        root.removetree("/" + single_file_or_dir)
        sanitize_binder(root)

    if root.isfile(single_file_or_dir):
        if single_file_or_dir.endswith(".zip"):
            archive_fs = ReadZipFS
        elif ".tar" in single_file_or_dir:
            archive_fs = ReadTarFS
        else:
            archive_fs = None

        if archive_fs is not None:
            with archive_fs(root.openbin(single_file_or_dir)) as archive:
                copy_fs(archive, root)
            root.remove("/" + single_file_or_dir)
            sanitize_binder(root)


def folder_to_dataSet(resource, user):
    # Create a dataset with the content of root ds folder,
    # so that it looks nicely and it's easy to copy to workspace later on
    data_set = [
        {
            "itemId": str(folder["_id"]),
            "mountPath": folder["name"],
            "_modelType": "folder",
        }
        for folder in Folder().childFolders(
            parentType="folder", parent=resource, user=user
        )
    ]
    data_set += [
        {
            "itemId": str(item["_id"]),
            "mountPath": item["name"],
            "_modelType": "item",
        }
        for item in Folder().childItems(resource)
    ]
    return data_set


def run(job):
    jobModel = Job()
    jobModel.updateJob(job, status=JobStatus.RUNNING)

    (lookup_kwargs,) = job["args"]
    user = User().load(job["userId"], force=True)
    tale = Tale().load(job["kwargs"]["taleId"], user=user)
    spawn = job["kwargs"]["spawn"]
    asTale = job["kwargs"]["asTale"]
    token = Token().createToken(user=user, days=0.5)
    wt_notification = Notification().load(job["wt_notification_id"])

    progressTotal = wt_notification["data"]["total"]
    progressCurrent = 0

    try:
        notify_event([user["_id"]], "wt_import_started", {"taleId": tale["_id"]})

        # 0. Spawn instance in the background
        if spawn:
            instance = Instance().createInstance(tale, user, spawn=spawn)

        # 1. Register data using url
        jobModel.updateJob(
            job,
            status=JobStatus.RUNNING,
            progressTotal=progressTotal,
            progressCurrent=progressCurrent,
            progressMessage="Registering external data",
        )
        dataIds = lookup_kwargs.pop("dataId")
        base_url = lookup_kwargs.get("base_url", DataONELocations.prod_cn)
        dataMaps = pids_to_entities(
            dataIds, user=user, base_url=base_url, lookup=True
        )  # DataONE shouldn't be here
        ds_ids = register_dataMap(
            dataMaps,
            Tale().getDataDir(tale),
            "folder",
            user=user,
            base_url=base_url,
        )

        if asTale:
            # 2. Create a session
            # TODO: yay circular dependencies! IMHO we really should merge
            # wholetale and wt_data_manager plugins...
            from girder.plugins.wt_data_manager.models.session import Session

            data_dir = Tale().getDataDir(tale)
            data_set = []
            for item in Folder().childItems(folder=data_dir):
                data_set.append(
                    {
                        "_modelType": "item",
                        "itemId": item["_id"],
                        "mountPath": item["name"],
                    }
                )

            for folder in Folder().childFolders(
                parentType="folder", parent=data_dir, user=user
            ):
                data_set.append(
                    {
                        "_modelType": "folder",
                        "itemId": folder["_id"],
                        "mountPath": folder["name"],
                    }
                )

            # Session is created so that we can easily copy files to workspace,
            # without worrying about how to handler transfers. DMS will do that for us <3
            session = Session().createSession(user, dataSet=data_set)

            # 3. Copy data to the workspace
            progressCurrent += 1
            jobModel.updateJob(
                job,
                status=JobStatus.RUNNING,
                log="Copying files to workspace",
                progressTotal=progressTotal,
                progressCurrent=progressCurrent,
                progressMessage="Copying files to workspace",
            )
            workspace = Folder().load(tale["workspaceId"], force=True)
            girder_root = "http://localhost:{}".format(
                config.getConfig()["server.socket_port"]
            )

            with OSFS(workspace["fsPath"]) as destination_fs, DMSFS(
                str(session["_id"]), girder_root + "/api/v1", str(token["_id"])
            ) as source_fs:
                copy_fs(source_fs, destination_fs)
                sanitize_binder(destination_fs)

            Session().deleteSession(user, session)
            for folder_id in ds_ids:
                Folder().remove(Folder().load(folder_id, force=True))
        else:
            # 3. Update Tale's dataSet
            progressCurrent += 1
            jobModel.updateJob(
                job,
                status=JobStatus.RUNNING,
                log="Updating datasets",
                progressTotal=progressTotal,
                progressCurrent=progressCurrent,
                progressMessage="Updating datasets",
            )

            eventParams = {"tale": tale, "user": user}
            events.daemon.trigger("tale.update_citation", eventParams)

        # Tale is ready to be built
        Tale().update(
            {"_id": tale["_id"]}, update={"$set": {"status": TaleStatus.READY}}
        )

        # 4. Wait for container to show up
        if spawn:
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

        notify_event([user["_id"]], "wt_import_completed", {"taleId": tale["_id"]})

    except Exception:
        Tale().update(
            {"_id": tale["_id"]}, update={"$set": {"status": TaleStatus.ERROR}}
        )
        t, val, tb = sys.exc_info()
        log = "%s: %s\n%s" % (t.__name__, repr(val), traceback.extract_tb(tb))
        jobModel.updateJob(
            job,
            progressTotal=progressTotal,
            progressCurrent=progressTotal,
            progressMessage="Task failed",
            status=JobStatus.ERROR,
            log=log,
        )
        notify_event([user["_id"]], "wt_import_failed", {"taleId": tale["_id"]})
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


class DMSFS(FS):
    """Wrapper for WtDmsGirderFS using pyfilesystem.

    This allows to access WtDMS in a pythonic way, without actually mounting it anywhere.
    """

    STAT_TO_RESOURCE_TYPE = {
        stat.S_IFDIR: ResourceType.directory,
        stat.S_IFCHR: ResourceType.character,
        stat.S_IFBLK: ResourceType.block_special_file,
        stat.S_IFREG: ResourceType.file,
        stat.S_IFIFO: ResourceType.fifo,
        stat.S_IFLNK: ResourceType.symlink,
        stat.S_IFSOCK: ResourceType.socket,
    }

    def __init__(self, session_id, api_url, token):
        super().__init__()
        self.session_id = session_id
        gc = GirderClient(apiUrl=api_url)
        gc.token = token
        self._fs = WtDmsGirderFS(session_id, gc)

    def __repr__(self):
        return "{}({})".format(self.__class__.__name__, self.session_id)

    # Required methods
    def getinfo(self, path, namespaces=None):
        self.check()
        namespaces = namespaces or ()
        _path = self.validatepath(path)
        _stat = self._fs.getinfo(_path)

        info = {
            "basic": {"name": basename(_path), "is_dir": stat.S_ISDIR(_stat["st_mode"])}
        }

        if "details" in namespaces:
            info["details"] = {
                "_write": ["accessed", "modified"],
                "accessed": _stat["st_atime"],
                "modified": _stat["st_mtime"],
                "size": _stat["st_size"],
                "type": int(
                    self.STAT_TO_RESOURCE_TYPE.get(
                        stat.S_IFMT(_stat["st_mode"]), ResourceType.unknown
                    )
                ),
            }
        if "stat" in namespaces:
            info["stat"] = _stat

        if "access" in namespaces:
            info["access"] = {
                "permissions": Permissions(mode=_stat["st_mode"]).dump(),
                "uid": 1000,  # TODO: fix
                "gid": 100,  # TODO: fix
            }

        return Info(info)

    def listdir(self, path):
        return self._fs.listdir(path)

    def openbin(self, path, mode="r", buffering=-1, **options):
        _mode = Mode(mode)
        _mode.validate_bin()
        self.check()
        _path = self.validatepath(path)
        if _path == "/":
            raise FileExpected(path)
        with convert_os_errors("openbin", path):
            # TODO: I'm not sure if it's not leaving descriptors open...
            fd = self._fs.open(_path, os.O_RDONLY)
            fdict = self._fs.openFiles[path]
            self._fs._ensure_region_available(path, fdict, fd, 0, fdict["obj"]["size"])
            return open(fdict["path"], "r+b")

    def makedir(self, path, permissions=None, recreate=False):
        pass

    def remove(self, path):
        pass

    def removedir(self, path):
        pass

    def setinfo(self, path, info):
        pass
