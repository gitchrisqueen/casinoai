#!/usr/bin/env bash

# Processes files in $PDF_LOCATION directory recursively
# through Unstructured's library in 2 processes.

# Structured outputs are stored in $PDF_STRUCTURED_LOCATION/

PYTHONPATH=. unstructured-ingest local \
    --input-path "$PDF_LOCATION" \
    --structured-output-dir "$PDF_STRUCTURED_LOCATION" \
    --num-processes 10 \
    --recursive \
    --partition-by-api \
    --partition-endpoint "http://unstructured:${UNSTRUCTURED_CONTAINER_PORT}/general/v0/general" \
    --partition-strategy "hi_res" \
    --partition-pdf-infer-table-structure 1 \
    --file-glob '*.pdf' \
    --verbose
    #--reprocess \
    #--partition-strategy auto \
    #--partition-strategy hi_res \
    # Take this ^ out if you dont want to reprocess processed files
    #--api-key "$UNSTRUCTURED_API_KEY" \

