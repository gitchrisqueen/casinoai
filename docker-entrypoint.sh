#!/bin/bash -e

#
# Copyright (c) 2023. Christopher Queen Consulting LLC (http://www.ChristopherQueenConsulting.com/)
#

#############################################

# Confirm env variables
echo -e "OPENAI_API_KEY: $OPENAI_API_KEY \nGOOGLE_API_KEY: $GOOGLE_API_KEY \nGOOGLE_CSE_ID: $GOOGLE_CSE_ID \nWEAVIATE_URL: $WEAVIATE_UR\nPDF_LOCATION: $PDF_LOCATION"

# Run core code here
python3 casinoai/ingest.py
#python3 casinoai/core.py

# Sleep to keep container running
sleep infinity