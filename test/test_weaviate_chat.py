import sys
import os

# getting the name of the directory
# where the this file is present.
current = os.path.dirname(os.path.realpath(__file__))

# Getting the parent directory name
# where the current directory is present.
parent = os.path.dirname(current)
casinoPath = parent+"/casinoai"

#print(f"Current Path: {current}")
#print(f"Parent Path: {parent}")
#print(f"Casino Path: {casinoPath}")

# adding the parent directory to
# the sys.path.
sys.path.append(casinoPath)



from langchain.vectorstores.weaviate import Weaviate
from langchain.llms import OpenAI
#from langchain.chains import ChatVectorDBChain
from langchain.chains import ConversationalRetrievalChain
from langchain.memory import ConversationBufferMemory
from langchain.chat_models import ChatOpenAI
from langchain.agents import load_tools, initialize_agent
from langchain.agents import AgentType
import weaviate
import os
from knowledgebase import *
from pathlib import Path

#import ingest

#weaviate_url = "http://"+os.environ.get("WEAVIATE_URL", "localhost:8080")
openai_api_key = os.environ.get("OPENAI_API_KEY")
gpt_model = os.environ.get("GPT_MODEL")

#client = weaviate.Client(weaviate_url)

#vectorstore = Weaviate(client, "UnstructuredDocument", "text")

#MyOpenAI = OpenAI(temperature=0.2,
#    openai_api_key=openai_api_key)

memory = ConversationBufferMemory(memory_key="chat_history", return_messages=True)
#retriever = vectorstore.as_retriever(
#search_type="mmr"
#)
#chat = ConversationalRetrievalChain.from_llm(MyOpenAI, retriever=retriever, memory=memory)




llm = ChatOpenAI(
    temperature=0.0,
    model_name=gpt_model,
    openai_api_key=openai_api_key,
)
#tools = load_tools(
#    ["human"]

#)
tools = []

# Get List of all directories from given path recursively.
def fast_scandir(dirname):
    subfolders= [f.path for f in os.scandir(dirname) if f.is_dir()]
    for dirname in list(subfolders):
        subfolders.extend(fast_scandir(dirname))
    return subfolders

dirs = fast_scandir(os.environ.get("PDF_STRUCTURED_LOCATION"))

for dir in dirs:
    vectorClass = Path(dir).name.title().replace(" ", "_")
    kb = getKnowledgeBaseTool(vectorClass)
    tools.append(kb)
    print(f"Adding Knowledge Base Tool: {kb.name} | {kb.description}")

#tools.append(getKnowledgeBaseTool("Alpha_Male"))

#print(f"Tools: {tools}")



agent_chain = initialize_agent(
    tools,
    llm,
    agent=AgentType.CHAT_CONVERSATIONAL_REACT_DESCRIPTION,
    memory=memory,
    verbose=True,
)

print(f"I'm ready. Ask me anything:")

while True:
    query = input("")
    result = agent_chain.run(query)
    print(result)

