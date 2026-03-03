#!/bin/bash
set -e

read -r -d '' -n 1

WORKDIR=$1

SCRIPT_NAME=$2

cd $WORKDIR
if [ -f "requirements.txt" ]; then
    pipoutput=$(pip install --no-cache-dir --user -r requirements.txt)
    retval=$?
    if [ $retval -ne 0 ]; then
        echo -n $pipoutput
        exit $retval
    fi
fi

if [ "$LAGER_STDOUT_IS_STDERR" = "True" ]; then
	exec python $SCRIPT_NAME "${@:3}" 2>&1
else
	exec python $SCRIPT_NAME "${@:3}"
fi
