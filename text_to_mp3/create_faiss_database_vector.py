import openai
import time
import re
import os
import json
import torch

from collections import OrderedDict
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document

DB_FILE_PATH = "/home/igraperobot3/Model/BAAI/museum.txt"
VECTOR_DB_PATH = "/home/igraperobot3/Model/vector_database_faiss/"


model_name = "/home/igraperobot3/Model/BAAI/bge-large-zh-v1.5"
print(f"Initializing embedding model from local path: {model_name}...")

if not os.path.isdir(model_name):
    raise FileNotFoundError(
        f"Local model directory not found at '{model_name}'. "
        f"Please ensure the 'BAAI/bge-large-zh-v1.5' folder is in the project root."
    )

embedding_model = HuggingFaceEmbeddings(
    model_name=model_name,
    model_kwargs={"device": "cuda", "local_files_only": True},
    encode_kwargs={"normalize_embeddings": True},
)
print("Embedding model loaded successfully.")


print(f"\nBuilding new vector database from source: {DB_FILE_PATH}...")
try:
    with open(DB_FILE_PATH, "r", encoding="utf-8") as f:
        text_content = f.read()
except FileNotFoundError:
    print(f"Error: Source file '{DB_FILE_PATH}' not found.")

final_splits = []
exhibit_blocks = text_content.split("\n\n")
for block in exhibit_blocks:
    block = block.strip()
    if not block:
        continue
    parent_paragraph = block
    parts = block.split("\n", 1)
    body = parts[1] if len(parts) == 2 else parts[0]
    sentences = [s.strip() for s in re.split(r"(。)", body) if s.strip()]
    combined_sentences = []
    for i in range(0, len(sentences), 2):
        sentence = sentences[i]
        if i + 1 < len(sentences):
            sentence += sentences[i + 1]
        if sentence:
            combined_sentences.append(sentence)
    for sentence in combined_sentences:
        new_doc = Document(page_content=sentence, metadata={"parent_paragraph": parent_paragraph})
        final_splits.append(new_doc)

if not final_splits:
    print("Error: No text chunks were generated. Please check the source file format.")


print(f"Created {len(final_splits)} sentence chunks. Building FAISS index...")
start_time = time.time()
vector_db = FAISS.from_documents(final_splits, embedding_model)
end_time = time.time()
print(f"Vector database construction completed in {end_time - start_time:.2f} seconds.")

if vector_db:
    print(f"Saving new vector database to '{VECTOR_DB_PATH}'...")
    vector_db.save_local(VECTOR_DB_PATH)
    print("Database saved successfully.")
else:
    print("Database create fail.")





    