girder_wholetale |build-status| |codecov-badge|
###############################################

DO NOT MERGE

Girder plugin enabling intergration with tmpnb

.. |build-status| image:: https://circleci.com/gh/girder/girder.png?style=shield
    :target: https://circleci.com/gh/whole-tale/girder_wholetale
    :alt: Build Status

.. |codecov-badge| image:: https://img.shields.io/codecov/c/github/whole-tale/girder_wholetale.svg
    :target: https://codecov.io/gh/whole-tale/girder_wholetale
    :alt: Coverage Status

Development
===========

Installing Girder
-----------------
There are a couple of different ways to install Girder which are outlined `here <http://girder.readthedocs.io/en/latest/installation.html#sources>`_. Note that this should be done in a Python 3 environment.

Linking the plugin to Girder
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Once you have the repo cloned, you'll need to create a new folder named ``wholetale`` in the ``/grider/plugins/`` directory. The goal of the next step is to copy/link the contents of the cloned ``girder_wholetale`` directory into the ``wholetale`` directory.

To symbolically link the directory (so that any changes to ``girder_wholetale`` are reflected instantly), 
run ``girder-install plugin -s /path/to/your/plugin``

To copy the contents  instead, run
``girder-install plugin /path/to/your/plugin``

For more infomration visit the page on `Installing Third Party Plugins <http://girder.readthedocs.io/en/latest/installation.html#installing-third-party-plugins>`_

Installing the Web Service
^^^^^^^^^^^^^^^^^^^^^^^^^^
To install the web service, run
``girder-install web --all-plugins --dev``

Enabling Plugins
^^^^^^^^^^^^^^^^

To get to the plugins section, navigate to ``Admin Console``-> ``Plugins``. Make sure that the following plugins are enabled.

1. ``Celery Jobs``
2. ``Gravatar portraits``
3. ``Jobs``
4. ``OAuth2 login``
5. ``Remote worker``
6. ``wholetale``

OAuth
^^^^^
Instead of using the login screen in the dashboard, you'll use OAuth with GitHub to handle authentication. In the plugins menu, click the blue gear next to ``OAuth2 login``. Open a new tab with GitHub. Open your settings, and navigate to ``Developer Settings``, which is the last item in the navigation menu. Click the  ``New OAuth App`` button. Use the settings in the OAuth2 login settings to fill in the required information. Fill out the fields in the OAuth2 login plugin with the information provided by GitHub.

CORS Headers
^^^^^^^^^^^^
You'll want to allow CORS headers in the dashboard. To do this, navigate to  ``Admin Console``-> ``Server Configuration``. Scroll to the bottom of the page and click ``Advanced Settings``. Put ``*`` in the ``CORS Allowed Origins`` and ``CORS Allowed Headers`` fields. More information can be found 
`here <http://girder.readthedocs.io/en/latest/security.html#cors-cross-origin-resource-sharing>`_.

Create an Assetstore
^^^^^^^^^^^^^^^^^^^^
To allow uploading and registering data files in the dashboard, you'll need to create an `assetstore`. To do this, navigate to ``Admin Console``-> ``Assetstores``. Click ``Create new Filesystem assetstore``, name the assetstore, specify where on your local machine it will reside, and click the ``Create`` button.

Running Tests
-------------
This Girder plugin includes a set of tests in ``./plugin_tests``. To run these, you'll need to get a copy of the `WholeTale Fork of Girder`_ and run this plugin's test as part of Girder's test suite.

Pre-requisites:

- Python 3
- CMake
- An instance of MongoDB, running at mongodb://localhost:27101

Optional pre-requisites:

- coverage
- flake8

::

    $ git clone https://github.com/whole-tale/girder
    $ cd girder
    $ rm -rf plugins/wholetale
    $ cp -r {path_to_your_version_of_this_repo}/ plugins/wholetale
    $ # Install dependencies
    $ pip install -r requirements-dev.txt
    $ pip install -r plugins/wholetale/requirements.txt
    $ cd tests
    $ # Set up environment variables for CMake
    $ export PYTHON="{YOUR_PYTHON_3_BIN_PATH}"
    $ export COVERAGE="{YOUR_COVERAGE_BIN_PATH}"
    $ export FLAKE8="{YOUR_FLAKE8_BIN_PATH}"
    $ cmake \
        -DRUN_CORE_TESTS:BOOL=OFF \
        -DBUILD_JAVASCRIPT_TESTS:BOOL=OFF \
        -DJAVASCRIPT_STYLE_TESTS:BOOL=OFF \
        -DTEST_PLUGINS:STRING=wholetale \
        -DCOVERAGE_MINIMUM_PASS:STRING=4 \
        -DPYTHON_COVERAGE=ON \
        -DPYTHON_STATIC_ANALYSIS=ON \
        -DPYTHON_VERSION="3.6" \
        -DPYTHON_COVERAGE_EXECUTABLE="$COVERAGE" \
        -DFLAKE8_EXECUTABLE="$FLAKE8" \
        -DPYTHON_EXECUTABLE="$PYTHON" \
        ..
    $ ctest -VV
..

.. _`WholeTale Fork of Girder`: https://github.com/whole-tale/girder
