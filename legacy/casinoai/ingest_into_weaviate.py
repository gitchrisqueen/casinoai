import os


# importing
from ingest_info import *
#from casinoai.ingest_info import IngestInfo


data_folder = os.environ.get("PDF_STRUCTURED_LOCATION")
print(f"Structured Data Folder Path (orig): {data_folder}")
di = IngestInfo()
#di.delete_all() # Only do this if you want to wipe all Weaviate data
di.ingest_data(data_folder)
print(f"Ingest Into Weaviate Finished")