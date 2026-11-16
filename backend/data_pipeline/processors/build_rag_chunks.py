import json
import re
from pathlib import Path


DATA_DIR = Path(__file__).resolve().parents[1] / "qistwalay_data"
SOURCE = DATA_DIR / "qistwalay_clean_dataset.json"
CONTACT_SOURCE = DATA_DIR / "qistwalay_contact.json"
FAQ_SOURCE = DATA_DIR / "qistwalay_faqs.json"
OUTPUT = DATA_DIR / "qistwalay_rag_chunks.json"
PLANS_SOURCE = DATA_DIR / "qistwalay_installment_plans.json"
HOMEPAGE_SOURCE = DATA_DIR / "qistwalay_homepage.json"
DEALS_SOURCE = DATA_DIR / "qistwalay_deals.json"


def make_chunk(text, chunk_type, **metadata):
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return None
    return {
        "id": f"{chunk_type}_{len(chunks) + 1}",
        "type": chunk_type,
        "text": text,
        "metadata": metadata,
    }


def product_metadata(description, url):
    fields = {}
    for label in ("Product Name", "Brand", "Category", "SKU", "Price", "Availability"):
        match = re.search(
            rf"{re.escape(label)}:\s*(.*?)(?=\.\s+(?:Product Name|Brand|Category|SKU|Price|Availability|Description):|$)",
            description,
        )
        if match:
            fields[label.lower().replace(" ", "_")] = match.group(1).strip()
    fields["url"] = url
    return fields


def add_product_chunks(product):
    description = product.get("description", "")
    metadata = product_metadata(description, product.get("url"))
    product_id = metadata.get("sku") or metadata.get("product_name") or product.get("url")

    overview = re.split(r"\s+Specifications:", description, maxsplit=1)[0]
    overview = re.split(r"\s+Product FAQs:", overview, maxsplit=1)[0]
    chunk = make_chunk(overview, "product_overview", product_id=product_id, **metadata)
    if chunk:
        chunks.append(chunk)

    specifications = product.get("specifications") or {}
    specs_text = "; ".join(f"{key}: {value}" for key, value in specifications.items())
    chunk = make_chunk(
        f"Product: {metadata.get('product_name', '')}. Specifications: {specs_text}",
        "product_specifications",
        product_id=product_id,
        **metadata,
    )
    if chunk:
        chunks.append(chunk)

    faq_section = description.split("Product FAQs:", 1)[-1]
    faq_matches = re.findall(
        r"Q:\s*(.*?)\s+A:\s*(.*?)(?=\s+Q:|$)", faq_section
    )
    for question, answer in faq_matches:
        chunk = make_chunk(
            f"Question: {question} Answer: {answer}",
            "product_faq",
            product_id=product_id,
            **metadata,
        )
        if chunk:
            chunks.append(chunk)


def add_general_faq_chunks(faqs):
    for faq in faqs:
        chunk = make_chunk(
            f"Question: {faq.get('question', '')} Answer: {faq.get('answer', '')}",
            "general_faq",
        )
        if chunk:
            chunks.append(chunk)


def add_contact_chunks(contact_data):
    quick_contacts = contact_data.get("quick_contacts", {})
    quick_text = "; ".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in quick_contacts.items())
    chunk = make_chunk(quick_text, "contact_quick")
    if chunk:
        chunks.append(chunk)

    for branch in contact_data.get("branches", []):
        branch_name = branch.get("name", "Unknown branch")
        branch_text = "; ".join(
            f"{key.replace('_', ' ').title()}: {value}"
            for key, value in branch.items()
            if key != "name"
        )
        chunk = make_chunk(
            f"Qistwalay branch: {branch_name}. {branch_text}",
            "contact_branch",
            branch_name=branch_name,
        )
        if chunk:
            chunks.append(chunk)


def add_policy_chunks(policies):
    for policy_name, policy_text in policies.items():
        sections = re.split(r"\n{2,}|(?<=[.!?])\s+(?=[A-Z][^:]{2,}:)", policy_text)
        for section_number, section in enumerate(sections, 1):
            chunk = make_chunk(
                section,
                "policy",
                policy_name=policy_name,
                section_number=section_number,
            )
            if chunk:
                chunks.append(chunk)


def add_requirement_chunks(requirements):
    sections = re.split(r"\n{2,}|(?<=[.!?])\s+(?=[A-Z][^:]{2,}:)", requirements)
    for section_number, section in enumerate(sections, 1):
        chunk = make_chunk(
            section,
            "requirement",
            section_number=section_number,
        )
        if chunk:
            chunks.append(chunk)


def money(x):
    return f"Rs. {int(round(x)):,}"


def add_installment_chunks(products):
    for p in products:
        rows = p.get("installment_table") or []
        price = p.get("price_live") or p.get("price_catalog")
        if not rows or not price:
            continue
        slug = p["url"].rstrip("/").split("/")[-1]
        durations = sorted({r["duration_months"] for r in rows})
        lines = [
            f"Installment plans for {p['name']} (cash price {money(price)}).",
            f"Plan durations: {', '.join(str(d) for d in durations)} months.",
        ]
        no_down = [r for r in rows if r["down_payment_pct"] == 0]
        if no_down:
            parts = [
                f"{r['duration_months']} months: {money(r['monthly'])} today, then "
                f"{r['remaining_payments']} more monthly payments of {money(r['monthly'])} "
                f"(total {money(r['total'])})"
                for r in no_down
            ]
            lines.append("With no down payment (First Installment): " + "; ".join(parts) + ".")
        by_pct = {}
        for r in rows:
            if r["down_payment_pct"] > 0:
                by_pct.setdefault(r["down_payment_pct"], []).append(r)
        for pct in sorted(by_pct):
            rs = by_pct[pct]
            parts = [
                f"{r['duration_months']} months: {r['remaining_payments']} monthly payments of "
                f"{money(r['monthly'])} (total {money(r['total'])})"
                for r in rs
            ]
            lines.append(
                f"With a {pct}% down payment ({money(rs[0]['pay_today'])} paid today): "
                + "; ".join(parts) + "."
            )
        lines.append("These are estimates; final approval depends on verification and availability.")
        chunk = make_chunk(
            " ".join(lines), "product_installment",
            product_id=slug, product_name=p["name"], url=p["url"],
        )
        if chunk:
            chunks.append(chunk)


def flatten(value):
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "; ".join(t for t in (flatten(i) for i in value) if t)
    if isinstance(value, dict):
        return "; ".join(
            f"{k.replace('_', ' ')}: {flatten(v)}" for k, v in value.items() if flatten(v)
        )
    return ""


HOME_SECTIONS = {
    "offers": "Qistwalay current offers and announcements",
    "benefits": "Why choose Qistwalay",
    "stats": "Qistwalay in numbers",
    "shariah_statement": "Qistwalay Shariah-compliant installments",
    "about_blurb": "About Qistwalay",
    "serviced_by": "Qistwalay is serviced by",
    "brands": "Brands available at Qistwalay",
    "deal_packs": "Qistwalay deal packs and bundles",
}


def add_homepage_chunks(home):
    for key, label in HOME_SECTIONS.items():
        text = flatten(home.get(key))
        if text:
            chunk = make_chunk(f"{label}: {text}", "homepage_info", section=key)
            if chunk:
                chunks.append(chunk)
    for faq in home.get("faqs", []):
        question, answer = faq.get("question", ""), faq.get("answer", "")
        if re.search(r"tenure|down payment", question, re.I) or faq.get("already_in_site_faqs"):
            continue
        chunk = make_chunk(
            f"Question: {question} Answer: {answer}", "general_faq", source="homepage"
        )
        if chunk:
            chunks.append(chunk)


def add_deal_chunks(deals):
    for deal in deals:
        name = deal.get("name", "")
        price = deal.get("cash_price")
        items = deal.get("items", [])
        durations = deal.get("durations_months", [3, 6, 12])
        desc = deal.get("description", "")
        slug = deal.get("slug", "")

        parts = [f"Deal Package: {name}."]
        if price:
            parts.append(f"Cash Price: Rs. {price:,}.")
        if items:
            parts.append(f"Included items ({len(items)} items in package): {', '.join(items)}.")
        if durations:
            parts.append(f"Installment plan durations: {', '.join(str(d) for d in durations)} months.")
        if desc:
            parts.append(f"Package Details: {desc}")
        parts.append("All appliances come with official brand warranties. Verification is completed within 48 hours with delivery across Lahore.")

        chunk = make_chunk(
            " ".join(parts),
            "deal_package",
            deal_name=name,
            slug=slug,
            url=deal.get("url", ""),
            cash_price=price,
        )
        if chunk:
            chunks.append(chunk)


with SOURCE.open(encoding="utf-8") as source_file:
    dataset = json.load(source_file)
with CONTACT_SOURCE.open(encoding="utf-8") as contact_file:
    contact_data = json.load(contact_file)
with FAQ_SOURCE.open(encoding="utf-8") as faq_file:
    website_faqs = json.load(faq_file)

chunks = []
for product in dataset.get("products", []):
    add_product_chunks(product)
add_general_faq_chunks(website_faqs)
add_contact_chunks(contact_data)
add_policy_chunks(dataset.get("policies", {}))
add_requirement_chunks(dataset.get("requirements", ""))

add_installment_chunks(json.loads(PLANS_SOURCE.read_text(encoding="utf-8"))["products"])
add_homepage_chunks(json.loads(HOMEPAGE_SOURCE.read_text(encoding="utf-8")))

if DEALS_SOURCE.exists():
    with DEALS_SOURCE.open(encoding="utf-8") as deals_file:
        add_deal_chunks(json.load(deals_file))

with OUTPUT.open("w", encoding="utf-8") as output_file:
    json.dump(chunks, output_file, indent=2, ensure_ascii=False)

print(f"Created {OUTPUT} with {len(chunks)} chunks")
print(json.dumps({chunk_type: sum(c["type"] == chunk_type for c in chunks) for chunk_type in sorted({c["type"] for c in chunks})}, indent=2))