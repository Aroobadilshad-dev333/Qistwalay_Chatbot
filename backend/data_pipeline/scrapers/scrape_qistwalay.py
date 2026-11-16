from __future__ import annotations
import requests
from bs4 import BeautifulSoup
import json
import time
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "qistwalay_data"

# --- Description nikalne wala function ---

def get_full_description(soup):
    tab_link = soup.find("a", attrs={"data-bs-toggle": "tab"}, string=lambda t: t and "description" in t.lower())

    if not tab_link:
        for link in soup.find_all("a", attrs={"data-bs-toggle": "tab"}):
            if "description" in link.get_text(strip=True).lower():
                tab_link = link
                break

    if not tab_link:
        return None

    target_id = tab_link.get("href", "").replace("#", "")
    if not target_id:
        return None

    pane = soup.find("div", id=target_id)
    if not pane:
        return None

    card = pane.find("div", class_="premium-tab-card") or pane
    paragraphs = card.find_all("p")
    text = " ".join(p.get_text(separator=" ", strip=True) for p in paragraphs)
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else None

# --- Specifications table nikalne wala function ---
def get_specifications(soup):
    specs = {}
    table = soup.select_one(".premium-tab-card .premium-specs-table")
    if not table:
        return specs
    rows = table.find_all("div", class_="premium-specs-row")
    for row in rows:
        parts = row.get_text(separator="\n", strip=True).split("\n")
        parts = [p for p in parts if p]
        if len(parts) >= 2:
            specs[parts[0]] = " ".join(parts[1:])
    return specs


# --- Har product ke apne FAQs nikalne wala function ---
def get_product_faqs(soup):
    faqs = []
    details_blocks = soup.find_all("details")
    for d in details_blocks:
        summary = d.find("summary")
        answer_p = d.find("p")
        if not summary or not answer_p:
            continue
        question = re.sub(r"\s+", " ", summary.get_text(separator=" ", strip=True)).strip()
        answer = re.sub(r"\s+", " ", answer_p.get_text(separator=" ", strip=True)).strip()
        faqs.append({"question": question, "answer": answer})
    return faqs
# --- Requirements ko sirf EK dafa scrape karne wala function ---
def scrape_requirements_once(sample_url):
    r = requests.get(sample_url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    tab_link = None
    for link in soup.find_all("a", attrs={"data-bs-toggle": "tab"}):
        if "requirement" in link.get_text(strip=True).lower():
            tab_link = link
            break

    if not tab_link:
        return None

    target_id = tab_link.get("href", "").replace("#", "")
    if not target_id:
        return None

    pane = soup.find("div", id=target_id)
    if not pane:
        return None

    card = pane.find("div", class_="premium-tab-card") or pane

    # h2, h3 (headings) aur div/p (content) sab ordered tareeqe se nikalo
    parts = []
    for tag in card.find_all(["h2", "h3", "div", "p", "li"]):
        text = tag.get_text(strip=True)
        if text:
            parts.append(text)

    return " ".join(parts) if parts else None

# --- Main product scraper (ab specifications aur faqs bhi shamil hain — YEH THA FIX) ---
def scrape_product(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    script_tags = soup.find_all("script", type="application/ld+json")
    product_data = None
    for tag in script_tags:
        try:
            parsed = json.loads(tag.string)
            if isinstance(parsed, list):
                for item in parsed:
                    if item.get("@type") == "Product":
                        product_data = item
            elif parsed.get("@type") == "Product":
                product_data = parsed
        except Exception:
            continue

    if not product_data:
        return None

    short_desc = product_data.get("description")
    full_desc = get_full_description(soup)
    final_desc = full_desc if full_desc else short_desc

    return {
        "url": url,
        "name": product_data.get("name"),
        "description": final_desc,
        "specifications": get_specifications(soup),   # FIX: pehle missing thi
        "faqs": get_product_faqs(soup),                # FIX: pehle missing thi
        "sku": product_data.get("sku"),
        "category": product_data.get("category"),
        "brand": product_data.get("brand", {}).get("name"),
        "price": product_data.get("offers", {}).get("price"),
        "currency": product_data.get("offers", {}).get("priceCurrency"),
        "availability": product_data.get("offers", {}).get("availability"),
    }


# --- Sitemap se product URLs nikalo ---
r = requests.get("https://www.qistwalay.com/sitemap.xml", headers={"User-Agent": "Mozilla/5.0"})
soup = BeautifulSoup(r.content, "xml")
product_urls = [loc.text for loc in soup.find_all("loc") if "/shop/product/" in loc.text]
print(len(product_urls), "products mile")


# --- Pehle test karo ek product pe ---
test = scrape_product(product_urls[3])
print("DESC:", test["description"][:150] if test["description"] else None)
print("SPECS:", test["specifications"])
print("FAQS:", test["faqs"])

# --- Requirements sirf ek dafa scrape karo ---
requirements_text = scrape_requirements_once(product_urls[0])
with (DATA_DIR / "qistwalay_requirements.json").open("w", encoding="utf-8") as f:
    json.dump({"requirements": requirements_text}, f, indent=2, ensure_ascii=False)
print("Requirements saved (once):", (requirements_text or "")[:100])

# --- Sab 226 products pe chalao (test theek hone ke baad uncomment karo) ---
results = []
for i, u in enumerate(product_urls, 1):
    print(f"[{i}/{len(product_urls)}] Scraping: {u}")
    data = scrape_product(u)
    if data:
         results.append(data)
    time.sleep(0.5)

with (DATA_DIR / "qistwalay_products.json").open("w", encoding="utf-8") as f:
     json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nDone! {len(results)} products saved to qistwalay_products.json")


# --- Site-wide general FAQs (koi change nahi) ---
def scrape_faqs():
    r = requests.get("https://www.qistwalay.com/faqs", headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")
    headers = soup.find_all("div", class_="accordion-header")
    faqs = []
    for h in headers:
        link = h.find("a")
        title_tag = h.find("div", class_="accordion-title")
        if not link or not title_tag:
            continue
        question = title_tag.get_text(strip=True)
        target_id = link.get("data-bs-target", "").replace("#", "")
        answer_div = soup.find(id=target_id)
        answer = answer_div.get_text(strip=True) if answer_div else ""
        faqs.append({"question": question, "answer": answer})
    return faqs


faqs = scrape_faqs()
print(f"{len(faqs)} FAQs scraped\n")
with (DATA_DIR / "qistwalay_faqs.json").open("w", encoding="utf-8") as f:
    json.dump(faqs, f, indent=2, ensure_ascii=False)
print("Saved to qistwalay_faqs.json")


# --- Policy pages (koi change nahi) ---
def scrape_policy(url):
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")
    content = soup.find("main") or soup.find("article") or soup.body
    return content.get_text(separator="\n", strip=True) if content else ""


policy_pages = {
    "terms_and_conditions": "https://www.qistwalay.com/terms-and-conditions",
    "return_and_refund": "https://www.qistwalay.com/return-and-refund-policy",
    "privacy_policy": "https://www.qistwalay.com/privacy-policy",
    "verification_process": "https://www.qistwalay.com/verification-process",
}

policies = {}
for name, url in policy_pages.items():
    print(f"Scraping: {name}")
    policies[name] = scrape_policy(url)
    time.sleep(1)

with (DATA_DIR / "qistwalay_policies.json").open("w", encoding="utf-8") as f:
    json.dump(policies, f, indent=2, ensure_ascii=False)
print(f"\nDone! Policies saved to qistwalay_policies.json")


# --- Sab kuch combine karo ---
with (DATA_DIR / "qistwalay_products.json").open(encoding="utf-8") as f:
    products = json.load(f)
with (DATA_DIR / "qistwalay_faqs.json").open(encoding="utf-8") as f:
    faqs = json.load(f)
with (DATA_DIR / "qistwalay_policies.json").open(encoding="utf-8") as f:
    policies = json.load(f)
with (DATA_DIR / "qistwalay_requirements.json").open(encoding="utf-8") as f:
    requirements = json.load(f)

full_dataset = {
    "products": products,
    "faqs": faqs,
    "policies": policies,
    "requirements": requirements["requirements"]
}

with (DATA_DIR / "qistwalay_full_dataset.json").open("w", encoding="utf-8") as f:
    json.dump(full_dataset, f, indent=2, ensure_ascii=False)

print("Combined dataset ready!")

test = scrape_product(product_urls[3])
print("FAQS:", test["faqs"])

def build_full_description(p):
    specs_text = " ".join(f"{k}: {v}." for k, v in p.get("specifications", {}).items())
    return (
        f"Product Name: {p.get('name', '')}. "
        f"Brand: {p.get('brand', '')}. "
        f"Category: {p.get('category', '')}. "
        f"SKU: {p.get('sku', '')}. "
        f"Price: {p.get('price', '')} {p.get('currency', '')}. "
        f"Availability: {p.get('availability', '')}. "
        f"Description: {p.get('description', '')} "
        f"Specifications: {specs_text}"
    )
def scrape_contact_page():
    url = "https://www.qistwalay.com/contact"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
    soup = BeautifulSoup(r.text, "html.parser")

    contact_info = {}

    # --- Quick contact cards (Call us, WhatsApp, Email) ---
    quick_cards = soup.find_all("a", class_="contact-hub__quick-card")
    quick_contacts = {}
    for card in quick_cards:
        label_tag = card.find("span", class_="contact-hub__quick-label")
        value_tag = card.find("strong")
        if label_tag and value_tag:
            label = label_tag.get_text(strip=True).lower().replace(" ", "_")
            quick_contacts[label] = value_tag.get_text(strip=True)
    contact_info["quick_contacts"] = quick_contacts

    # --- Branch cards ---
    branches = []
    branch_cards = soup.find_all("div", class_="contact-hub__location-card")
    for card in branch_cards:
        name_tag = card.find("h4")
        shop_tag = card.find("span")
        address_tag = card.find("p")
        phone_tag = card.find("a", class_="contact-hub__location-phone")
        map_tag = card.find("a", href=re.compile(r"maps\.app\.goo\.gl|google\.com/maps"))

        branches.append({
            "name": name_tag.get_text(strip=True) if name_tag else None,
            "shop_no": shop_tag.get_text(strip=True) if shop_tag else None,
            "address": address_tag.get_text(strip=True) if address_tag else None,
            "phone": phone_tag.get_text(strip=True) if phone_tag else None,
            "map_link": map_tag.get("href") if map_tag else None,
        })
    contact_info["branches"] = branches

    return contact_info


contact_data = scrape_contact_page()
print(contact_data)

with (DATA_DIR / "qistwalay_contact.json").open("w", encoding="utf-8") as f:
    json.dump(contact_data, f, indent=2, ensure_ascii=False)

print("Saved to qistwalay_contact.json")

FORMULA_VERIFIED = {
    "no_down_payment": True,
    "with_down_payment": False,  # <-- flip to True once confirmed against a real example
}


def compute_plan_row(cash_price: float, duration_months: int,
                      markup_pct: float, down_payment_pct: int) -> dict:
    """Compute one row of the installment matrix for one plan + one down-payment option."""

    if down_payment_pct == 0:
        # "First Installment" (no down payment) branch — CONFIRMED
        total_repay = cash_price * (1 + markup_pct / 100)
        monthly = total_repay / duration_months
        due_today = round(monthly, 2)
        down_payment_amount = 0.0
        remaining_months = duration_months - 1
        verified = FORMULA_VERIFIED["no_down_payment"]
    else:
        # Down-payment-selected branch — UNVERIFIED, best guess
        total_repay = cash_price * (1 + markup_pct / 100)
        down_payment_amount = cash_price * (down_payment_pct / 100)
        remaining_balance = total_repay - down_payment_amount
        remaining_months = duration_months - 1
        monthly = remaining_balance / remaining_months if remaining_months > 0 else remaining_balance
        due_today = round(down_payment_amount, 2)
        verified = FORMULA_VERIFIED["with_down_payment"]

    return {
        "duration_months": duration_months,
        "down_payment_pct": down_payment_pct,
        "down_payment_amount": round(down_payment_amount, 2),
        "monthly_amount": round(monthly, 2),
        "total_repay": round(total_repay, 2),
        "due_today": due_today,
        "remaining_months": remaining_months,
        "formula_verified": verified,
    }


def build_installment_matrix(cash_price: float, installment_plans_raw: list[dict],
                              down_payment_options_pct: list[int]) -> list[dict]:
    """
    Cross-product every plan THIS PRODUCT ACTUALLY HAS (read from its own
    <option> tags — e.g. an air fryer might only have a 3-month plan, an
    AC might have 5 and 10) x every down-payment option it offers.
    Never fills in a plan or down-payment that isn't really there.
    """
    matrix = []
    for plan in installment_plans_raw:
        duration = plan["duration_months"]

        # Row for "no down payment", using markup_no_advance
        matrix.append(compute_plan_row(
            cash_price, duration, plan["markup_no_advance_pct"], down_payment_pct=0
        ))

        # One row per real down-payment option, using markup_advance
        for pct in down_payment_options_pct:
            matrix.append(compute_plan_row(
                cash_price, duration, plan["markup_advance_pct"], down_payment_pct=pct
            ))

    return matrix