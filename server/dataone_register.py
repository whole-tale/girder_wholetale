"""
Code for querying DataONE and verifying query results. Specifically used for
 finding datasets based on the url and for listing package contents. Some of
  these methods are used elsewhere in the WholeTale plugin, specifically in  the harvester.
"""

import re
import json
import six.moves.urllib as urllib
import requests

from girder import logger
from girder.api.rest import RestException
from .constants import DataONELocations


def esc(value):
    """
    Escape a string so it can be used in a Solr query string
    :param value: The string that will be escaped
    :type value: str
    :return: The escaped string
    :rtype: str
    """
    return urllib.parse.quote_plus(value)


def unesc(value):
    """
    Un-escapes a string so it can used in URLS.
    :param value: The string that will be un-escaped
    :type value: str
    :return: The un-escaped string
    :rtype: str
    """
    return urllib.parse.unquote_plus(value)


def query(q,
          base_url=DataONELocations.prod_cn,
          fields=["identifier"],
          rows=1000,
          start=0,
          test=False):
    """
    Query a DataONE Solr index.
    :param q: The query
    :param base_url: The URL to the coordinating node
    :param fields: The field to search for
    :param rows: Number of rows to return
    :param start: Which row to start at
    :param test: Flag used when registering data from dev.nceas
    :return: The content of the response
    """

    """
    Create the query section of the url. Note that the DataONE Python library
     has functionality for solr queries. If time permits or if errors occur
     in this area, it is worth looking into refactoring with it.
    """
    fl = ",".join(fields)
    query_url = "{}/query/solr/?q={}&fl={}&rows={}&start={}&wt=json".format(
        base_url, q, fl, rows, start)

    try:
        req = requests.get(query_url)
        req.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise RestException(e)
    content = json.loads(req.content.decode('utf8'))

    # Fail if the Solr query failed rather than fail later
    if content['responseHeader']['status'] != 0:
        raise RestException(
            "Solr query was not successful.\n{}\n{}".format(query_url, content))

    # Stop if the number of results is equal to the number of rows requested
    # Fix this in the future by supporting paginated queries.
    if content['response']['numFound'] == rows:
        raise RestException(
            "Number of results returned equals number of rows requested. "
            "This could mean the query result is truncated. "
            "Implement paged queries.")

    return content


def find_resource_pid(pid, base_url):
    """
    Find the PID of the resource map for a given PID, which may be a resource map.
    :param pid: The pid of the object on DataONE
    :param base_url: The base url of the node endpoint that will be used for the search
    :type pid: str
    :type base_url: str
    :return:
    """

    result = query(
        q="identifier:\"{}\"".format(esc(pid)),
        base_url=base_url,
        fields=["identifier", "formatType", "formatId", "resourceMap"])
    result_len = int(result['response']['numFound'])

    if result_len == 0:
        error_msg = 'No object was found in the index for {}.'.format(pid)
        logger.warning(error_msg)
        raise RestException(error_msg)
    elif result_len > 1:
        error_msg = 'More than one object was found in the index for the identifier ' \
                    '{} which is an unexpected state.'.format(pid)
        logger.warning(error_msg)
        raise RestException(error_msg)

    # Find out if the PID is an OAI-ORE PID and return early if so
    try:
        if result['response']['docs'][0]['formatType'] == 'RESOURCE':
            return(result['response']['docs'][0]['identifier'])
    except KeyError:
        error_msg = 'Unable to find a resource file in the data package'
        logger.warning(error_msg)
        raise RestException(error_msg)

    try:
        if len(result['response']['docs'][0]['resourceMap']) == 1:
            return result['response']['docs'][0]['resourceMap'][0]
    except KeyError:
        raise RestException('Unable to find a resource map for the data package')

    if len(result['response']['docs'][0]['resourceMap']) > 1:
        # Extract all of the candidate resource map PIDs (list of lists)
        resmaps = [doc['resourceMap'] for doc in result['response']['docs']]

        # Flatten the above result out and query
        # Flattening is required because the above 'resourceMap' field is a
        # Solr array type so the result is a list of lists
        nonobs = find_nonobsolete_resmaps(
            [item for items in resmaps for item in items],
            base_url=base_url)

        # Only return of one non-obsolete Resource Map was found
        # If we find multiple, that implies the original PID we queried for
        # is a member of multiple packages and what to do isn't implemented
        if len(nonobs) == 1:
            return nonobs[0]

    # Error out if the document passed in has multiple resource maps. What I can
    # still do here is determine the most likely resource map given the set.
    # Usually we do this by rejecting any obsoleted resource maps and that
    # usually leaves us with one.
    raise RestException(
        "Multiple resource maps were for the data package, which isn't supported.")


def find_nonobsolete_resmaps(pids, base_url):
    """
    Given one or more resource map pids, returns the ones that are not obsoleted
    by any other Object.
    This is done by querying the Solr index with the -obsoletedBy:* query param

    :param pids: The pids that are checked
    :param base_url: A coordinating node that will be used to check
    :return:
    """

    result = query(
        "identifier:(\"{}\")+AND+-obsoletedBy:*".format("\" OR \"".join(pids),
                                                        base_url=base_url,
                                                        fields="identifier"))
    result_len = int(result['response']['numFound'])

    if result_len == 0:
        raise RestException('No results were found for identifier(s): {}.'.format(", ".join(pids)))

    return [doc['identifier'] for doc in result['response']['docs']]


def find_initial_pid(path):
    """
    Extracts the pid from an arbitrary path to a DataOne object.
    Supports:
       - HTTP & HTTPS
       - The MetacatUI landing page (#view)
       - The D1 v2 Object URI (/object)
       - The D1 v2 Resolve URI (/resolve)

    :param path:
    :type path: str
    :return: The object's pid, or the original path if one wasn't found
    :rtype: str
    """

    # http://blog.crossref.org/2015/08/doi-regular-expressions.html
    doi_regex = re.compile('(10.\d{4,9}/[-._;()/:A-Z0-9]+)', re.IGNORECASE)
    doi = doi_regex.search(path)
    if re.search(r'^http[s]?:\/\/search.dataone.org\/#view\/', path):
        return re.sub(
            r'^http[s]?:\/\/search.dataone.org\/#view\/', '', path)
    elif re.search(r'\Ahttp[s]?:\/\/cn[a-z\-\d\.]*\.dataone\.org\/cn\/v\d\/[a-zA-Z]+\/.+\Z', path):
        return re.sub(
            r'\Ahttp[s]?:\/\/cn[a-z\-\d\.]*\.dataone\.org\/cn\/v\d\/[a-zA-Z]+\/', '', path)
    if re.search(r'^http[s]?:\/\/dev.nceas.ucsb.edu\/#view\/', path):
        return re.sub(
            r'^http[s]?:\/\/dev.nceas.ucsb.edu\/#view\/', '', path)
    elif doi is not None:
        return 'doi:{}'.format(doi.group())
    else:
        return path


def get_package_pid(path, base_url):
    """
    Get the pid of a package from its path.
    :param path: The path to a DataONE object
    :param base_url: The node endpoint that will be used to perform the search
    :type path: str
    :type base_url: str
    :return: The package's pid
    """

    initial_pid = find_initial_pid(path)
    pid = find_resource_pid(initial_pid, base_url)
    return pid


def extract_metadata_docs(docs):
    metadata = [doc for doc in docs if doc['formatType'] == 'METADATA']
    if not metadata:
        raise RestException('No metadata file was found in the package.')
    return metadata


def extract_data_docs(docs):
    data = [doc for doc in docs if doc['formatType'] == 'DATA']
#    if not data:
#        raise RestException('No data found.')
    return data


def extract_resource_docs(docs):
    resource = [doc for doc in docs if doc['formatType'] == 'RESOURCE']
    return resource


def D1_lookup(path, base_url):
    """
    Lookup and return information about a package on the
    DataONE network.
    :param path: The path to a DataONE object
    :param base_url: The patht to a node endpoint
    :type path: str
    :type base_url: str
    :return:
    """

    package_pid = get_package_pid(path, base_url)
    docs = get_documents(package_pid, base_url)

    if not docs:
        raise RestException('Failed to find any documents in the provided package')
    # Filter the Solr result by TYPE so we can construct the package
    metadata = [doc for doc in docs if doc['formatType'] == 'METADATA']
    if not metadata:
        raise RestException('No metadata found.')

    # Compute package size (sum of 'size' values)
    total_size = sum([int(doc.get('size', 0)) for doc in docs])

    dataMap = {
        'dataId': package_pid,
        'size': total_size,
        'name': metadata[0].get('title', 'no title'),
        'doi': metadata[0].get('identifier', 'no DOI').split('doi:')[-1],
        'repository': 'DataONE',
    }
    return dataMap


def get_documents(package_pid, base_url):
    """
    Retrieve a list of all the files in a data package. The metadata
    record providing information about the package is also in this list.
    """

    result = query(q='resourceMap:"{}"'.format(esc(package_pid)),
                   fields=["identifier", "formatType", "title", "size", "formatId",
                           "fileName", "documents"],
                   base_url=base_url)

    if 'response' not in result or 'docs' not in result['response']:
        raise RestException(
            "Failed to get a result for the query\n {}".format(result))

    return result['response']['docs']


def check_multiple_maps(documenting):
    if len(documenting) > 1:
        raise RestException(
            "Found two objects in the resource map documenting other objects. "
            "This is unexpected and unhandled.")
    elif len(documenting) == 0:
        raise RestException('No object was found in the resource map.')


def check_multiple_metadata(metadata):
    if len(metadata) > 1:
        raise RestException("Multiple documenting metadata objects found. "
                            "This is unexpected and unhandled.")


def get_package_list(path, base_url, package=None, isChild=False):
    """

    :param path:
    :param package:
    :param isChild:
    :return:
    """

    if package is None:
        package = {}

    package_pid = get_package_pid(path, base_url)

    docs = get_documents(package_pid, base_url)

    # Filter the Solr result by TYPE so we can construct the package
    metadata = extract_metadata_docs(docs)
    data = extract_data_docs(docs)
    children = extract_resource_docs(docs)

    # Determine the folder name. This is usually the title of the metadata file
    # in the package but when there are multiple metadata files in the package,
    # we need to figure out which one is the 'main' or 'documenting' one.
    primary_metadata = [doc for doc in metadata if 'documents' in doc]

    check_multiple_metadata(primary_metadata)

    data += [doc for doc in metadata if doc['identifier'] != primary_metadata[0]['identifier']]

    fileList = get_package_files(data, metadata, primary_metadata)

    # Add a new entry in the package structure
    # if isChild:
    #    package[-1][primary_metadata[0]['title']] = {'fileList': []}
    # else:
    package[primary_metadata[0]['title']] = {'fileList': []}

    package[primary_metadata[0]['title']]['fileList'].append(fileList)
    if children is not None and len(children) > 0:
        for child in children:
            get_package_list(child['identifier'],
                             base_url=base_url,
                             package=package[primary_metadata[0]['title']],
                             isChild=True)
    return package


def get_package_files(data, metadata, primary_metadata):
    fileList = {}
    for fileObj in data:
        fileName = fileObj.get('fileName', fileObj.get('identifier', ''))

        fileSize = int(fileObj.get('size', 0))

        fileList[fileName] = {
            'size': fileSize
        }

    # Also add the metadata to the file list
    fileList[primary_metadata[0]['fileName']] = {
        'size': primary_metadata[0].get('size', 0)
    }

    return fileList
