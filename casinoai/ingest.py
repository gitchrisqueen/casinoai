from pathlib import Path
import weaviate
from weaviate.embedded import EmbeddedOptions
from weaviate.util import generate_uuid5
import os
import tqdm
#from unstructured.partition.pdf import partition_pdf
from unstructured.partition.auto import partition
from unstructured.staging.weaviate import stage_for_weaviate
from unstructured.staging.weaviate import create_unstructured_weaviate_class


from utils.abstractextractor import AbstractExtractor

weaviate_url = "http://"+os.environ.get("WEAVIATE_URL", "localhost:8080")
client = weaviate.Client(
    url=weaviate_url, # URL of your Weaviate instance
    #auth_client_secret=auth_config,  # (Optional) If the Weaviate instance requires authentication
    #timeout_config=(5, 15),  # (Optional) Set connection timeout & read timeout time in seconds
    #additional_headers={  # (Optional) Any additional headers; e.g. keys for API inference services
        #"X-Cohere-Api-Key": "YOUR-COHERE-API-KEY",            # Replace with your Cohere key
        #"X-HuggingFace-Api-Key": "YOUR-HUGGINGFACE-API-KEY",  # Replace with your Hugging Face key
        #"X-OpenAI-Api-Key": os.environ.get("OPENAI_API_KEY")            # Replace with your OpenAI key
   #}
)

unstructured_class_name="UnstructuredDocument"
unstructured_class = create_unstructured_weaviate_class(class_name=unstructured_class_name)
schema = {"classes": [unstructured_class]}

'''
schema = {
    "class": "Document",
    "vectorizer": "text2vec-openai",
    "properties": [
        {
            "name": "source",
            "dataType": ["text"],
        },
        {
            "name": "abstract",
            "dataType": ["text"],
            "moduleConfig": {
                "text2vec-openai": {"skip": False, "vectorizePropertyName": False}
            },
        },
    ],
    "moduleConfig": {
        "generative-openai": {},
        "text2vec-openai": {"model": "ada", "modelVersion": "002", "type": "text"},
    },
}
'''

def refresh_schema():
    #TODO: Determine if and when this needs to happen
    print(f"Refreshing Weaviate Schema.")
    client.schema.delete_all()
    #client.schema.create_class(schema)
    client.schema.create(schema)
    print(f"Weaviate Schema Refreshed.")

# Look for the given data_folder and traverse up till you find it
def find_folder(data_folder, depth=0, parent='..'):
    if parent=='..':
        parent = Path(__file__).parent
    path = Path(data_folder)

    isExist = os.path.exists(path)
    if isExist==False and depth<3:
        data_folder = find_folder(parent / data_folder ,depth+1, parent.parent)
    return Path(data_folder)



def ingest_data(data_folder, fileTypes='*.pdf'):

    directory = find_folder(data_folder)

    print(f"Ingesting ({fileTypes}) files from path: {directory} ...")

    #TODO: Check path to see if it exist locally or if it comes from google drive and load via Google APIs
    data_objects = []

    #for path in Path(data_folder).rglob(fileTypes):
    for path in sorted(directory.rglob(fileTypes)):
        #print(f"Processing {path.relative_to(data_folder)} ...")
        depth = len(path.relative_to(directory).parts)
        spacer = "    " * depth
        print(f"{spacer}+ {path.relative_to(directory)} | [Processing]")

        elements = partition(filename=path)

        #abstract_extractor = AbstractExtractor()
        #abstract_extractor.consume_elements(elements)
        #data_object = {"source": path.relative_to(data_folder), "abstract": abstract_extractor.abstract()}
        weaviate_data_object = stage_for_weaviate(elements)

        data_objects.append(weaviate_data_object)

    with client.batch(batch_size=10) as batch:
        for weaviate_data_object in tqdm.tqdm(data_objects):
            for data_object in weaviate_data_object:
                batch.add_data_object(
                    data_object,
                    unstructured_class_name,
                    uuid=generate_uuid5(data_object),
                )

    print(f"ingest_data function Finished")








#Test the Ingesting
refresh_schema()
data_folder = os.environ["PDF_LOCATION"]
#data_folder = os.environ["PDF_LOCATION_LOCAL"]
ingest_data(data_folder)
print(f"Ingest.py Finished")