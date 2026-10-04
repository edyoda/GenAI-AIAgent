

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# load_dotenv(dotenv_path="src/mcp_codebase/.env")
load_dotenv()



# already set `OPENAI_API_KEY`` environment variable

llm = ChatOpenAI(model="gpt-4.1-mini")

# print(llm.invoke("hi").content)