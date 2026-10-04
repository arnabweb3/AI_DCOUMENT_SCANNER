# vector_store.py
# This is the "R" (Retrieval) part of RAG.
# I am using ChromaDB. It makes the embeddings by itself using a small local model
# (all-MiniLM-L6-v2), so no API key is needed for embeddings.

import chromadb
from chromadb.config import Settings

from config import CHROMA_DIR

client = chromadb.PersistentClient(path=CHROMA_DIR, settings=Settings(anonymized_telemetry=False))
collection = client.get_or_create_collection(name="documents", metadata={"hnsw:space": "cosine"})


def fix_metadata(metadata):
    # chroma only allows str, int, float and bool in metadata
    new_metadata = {}
    for key in metadata:
        value = metadata[key]
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            new_metadata[key] = value
        else:
            new_metadata[key] = str(value)
    return new_metadata


def add_chunks(doc_id, chunks):
    # first remove old chunks of this document (if the same file is uploaded again)
    delete_document(doc_id)

    # add in batches of 200
    for i in range(0, len(chunks), 200):
        batch = chunks[i:i + 200]
        ids = []
        texts = []
        metadatas = []
        for j in range(len(batch)):
            ids.append(doc_id + "-" + str(i + j))
            texts.append(batch[j]["text"])
            metadata = batch[j]["metadata"]
            metadata["doc_id"] = doc_id
            metadatas.append(fix_metadata(metadata))
        collection.add(ids=ids, documents=texts, metadatas=metadatas)

    return len(chunks)


def search(query, top_k=5, doc_ids=None):
    total = collection.count()
    if total == 0:
        return []

    # filter by document if user selected some documents
    where = None
    if doc_ids:
        if len(doc_ids) == 1:
            where = {"doc_id": doc_ids[0]}
        else:
            where = {"doc_id": {"$in": doc_ids}}

    results = collection.query(query_texts=[query], n_results=min(top_k, total), where=where)

    hits = []
    for i in range(len(results["documents"][0])):
        hits.append({
            "text": results["documents"][0][i],
            "metadata": results["metadatas"][0][i],
            "score": round(1 - results["distances"][0][i], 4),  # cosine distance -> similarity
        })
    return hits


def delete_document(doc_id):
    collection.delete(where={"doc_id": doc_id})
