#!/bin/bash

export PYTHON_VERSION=3.4
export COVERAGE_EXECUTABLE=/usr/local/bin/coverage
export FLAKE8_EXECUTABLE=/usr/local/bin/flake8
export VIRTUALENV_EXECUTABLE=/usr/local/bin/virtualenv
export PYTHON_EXECUTABLE=/usr/bin/python3

case $CIRCLE_NODE_INDEX in
	0|1)
		export TEST_GROUP=python
		;;
	2)
		export TEST_GROUP=browser
		;;
	3)
		export TEST_GROUP=static
		;;
	*)
		echo "Invalid node index"
		exit 0
esac

mkdir /girder/build
touch /girder/build/test_failed
ctest -VV -S /girder/plugins/wholetale/cmake/circle_continuous.cmake
if [ -f /gitder/build/test_failed ] ; then
	exit 1
fi

mkdir -p $CIRCLE_ARTIFACTS/coverage/python $CIRCLE_ARTIFACTS/coverage/js
ls -l /girder/build/
if [ -f /girder/build/coverage.xml ] ; then
  cp /girder/build/coverage.xml $CIRCLE_ARTIFACTS/coverage/python
fi
if [ -d /girder/girder/clients/web/dev/built/py_coverage ] ; then
  cp -r /girder/girder/clients/web/dev/built/py_coverage/* $CIRCLE_ARTIFACTS/coverage/python
fi
if [ -d /girder/build/coverage ] ; then
  cp -r /girder/build/coverage/* $CIRCLE_ARTIFACTS/coverage/js
fi
