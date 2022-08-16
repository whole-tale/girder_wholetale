import httmock


@httmock.all_requests
def mockOtherRequest(url, request):
    raise Exception('Unexpected url %s' % str(request.url))


def get_events(test, since, user=None):
    if not user:
        user = test.user

    resp = test.request(
        path="/notification", method='GET',
        user=user, params={'since': since})
    test.assertStatusOk(resp)

    return [event for event in resp.json if event['type'] == 'wt_event']


def event_types(events, affected_resources):
    return {
        event["data"]["event"]
        for event in events
        if affected_resources == event["data"]["affectedResourceIds"]
    }


def get_data_dir_content(tale, user):
    from girder.models.folder import Folder
    from girder.plugins.wholetale.models.tale import Tale

    tale = Tale().load(tale["_id"], force=True)
    data_dir = Tale().getDataDir(tale)
    dataset = set([_["name"] for _ in Folder().childItems(data_dir)])
    dataset |= set(
        [
            _["name"]
            for _ in Folder().childFolders(
                parentType="folder", parent=data_dir, user=user
            )
        ]
    )
    return dataset
