from pathlib import Path
import weaviate
from weaviate.embedded import EmbeddedOptions
from weaviate.util import generate_uuid5
import os
import tqdm
import gc
from unstructured.partition.pdf import partition_pdf
from unstructured.partition.auto import partition
from unstructured.staging.base import elements_from_json
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

class IngestInfo():

    # Remove the entire schema from the Weaviate instance and all data associated with it.
    def delete_all(self):
        print(f"Deleting All Weaviate Schemas and Data.")
        client.schema.delete_all()

    def createSchemaClass(self,class_name,createIfExists=False):
        # Sanitize the class_name
        class_name = class_name.title().replace(" ", "_")
        # Create a new Weaviate Class if it does not exist
        if client.schema.exists(class_name=class_name) == True:
            if createIfExists==True:
                client.schema.delete_class(class_name)
        else:
            print(f"Creating Weaviate Class: {class_name}")
            unstructured_class = create_unstructured_weaviate_class(class_name=class_name)
            client.schema.create_class(unstructured_class)

        return class_name

    # Using the pathlib library Look for the given directory(data_folder) and traverse up directory tree till you
    # find the folder that exists
    # with the given filename.
    def find_folder(self, data_folder, depth=0, parent='..'):
        if parent=='..':
            parent = Path(__file__).parent
        path = Path(data_folder)

        isExist = os.path.exists(path)
        if isExist==False and depth<3:
            data_folder = self.find_folder(parent / data_folder ,depth+1, parent.parent)
        # else if the directory exists then print the path
        elif isExist==True:
            print(f"Data Folder Path (orig): {Path(data_folder).absolute()}")

        return Path(data_folder).absolute()

    # fileTypes='*.pdf' for pdf unpartitioned files
    def ingest_data(self, data_folder, fileTypes='*.json'):

        directory = self.find_folder(data_folder)

        print(f"Ingesting ({fileTypes}) files from path: {directory} ...")

        #TODO: Check path to see if it exist locally or if it comes from google drive and load via Google APIs

        # Create a list of data objects to be added to the client batch using mapped indices
        data_objects = {}

        weaviateErrorRetryConf = weaviate.WeaviateErrorRetryConf(number_retries = 3, errors_to_include = ['UnexpectedStatusCodeException'])
        with client.batch(batch_size=5, dynamic=True, num_workers=1, weaviate_error_retries=weaviateErrorRetryConf ) as batch:

            #for path in Path(data_folder).rglob(fileTypes):
            for path in tqdm.tqdm(sorted(directory.rglob(fileTypes))):
                #print(f"Processing {path.relative_to(data_folder)} ...")
                depth = len(path.relative_to(directory).parts)
                spacer = "    " * depth
                print(f"{spacer}+ {path.relative_to(directory)} | [Processing]")

                #pathParentFolderName = the folder name of the directory containing the file in path
                pathParentFolderName = path.parent.name
                unstructured_class_name = self.createSchemaClass(pathParentFolderName)


                ''' For Unstructured files that have already been partitioned yet '''
                elements = elements_from_json(filename=path)

                ''' #For Unstructured files that havent been partitioned yet
                if path.suffix == '.pdf':
                    #elements = partition_pdf(filename=path, strategy="hi_res", infer_table_structure=True)
                    elements = partition_pdf(filename=path, strategy="auto", infer_table_structure=True)
                    #elements = partition_pdf(filename=path, strategy="fast")
                else:
                    elements = partition(filename=path)

                '''

                #abstract_extractor = AbstractExtractor()
                #abstract_extractor.consume_elements(elements)
                #data_object = {"source": path.relative_to(data_folder), "abstract": abstract_extractor.abstract()}
                weaviate_data_object = stage_for_weaviate(elements)

                for data_object in weaviate_data_object:
                    batch.add_data_object(
                        data_object,
                        unstructured_class_name,
                        #uuid=generate_uuid5(data_object),
                    )
                # Clean up memory
                del(weaviate_data_object)
                gc.collect()

        """
                # Add the data object to the list for use in batch
                if unstructured_class_name not in data_objects:
                    data_objects[unstructured_class_name] = []
                data_objects[unstructured_class_name].append(weaviate_data_object)



        with client.batch(batch_size=10) as batch:
            # print dictionary
            #print(f"Data Objects:")
            #print(data_objects)
            for unstructured_class_name, weaviate_data_objects in tqdm.tqdm(data_objects.items()):
                #weaviate_data_object=weaviate_data_objects[unstructured_class_name]
                print(f"Weaviate Object [{unstructured_class_name}]:")
                #print(weaviate_data_objects)
                for data_object in weaviate_data_object:
                    #print(f"Data Object:")
                    #print(data_objects)
                    batch.add_data_object(
                        data_object,
                        unstructured_class_name,
                        uuid=generate_uuid5(data_object),
                    )

        """

        print(f"ingest_data function Finished")








#Test the Ingesting
#refresh_schema()
#data_folder = os.environ["PDF_LOCATION"]
#data_folder = os.environ["PDF_LOCATION_LOCAL"]
#ingest_data(data_folder)
#print(f"Ingest.py Finished")