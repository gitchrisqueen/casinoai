from langchain.vectorstores.weaviate import Weaviate
from langchain.llms import OpenAI
from langchain.chains.llm import LLMChain
from langchain.chains.combine_documents.stuff import StuffDocumentsChain
from langchain.chains import RetrievalQA
from langchain.chains.mapreduce import MapReduceChain
from langchain.chains import ReduceDocumentsChain, MapReduceDocumentsChain
from langchain.prompts import PromptTemplate
from langchain.text_splitter import CharacterTextSplitter

import weaviate
import os
from ingest_info import *

weaviate_url = "http://"+os.environ.get("WEAVIATE_URL", "localhost:8080")
openai_api_key = os.environ.get("OPENAI_API_KEY")
client = weaviate.Client(weaviate_url)

llm = OpenAI(temperature=0,openai_api_key=openai_api_key)


#knowledgebase_subject = "casino games and strategies"

ingest_new_data = False
verbose = True
di = IngestInfo()


# Set up a knowledge base
def setup_knowledge_base(vectorClass):

    vectorstore = Weaviate(client, vectorClass, "text")
    retriever = vectorstore.as_retriever(
    #search_type="mmr"
    )



    #TODO: Get the right chain_type or pull from something else instead of from_chain_type
    knowledge_base = RetrievalQA.from_llm(
        llm=llm, retriever=retriever, verbose=verbose
    )
    return knowledge_base

def getKnowledgebaseSubjectByClass(vectorClass):
    knowledge_base_description = getKnowledgebaseDescriptionByClass(vectorClass)
    map_template = """The following is a description
    {description}
    Based on the description, please give me a short but thorough title that would represent the subject of the description.
    Title:"""
    map_prompt = PromptTemplate.from_template(map_template)
    map_chain = LLMChain(llm=llm, prompt=map_prompt)
    knowledge_base_subject = map_chain.run(knowledge_base_description)
    print(f"Knowledge Base Subject: {knowledge_base_subject}")
    return knowledge_base_subject


def getKnowledgebaseDescriptionByClass(vectorClass):
    vectorstore = Weaviate(client, vectorClass, "text")
    retriever = vectorstore.as_retriever(
        #search_type="mmr"
    )

    # Map
    map_template = """The following is a set of documents
    {docs}
    Based on this list of docs, please identify the main themes
    Helpful Answer:"""
    map_prompt = PromptTemplate.from_template(map_template)
    map_chain = LLMChain(llm=llm, prompt=map_prompt)

    # Reduce
    reduce_template = """The following is set of summaries:
    {doc_summaries}
    Take these and distill it into a final, consolidated summary of the main themes.
    Helpful Answer: Useful for when you need to answer questions about ..."""
    reduce_prompt = PromptTemplate.from_template(reduce_template)
    reduce_chain = LLMChain(llm=llm, prompt=reduce_prompt)

    # Takes a list of documents, combines them into a single string, and passes this to an LLMChain
    combine_documents_chain = StuffDocumentsChain(
        llm_chain=reduce_chain, document_variable_name="doc_summaries"
    )

    # Combines and iteratively reduces the mapped documents
    reduce_documents_chain = ReduceDocumentsChain(
        # This is final chain that is called.
        combine_documents_chain=combine_documents_chain,
        # If documents exceed context for `StuffDocumentsChain`
        collapse_documents_chain=combine_documents_chain,
        # The maximum number of tokens to group documents into.
        token_max=4000,
    )

    # Combining documents by mapping a chain over them, then combining results
    map_reduce_chain = MapReduceDocumentsChain(
        # Map chain
        llm_chain=map_chain,
        # Reduce chain
        reduce_documents_chain=reduce_documents_chain,
        # The variable name in the llm_chain to put the documents in
        document_variable_name="docs",
        # Return the results of the map steps in the output
        return_intermediate_steps=False,
    )


    text_splitter = CharacterTextSplitter.from_tiktoken_encoder(
        chunk_size=1000, chunk_overlap=0
    )

    docsQuestion = vectorClass.replace("_", " ")
    docs = retriever.get_relevant_documents(docsQuestion)
    print(f"Relevant Docs (About {docsQuestion}): {docs}")

    split_docs = text_splitter.split_documents(docs)
    knowledge_base_description = map_reduce_chain.run(split_docs)

    print(f"Knowledge Base Description: {knowledge_base_description}")
    return knowledge_base_description


def get_tools(vectorClass):
    # query to get_tools can be used to be embedded and relevant tools found
    # see here: https://langchain-langchain.vercel.app/docs/use_cases/agents/custom_agent_with_plugin_retrieval#tool-retriever

    # we only use one tool for now, but this is highly extensible!
    knowledge_base = setup_knowledge_base(vectorClass)
    knowledge_base_subject = getKnowledgebaseSubjectByClass(vectorClass)
    knowledge_base_description = getKnowledgebaseDescriptionByClass(vectorClass)
    tools = [
        Tool(
            name=knowledgebase_subject,
            func=knowledge_base.run,
            description="useful for when you need to answer questions about "+knowledge_base_description,
        )
    ]

    return tools

#vectorClass = "Alpha_Male"
#vectorClass = "Casino_Guides"
#vectorClass = "Embodiment_Celestrial"
#vectorClass = "Hermeticism"
vectorClass = "Official"
#knowledge_base = setup_knowledge_base(vectorClass)
#getKnowledgebaseDescriptionByClass(vectorClass)
getKnowledgebaseSubjectByClass(vectorClass)
#result = knowledge_base.run("Give me a summary of dating and steps from start to finish.")
#print(result)


