import os

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

load_dotenv()

persist_directory = (
    os.environ.get("VECTOR_STORE_CHROMA_PERSISTANCE_DIRECTORY") or "data/chroma-db"
)
collection_name = os.environ.get("CHROMA_COLLECTION_NAME") or "example_collection"

os.makedirs(persist_directory, exist_ok=True)


llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0.1)


embed_model = OpenAIEmbeddings(model="text-embedding-ada-002")


vector_store = Chroma(
    collection_name=collection_name,
    embedding_function=embed_model,
    persist_directory=persist_directory,
)

if __name__ == "__main__":
    # response = llm.invoke("hi")

    # print(response.content)

    print(len(embed_model.embed_query("What is the capital of India?")))

    # all_ids = vector_store.get()["ids"]

    # print(f"Total number of points in the vectorstore: {len(all_ids)}")

    pass
