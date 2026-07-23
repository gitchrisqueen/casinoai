from langchain.vectorstores.weaviate import Weaviate
from langchain.llms import OpenAI
#from langchain.chains import ChatVectorDBChain
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
import weaviate
import os
#import ingest

weaviate_url = "http://"+os.environ.get("WEAVIATE_URL", "localhost:8080")
openai_api_key = os.environ.get("OPENAI_API_KEY")

client = weaviate.Client(weaviate_url)

vectorstore = Weaviate(client, "UnstructuredDocument", "text")

MyOpenAI = OpenAI(temperature=0.2,
    openai_api_key=openai_api_key)

#qa = ChatVectorDBChain.from_llm(MyOpenAI, vectorstore)
'''
chat_history = []

while True:
    query = input("")
    result = qa({"question": query, "chat_history": chat_history})
    print(result["answer"])
    chat_history = [(query, result["answer"])]
'''

memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
retriever = vectorstore.as_retriever(
#search_type="mmr"
)
chat = ConversationalRetrievalChain.from_llm(MyOpenAI, retriever=retriever, memory=memory)

while True:
    query = input("")
    result = chat({"question": query})
    print(result["answer"])



def load_knowledge_base_into_weaviate(directory_path):
    #TODO: Check if data is already ingested then continue
    print("Knowledge Base loaded into Weaviate successfully!")


#1. Ingest Data into Knowledgebase
load_knowledge_base_into_weaviate("/path/to/knowledge_base_directory")
