#!/bin/bash -e

#
# Copyright (c) 2023. Christopher Queen Consulting LLC (http://www.ChristopherQueenConsulting.com/)
#

#############################################

# Set Environment Variables
set -o allexport
source .env
set +o allexport

# Prune Docker for dangling images
# docker system prune -f

#casinoai/utils/ingest.sh


python3 casinoai/knowledgebase.py
