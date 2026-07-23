import sys
import os

# getting the name of the directory
# where the this file is present.
current = os.path.dirname(os.path.realpath(__file__))

# Getting the parent directory name
# where the current directory is present.
parent = os.path.dirname(current)
casinoPath = parent+"/casinoai"

print(f"Current Path: {current}")
print(f"Parent Path: {parent}")
print(f"Casino Path: {casinoPath}")

# adding the parent directory to
# the sys.path.
sys.path.append(casinoPath)


# importing
from ingest_info import *
#from casinoai.ingest_info import IngestInfo


data_folder = os.environ.get("PDF_STRUCTURED_LOCATION")
print(f"Structured Data Folder Path (orig): {data_folder}")
di = IngestInfo()
di.delete_all() # Only do this if you want to wipe all Weaviate data
di.ingest_data(data_folder)
print(f"Ingest.py Finished")