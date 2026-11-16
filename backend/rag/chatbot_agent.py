import json
import re
import numpy as np
import faiss
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

index = faiss.read_index("qistwalay_faiss.index")

with open("qistwalay_chunk_lookup.json", encoding="utf-8") as f:
    chunks = json.load(f)


def _count_catalog_products(loaded_chunks):
    product_ids = set()
    for chunk in loaded_chunks:
        if chunk.get("type") != "product_overview":
            continue
        metadata = chunk.get("metadata") or {}
        product_id = metadata.get("url") or metadata.get("product_id")
        if product_id:
            product_ids.add(product_id)
    return len(product_ids)


PRODUCT_CATALOG_COUNT = _count_catalog_products(chunks)
if not PRODUCT_CATALOG_COUNT:
    raise ValueError("The loaded RAG index contains no product catalog entries.")

# aam lafz jo chunk dhoondne mein madad nahi karte
STOPWORDS = {
    "what", "whats", "is", "the", "of", "in", "a", "an", "for", "to", "and", "or",
    "are", "do", "does", "how", "much", "cost", "price", "tell", "me", "about",
    "can", "i", "you", "please", "show", "qistwalay", "lahore",
    "ki", "ka", "ke", "kya", "hai", "hain", "kitni", "kitna", "kitne", "mein", "me",
    "batao", "bataiye", "there", "any", "some", "has", "have", "with", "give", "get",
    "if", "person", "people", "he", "she", "they", "his", "her", "their", "take",
    "installment", "installments", "instalment", "instalments", "plan", "plans",
    "eligible", "eligibility", "qualify", "qualifies", "qualifying", "may", "would",
}
_ABOUT_QISTWALAY = re.compile(
    r"\b(?:tell\s+me\s+about|what\s+(?:is|does)|who\s+is|describe)\s+qistwalay\b"
    r"|\bqistwalay\b.{0,80}\b(?:about|bare|bary|baray|baare|kya|kia|jant\w*|"
    r"business|company|shop|store)\b",
    re.IGNORECASE,
)
_OVERVIEW_SECTIONS = {
    "about_blurb",
    "benefits",
    "brands",
    "deal_packs",
    "serviced_by",
    "stats",
}


def _words(text):
    return re.findall(r"[a-z0-9]+", text.lower())


def _stem(w):
    """Singular aur Plural ko aapas mein match karne ke liye (maslan customer aur customers)"""
    return w.rstrip("s") if len(w) > 3 else w


def get_query_embedding(query):
    response = client.embeddings.create(
        model="text-embedding-3-small",
        input=[query]
    )
    return np.array([response.data[0].embedding], dtype="float32")


def retrieve_context(query, k=5, candidates=30):
    """FAISS se `candidates` chunks lo, phir jin mein sawal ke asli lafz
    (model, size, brand) zyada hon unhe upar rakho, aur top `k` wapas do.
    No lexical match means there is no verified context to answer from."""
    if _ABOUT_QISTWALAY.search(query):
        overview = [
            chunk["text"]
            for chunk in chunks
            if chunk.get("type") == "homepage_info"
            and (chunk.get("metadata") or {}).get("section") in _OVERVIEW_SECTIONS
        ]
        if overview:
            return "\n\n".join(overview)

    query_words = {_stem(w) for w in _words(query) if w not in STOPWORDS}
    if not query_words:
        return ""

    query_vec = get_query_embedding(query)
    _, indices = index.search(query_vec, candidates)

    scored = []
    for rank, idx in enumerate(indices[0]):
        if idx < 0:
            continue
        text = chunks[idx]["text"]
        text_words = {_stem(w) for w in _words(text)}
        overlap = len(query_words & text_words)
        if not overlap:
            continue
        score = overlap - 0.05 * rank   # lafz ka milna zyada ahem, FAISS ki tarteeb bhi thodi ahem
        scored.append((score, text))

    if not scored:
        return ""

    scored.sort(key=lambda x: x[0], reverse=True)
    return "\n\n".join(text for _, text in scored[:k])


def answer_question(query):
    context = retrieve_context(query)

    prompt = f"""You are a helpful customer support assistant for Qistwalay, an installment-based electronics store in Lahore.
Answer the customer's question using ONLY the information in the context below.
If the answer isn't in the context, say you don't have that information.

Context:
{context}

Customer question: {query}

Answer:"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


if __name__ == "__main__":
    query = "What is the installment plan for air fryer?"
    answer = answer_question(query)
    print("Customer asked:", query)
    print("\nChatbot answer:\n", answer)