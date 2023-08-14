#!/bin/bash -e

#
# Copyright (c) 2023. Christopher Queen Consulting LLC (http://www.ChristopherQueenConsulting.com/)
#

#############################################

# Set Environment Variables
set -o allexport
source .env
set +o allexport

/bin/bash docker-entrypoint.sh
