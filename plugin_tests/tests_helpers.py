import httmock


@httmock.all_requests
def mockOtherRequest(url, request):
    raise Exception('Unexpected url %s' % str(request.url))
