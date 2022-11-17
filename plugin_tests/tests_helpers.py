import httmock


@httmock.all_requests
def mockOtherRequest(url, request):
    raise Exception("Unexpected url %s" % str(request.url))


def get_events(test, since, user=None):
    if not user:
        user = test.user

    resp = test.request(
        path="/notification", method="GET", user=user, params={"since": since}
    )
    test.assertStatusOk(resp)

    return [event for event in resp.json if event["type"] == "wt_event"]


def event_types(events, affected_resources):
    return {
        event["data"]["event"]
        for event in events
        if affected_resources == event["data"]["affectedResourceIds"]
    }
