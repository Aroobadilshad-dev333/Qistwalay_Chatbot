import json
import numpy as np
import faiss
import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI

DATA_DIR = Path(__file__).resolve().parents[1] / "qistwalay_data"

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

with (DATA_DIR / "qistwalay_rag_chunks.json").open(encoding="utf-8") as f:
    chunks = json.load(f)

print(f"{len(chunks)} chunks loaded")

texts = [c["text"] for c in chunks]

# --- OpenAI batches mein embed karta hai ---
def get_embeddings_batch(texts, batch_size=100):
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=batch
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)
        print(f"Embedded {i + len(batch)}/{len(texts)} chunks")
    return np.array(all_embeddings, dtype="float32")

embeddings = get_embeddings_batch(texts)
print("Embeddings shape:", embeddings.shape)

dimension = embeddings.shape[1]
index = faiss.IndexFlatL2(dimension)
index.add(embeddings)

faiss.write_index(index, str(DATA_DIR / "qistwalay_faiss.index"))

with (DATA_DIR / "qistwalay_chunk_lookup.json").open("w", encoding="utf-8") as f:
    json.dump(chunks, f, indent=2, ensure_ascii=False)

print("Saved: qistwalay_faiss.index + qistwalay_chunk_lookup.json")