import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "qistwalay_data"

with (DATA_DIR / "qistwalay_products.json").open(encoding="utf-8") as f:
    products = json.load(f)
with (DATA_DIR / "qistwalay_faqs.json").open(encoding="utf-8") as f:
    faqs = json.load(f)
with (DATA_DIR / "qistwalay_policies.json").open(encoding="utf-8") as f:
    policies = json.load(f)
with (DATA_DIR / "qistwalay_requirements.json").open(encoding="utf-8") as f:
    requirements = json.load(f)

print("Loaded:", len(products), "products,", len(faqs), "faqs,", len(policies), "policies")

# --- Duplicate site-wide FAQs hatao ---
seen = set()
unique_faqs = []
for faq in faqs:
    key = faq["question"].strip().lower()
    if key not in seen:
        seen.add(key)
        unique_faqs.append(faq)

print(f"{len(faqs)} → {len(unique_faqs)} after removing duplicates")
faqs = unique_faqs


# --- Policy text clean karo ---
def clean_policy_text(text):
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    lines = [l for l in lines if l not in ("Home",)]
    deduped = []
    for l in lines:
        if not deduped or deduped[-1] != l:
            deduped.append(l)
    return "\n".join(deduped).strip()

for name in policies:
    policies[name] = clean_policy_text(policies[name])


# --- Sirf valid products rakho ---
products = [p for p in products if p.get("name") and p.get("price")]
print(f"Clean products: {len(products)}")

for p in products:
    try:
        p["price"] = int(float(p["price"]))
    except (TypeError, ValueError):
        p["price"] = None


# --- Whitespace clean karne wala helper ---
def clean_text(text):
    if not text:
        return text
    text = re.sub(r"\n{2,}", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


# --- Site-wide FAQs clean karo (BUG FIX: dono lines loop ke ANDAR) ---
for faq in faqs:
    faq["question"] = clean_text(faq["question"])
    faq["answer"] = clean_text(faq["answer"])

# --- Product descriptions clean karo ---
for p in products:
    if p.get("description"):
        p["description"] = clean_text(p["description"])

# --- Requirements clean karo (ek dafa, sab products ke liye same) ---
requirements_text = clean_text(requirements.get("requirements"))

print("Whitespace cleaned")


# --- Har product ka specifications + apne FAQs + sab kuch ek combined description mein daalo ---
def build_combined_description(p):
    specs = p.get("specifications", {}) or {}
    specs_text = " ".join(f"{k}: {v}." for k, v in specs.items())

    product_faqs = p.get("faqs", []) or []
    faqs_text = " ".join(f"Q: {f.get('question','')} A: {f.get('answer','')}" for f in product_faqs)

    combined = (
        f"Product Name: {p.get('name', '')}. "
        f"Brand: {p.get('brand', '')}. "
        f"Category: {p.get('category', '')}. "
        f"SKU: {p.get('sku', '')}. "
        f"Price: {p.get('price', '')} {p.get('currency', '')}. "
        f"Availability: {p.get('availability', '')}. "
        f"Description: {p.get('description', '')} "
        f"Specifications: {specs_text} "
        f"Product FAQs: {faqs_text}"
    )
    return clean_text(combined)


new_products = []
for p in products:
    new_products.append({
        "url": p.get("url"),
        "description": build_combined_description(p),
        "specifications": p.get("specifications", {}),  # metadata ke liye alag se bhi rakho
    })

products = new_products


# --- Final save ---
clean_dataset = {
    "products": products,
    "faqs": faqs,                      # site-wide general FAQs
    "policies": policies,
    "requirements": requirements_text,  # sirf ek dafa, sab products ke liye common
}

with (DATA_DIR / "qistwalay_clean_dataset.json").open("w", encoding="utf-8") as f:
    json.dump(clean_dataset, f, indent=2, ensure_ascii=False)

print(f"\nFinal: {len(products)} products, {len(faqs)} faqs, {len(policies)} policies saved")
print(products[0])