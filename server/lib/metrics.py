import cherrypy
import datetime
import logging
from girder.models.model_base import Model
from girder.api.rest import getCurrentUser


metricsLogger = logging.getLogger("metrics")


class Record(Model):
    def initialize(self):
        self.name = "metrics_record"

    def validate(self, doc):
        return doc


class _MetricsHandler(logging.Handler):
    def handle(self, record):
        user = getCurrentUser()
        user_id = (user and user["_id"]) or record.details.pop("userId", None)
        Record().save(
            {
                "type": record.msg,
                "details": record.details,
                "ip": cherrypy.request.remote.ip,
                "userId": user_id,
                "when": datetime.datetime.utcnow(),
            },
            triggerEvents=False,
        )
