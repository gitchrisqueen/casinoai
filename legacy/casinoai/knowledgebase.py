from langchain.vectorstores.weaviate import Weaviate
from langchain.llms import OpenAI
from langchain.chat_models import ChatOpenAI
from langchain.chains.llm import LLMChain
from langchain.chains.combine_documents.stuff import StuffDocumentsChain
from langchain.chains import RetrievalQA
from langchain.chains.mapreduce import MapReduceChain
from langchain.chains import ReduceDocumentsChain, MapReduceDocumentsChain
from langchain.chains import create_qa_with_sources_chain
from langchain.chains.summarize import load_summarize_chain
from langchain.prompts import PromptTemplate
from langchain.text_splitter import CharacterTextSplitter
from langchain.tools import Tool
from langchain.agents import initialize_agent
from langchain.retrievers.self_query.base import SelfQueryRetriever
from langchain.chains.query_constructor.base import AttributeInfo
import json
import warnings
import weaviate
import os

with warnings.catch_warnings():
    warnings.simplefilter("ignore")

weaviate_url = "http://"+os.environ.get("WEAVIATE_URL", "localhost:8080")
openai_api_key = os.environ.get("OPENAI_API_KEY")
gpt_model = os.environ.get("GPT_MODEL")
client = weaviate.Client(weaviate_url)

llm = OpenAI(
    temperature=0,
    openai_api_key=openai_api_key,
    model_name=gpt_model,
)
llmc = ChatOpenAI(
    temperature=0,
    openai_api_key=openai_api_key,
    model_name=gpt_model

)
#qa_chain = create_qa_with_sources_chain(llmc)
qa_chain = create_qa_with_sources_chain(llm)

doc_prompt = PromptTemplate(
    template="Content: {page_content}\nSource: {filename}-pg_{page_number}",
    input_variables=["page_content", "filename", "page_number" ],
)

final_qa_chain = StuffDocumentsChain(
    llm_chain=qa_chain,
    document_variable_name="context",
    document_prompt=doc_prompt,
)


#knowledgebase_subject = "casino games and strategies"

verbose = True


def getDistinctFileNames(vectorClass):
    response = (
        client.query
        .aggregate(vectorClass)
        .with_group_by_filter(["filename"])
        .with_fields("groupedBy { value }")
        .do()
    )
    #print(response)
    #print(json.dumps(response, indent=2))
    data = response['data']['Aggregate'][vectorClass]
    #print(data)
    filenames = [groupedBy['groupedBy']['value'] for groupedBy in data]
    #print(filenames)
    return filenames

def getTotalTextEntries(vectorClass, fileName):
    where_filter = {
        "path": ["filename"],
        "operator": "Equal",
        "valueText": fileName,
    }

    response = (
        client.query
        .aggregate(vectorClass)
        #.with_limit(2) # Take this out
        .with_where(where_filter)
        .with_fields("text { count }")
        .do()
    )
    count = response['data']['Aggregate'][vectorClass][0]['text']['count']
    return count

def getAllTextByFileName(vectorClass, fileName):
    where_filter = {
        "path": ["filename"],
        "operator": "Equal",
        "valueText": fileName,
    }

    batch_size = getTotalTextEntries(vectorClass, fileName)
    print(f"Batch size: {batch_size}")

    response = (
        client.query
        .get(vectorClass, ['text'])
        #.with_limit(2) # Take this out
        .with_where(where_filter)
        .with_sort({
            'path': ['page_number'],
            'order': 'asc',
        })
        #.with_additional(["id"])
        .with_limit(batch_size)
        .do()
    )

    data = response['data']['Get'][vectorClass]
    text = [result['text'] for result in data]
    text = ' '.join(text)
    return text

def getSummaryByFileName(vectorClass, fileName):
    where_filter_simple = {
        "path": ["filename"],
        "operator": "Equal",
        "valueText": fileName,
    }
    where_filter_complex = {
        "operator": "And",
        "operands": [
            {
                "path": ["filename"],
                "operator": "Equal",
                "valueText": fileName,
            },
            {
                "path": ["category"],
                "operator": "Equal",
                #"valueText": "NarrativeText",
                "valueText": "Title",
            },
        ]
    }

    batch_size = getTotalTextEntries(vectorClass, fileName)
    print(f"Batch size: {batch_size}")
    batch_size = 10 # TODO: Remove this and uncomment above
    print(f"Reduced Batch size: {batch_size}")

    generate_prompt = "Please give a consolidated summary of the topics covered in less than 300 words."

    response = (
        client.query
        .get(vectorClass, ['text'])
        #.with_limit(2) # Take this out
        .with_where(where_filter_simple)
        .with_generate(grouped_task=generate_prompt)
        #.with_additional(["id"])
        .with_limit(batch_size)
        .do()
    )

    result = response['data']['Get'][vectorClass][0]['_additional']["generate"]['groupedResult']
    return result

# Set up a knowledge base
def setup_knowledge_base(vectorClass):

    vectorstore = Weaviate(client, vectorClass, "text", attributes=["filename","page_number"])

    #1. Get all the distinct filenames
    filenames = getDistinctFileNames(vectorClass)

    #2. Get all text per file name and summarize by file
    text_splitter = CharacterTextSplitter.from_tiktoken_encoder(
            chunk_size=1000, chunk_overlap=0
        )

    summaries = []

    for filename in filenames:
        print(f"Getting text for: {filename}")

        #summary = getSummaryByFileName(vectorClass, filename)
        #print(f"Summary: {summary}")


        #text = getAllTextByFileName(vectorClass, filename)
        #print(f"Text: {text}")
        #docs = text_splitter.create_documents([text])

        batch_size = getTotalTextEntries(vectorClass, filename)
        retriever = vectorstore.as_retriever(
                #search_type="mmr"
                search_kwargs={
                    #"score_threshold": .5,
                    "k": batch_size,
                    'filter': {'filename':filename}
                }
            )
        docsQuestion = " "
        docs = retriever.get_relevant_documents(docsQuestion)
        #print(f"Relevant Docs (About {docsQuestion}): {docs}")

        output_summary = getSummaryFromDocs(docs)
        print(output_summary)
        summaries.append(output_summary)


    #3. Summarize by all summaries for final descriptions
    #print(f"Summaries: {summaries}")
    docs = text_splitter.create_documents(summaries)
    final_summary = getSummaryFromDocs(docs)
    print(f"Final Summary: {final_summary}")

    document_content_description = final_summary

    metadata_field_info = [
        AttributeInfo(
            name="filename",
            description="The file name containing the content",
            type="string",
        ),
        AttributeInfo(
            name="filetype",
            description="The file type of the content",
            type="integer",
        ),
        AttributeInfo(
            name="page_number",
            description="The page number where the content is located in the file",
            type="string",
        ),

    ]
    #document_content_description = ' '
    #vectorClass.replace("_", " ")
    retriever = SelfQueryRetriever.from_llm(
        llm, vectorstore, document_content_description, metadata_field_info, verbose=True, enable_limit=False
    )


    #results = final_qa_chain.run(question="What is the Alpha Male 2.0",input_documents = docs)
    #print(f"From final_qa_chain: {results}")


    #TODO: Get the right chain_type or pull from something else instead of from_chain_type
    knowledge_base = RetrievalQA(
        #llm=llmc,
        retriever=retriever,
        combine_documents_chain=final_qa_chain,
        verbose=verbose
    )

    return {"knowledge_base":knowledge_base, "description":document_content_description}

def getKnowledgebaseTitleFromDescriptions(knowledge_base_description):
    map_template = """The following is a description
    {description}
    Based on the description, please give me a short but concise title that would represent the subject of the description. Make sure it uses proper case and remove commas and punctuations. Example Title: TheArtOfWar
    Title:"""
    map_prompt = PromptTemplate.from_template(map_template)
    map_chain = LLMChain(llm=llm, prompt=map_prompt)
    knowledge_base_title = map_chain.run(knowledge_base_description)
    title = knowledge_base_subject.strip().replace(" ", "")
    #print(f"Knowledge Base Title: {title}")
    return title

def getSummaryFromDocs(docs):
# Map
    map_template = """The following is a set of documents
    {docs}
    Based on this list of docs, please identify the main topics
    Helpful Answer:"""
    map_prompt = PromptTemplate.from_template(map_template)
    map_chain = LLMChain(llm=llm, prompt=map_prompt)

    # Reduce
    reduce_template = """The following is set of summaries:
    {doc_summaries}
    Take these and distill it into a final, consolidated summary of high level topics.
    Helpful Answer:"""
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
        token_max=3500, # Allow tokens for the completion
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

    split_docs = text_splitter.split_documents(docs)
    summary = map_reduce_chain.run(split_docs)
    return summary.strip()


def getKnowledgebaseDescriptionByClass(vectorClass):
    vectorstore = Weaviate(client, vectorClass, "text")
    retriever = vectorstore.as_retriever(
        #search_type="mmr"
        search_kwargs={
            #"score_threshold": .5,
            "k": 10
        }
    )


    #docsQuestion = vectorClass.replace("_", " ")
    #docs = retriever.get_relevant_documents(docsQuestion)

    docsQuestion = " "
    docs = retriever.get_relevant_documents(docsQuestion)
    #print(f"Relevant Docs (About {docsQuestion}): {docs}")

    knowledge_base_description = getSummaryFromDocs(docs)

    print(f"Knowledge Base Description: {knowledge_base_description}")


    chain = load_summarize_chain(llm, chain_type="stuff")
    summary = chain.run(input_documents=docs, question="Write a summary within 300 words.")
    print(f"Knowledge Base Summary: {summary}")

    return knowledge_base_description.strip()


def getKnowledgeBaseTool(vectorClass):
    # query to get_tools can be used to be embedded and relevant tools found
    # see here: https://langchain-langchain.vercel.app/docs/use_cases/agents/custom_agent_with_plugin_retrieval#tool-retriever

    # we only use one tool for now, but this is highly extensible!
    kb = setup_knowledge_base(vectorClass)
    knowledge_base = kb['knowledge_base']
    knowledge_base_description = kb['description']
    title = getKnowledgebaseTitleFromDescriptions(knowledge_base_description)
    tool = Tool(
        name=title,
        func=knowledge_base.run,
        description=""+knowledge_base_description,
    )

    return tool

#vectorClass = "Alpha_Male"
#vectorClass = "Casino_Guides"
#vectorClass = "Embodiment_Celestrial"
#vectorClass = "Hermeticism"
#vectorClass = "Official"
#knowledge_base = setup_knowledge_base(vectorClass)
#getKnowledgebaseDescriptionByClass(vectorClass)
#getKnowledgebaseSubjectByClass(vectorClass)
#result = knowledge_base.run("Give me a summary of dating and steps from start to finish.")
#print(result)


