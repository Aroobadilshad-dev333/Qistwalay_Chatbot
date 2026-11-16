"""
scrape_homepage.py  --  scrapes the Qistwalay homepage into qistwalay_homepage.json

Run from qistwalay-app/backend/data_pipeline:
    python scrapers/scrape_homepage.py

It makes ONE request to https://www.qistwalay.com/ (after checking robots.txt), saves the raw
page as homepage_raw.html (so we can look at it if something is missing) and writes
qistwalay_homepage.json. It does not touch the RAG index and costs no OpenAI money.

Deliberately NOT scraped: customer reviews, Instagram feed, social posts, login pages.
The "satisfied customers" counter is skipped too (the page text shows just "10").
"""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE = "https://www.qistwalay.com"
DATA_DIR = Path(__file__).resolve().parents[1] / "qistwalay_data"
HEADERS = {"User-Agent": "Mozilla/5.0"}
PRODUCTS_FILE = DATA_DIR / "qistwalay_products.json"   # existing catalog (to find what is missing)
FAQS_FILE = DATA_DIR / "qistwalay_faqs.json"           # existing site-wide FAQs (to flag duplicates)
OUT_FILE = DATA_DIR / "qistwalay_homepage.json"

PRICE_RE = re.compile(r"Starting From\s*Rs\.?\s*([\d,]+)\s*(/\s*m)?", re.I)


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def slug(url):
    return url.rstrip("/").split("/")[-1].split("?")[0]


def robots_allows_homepage():
    rp = RobotFileParser()
    try:
        r = requests.get(BASE + "/robots.txt", headers=HEADERS, timeout=30)
        rp.parse(r.text.splitlines())
        return rp.can_fetch(HEADERS["User-Agent"], BASE + "/")
    except Exception as e:
        print("Warning: could not read robots.txt:", e)
        return True


def fetch_homepage():
    r = requests.get(BASE + "/", headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "utf-8"
    with (DATA_DIR / "homepage_raw.html").open("w", encoding="utf-8") as f:
        f.write(r.text)
    soup = BeautifulSoup(r.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup


# ----------------------------------------------------------------------------
def card_of(a):
    """The card (li or nearby block) that holds a product / deal link and its price."""
    node = a.find_parent("li")
    if node:
        return node
    node = a
    for _ in range(4):
        node = node.parent
        if node is None:
            break
        if PRICE_RE.search(node.get_text(" ", strip=True)):
            return node
    return a.parent


def price_of(card):
    m = PRICE_RE.search(clean(card.get_text(" ", strip=True)))
    if not m:
        return None, False
    return int(m.group(1).replace(",", "")), bool(m.group(2))


def parse_links(soup):
    """Products, deals, categories and brands, found by their link patterns."""
    section = ""
    products, deals, categories, brands = {}, {}, {}, {}

    for el in soup.find_all(["h2", "a"]):
        if el.name == "h2":
            section = clean(el.get_text())
            continue
        href = el.get("href", "")
        url = urljoin(BASE, href)
        name = clean(el.get_text(" "))

        if "/shop/product/" in href and name:
            key = (section, url.split("?")[0])
            if key in products:
                continue
            card = card_of(el)
            price, per_month = price_of(card)
            logo = card.find("img", alt=re.compile(r"logo$", re.I))
            brand = re.sub(r"\s*logo$", "", logo["alt"], flags=re.I).strip() if logo else None
            products[key] = {"name": name, "url": key[1], "brand": brand, "section": section,
                             "starting_from_pkr": price, "per_month": per_month}

        elif "/shop/deal/" in href:
            clean_url = url.split("?")[0]
            img = el.find("img")
            label = name or (clean(img.get("alt", "")) if img else "")
            entry = deals.setdefault(clean_url, {"name": "", "url": clean_url,
                                                 "starting_from_pkr": None, "per_month": False})
            if label and not entry["name"]:
                entry["name"] = label
            price, per_month = price_of(card_of(el))
            if price and not entry["starting_from_pkr"]:
                entry["starting_from_pkr"], entry["per_month"] = price, per_month

        elif "/shop?category=" in href:
            m = re.fullmatch(r"(.+?)\s+(\d+)\s+items?", name, re.I)
            if m and url not in categories:
                categories[url] = {"name": m.group(1), "items": int(m.group(2)), "url": url}

        elif "/shop?brand=" in href:
            img = el.find("img")
            brand = clean(img.get("alt", "")) if img else name
            if brand and url not in brands:
                brands[url] = {"name": brand, "url": url}

    return (list(products.values()), list(deals.values()),
            list(categories.values()), list(brands.values()))


def page_lines(soup):
    lines = [clean(l) for l in soup.get_text("\n").split("\n")]
    return [l for l in lines if l]


def parse_faqs(lines):
    """Homepage FAQ block: a line ending with '?' is a question, the lines after it are the answer."""
    end = next((i for i, l in enumerate(lines) if l.lower().startswith("see all faqs")), None)
    if end is None:
        return []
    starts = [i for i, l in enumerate(lines[:end]) if l.lower().startswith("frequently asked questions")]
    if not starts:
        return []
    faqs, q, ans = [], None, []
    for l in lines[starts[-1] + 1:end]:
        if l.endswith("?"):
            if q and ans:
                faqs.append({"question": q, "answer": " ".join(ans)})
            q, ans = l, []
        elif q:
            ans.append(l)
    if q and ans:
        faqs.append({"question": q, "answer": " ".join(ans)})
    return faqs


def parse_offers(soup):
    text = clean(soup.get_text(" "))
    m = re.search(r"Offers & Updates(.*?)\+92", text)
    if not m:
        return []
    seen, offers = set(), []
    # "Rs." must not be treated as the end of a sentence
    segment = m.group(1).strip().replace("Rs.", "Rs<DOT>")
    for s in re.split(r"(?<=[.!])\s+", segment):
        s = clean(s.replace("Rs<DOT>", "Rs."))
        if s and s.lower() not in seen:
            seen.add(s.lower())
            offers.append(s)
    return offers


def parse_misc(soup, lines):
    text_lower = clean(soup.get_text(" ")).lower()

    stats = {}
    for label in ("Years in Industry", "Authorized Company Dealerships", "Physical Locations"):
        i = next((k for k, l in enumerate(lines) if l.lower() == label.lower()), None)
        if i and lines[i - 1].replace("+", "").isdigit():
            stats[label] = lines[i - 1]

    benefit_phrases = ["10% Discount on Cash Purchase", "Easy at Home Verification Process",
                       "100% Original Products", "Company Warranty Products",
                       "Pocket-Friendly Payment Options", "No Bank or Credit Card Details Required",
                       "No Banking Information Required", "No Hidden or Extra Charges",
                       "Free Home Delivery"]
    benefits = [p for p in benefit_phrases if p.lower() in text_lower]

    def find_text(pattern):
        s = soup.find(string=re.compile(pattern, re.I))
        return clean(s) if s else None

    domains = {"facebook.com": "Facebook", "instagram.com": "Instagram", "tiktok.com": "TikTok",
               "youtube.com": "YouTube", "play.google.com": "Google Play app",
               "apps.apple.com": "App Store app"}
    strip_query = {"instagram.com", "tiktok.com", "youtube.com"}
    links = {}
    for a in soup.find_all("a", href=True):
        for d, label in domains.items():
            if d in a["href"] and label not in links:
                links[label] = a["href"].split("?")[0] if d in strip_query else a["href"]

    minhaj = soup.find("img", attrs={"title": re.compile("Minhaj", re.I)})
    meta = soup.find("meta", attrs={"name": "description"})
    h1 = soup.find("h1")

    return {
        "hero_heading": clean(h1.get_text()) if h1 else None,
        "meta_description": meta.get("content") if meta else None,
        "stats": stats,
        "benefits": benefits,
        "shariah_statement": find_text(r"follows Shariah principles"),
        "about_blurb": find_text(r"Qistwalay makes it easy"),
        "links": links,
        "serviced_by": minhaj.get("title") if minhaj else None,
    }


def load_json(path):
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def main():
    if not robots_allows_homepage():
        sys.exit("robots.txt does not allow fetching the homepage. Stopping.")

    soup = fetch_homepage()
    products, deals, categories, brands = parse_links(soup)
    lines = page_lines(soup)

    # FAQs: flag the ones already in the site-wide FAQ file
    existing = load_json(FAQS_FILE) or []
    known_q = {clean(f.get("question", "")).lower() for f in existing if isinstance(f, dict)}
    faqs = [
        {"question": clean(d.find("summary").get_text(" ", strip=True)),
         "answer": clean(d.find("p").get_text(" ", strip=True))}
        for d in soup.select("details.premium-faq__item")
        if d.find("summary") and d.find("p")
    ]
    for f in faqs:
        f["already_in_site_faqs"] = f["question"].lower() in known_q

    # products shown on the homepage that are not in the catalog yet
    catalog = load_json(PRODUCTS_FILE)
    missing = []
    if catalog:
        have = {slug(p.get("url", "")) for p in catalog}
        seen = set()
        for p in products:
            s = slug(p["url"])
            if s not in have and s not in seen:
                seen.add(s)
                missing.append({"name": p["name"], "url": p["url"]})

    data = {
        "source": BASE + "/",
        "offers": parse_offers(soup),
        **parse_misc(soup, lines),
        "categories": categories,
        "best_sellers": [p for p in products if "best seller" in p["section"].lower()],
        "featured_products": [p for p in products if "featured products" in p["section"].lower()],
        "deal_packs": deals,
        "brands": brands,
        "faqs": faqs,
        "homepage_products_not_in_catalog": missing,
    }

    with OUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Saved {OUT_FILE}")
    print(f"  offers:               {len(data['offers'])}")
    print(f"  categories:           {len(categories)}  (items total: {sum(c['items'] for c in categories)})")
    print(f"  best sellers:         {len(data['best_sellers'])}")
    print(f"  featured products:    {len(data['featured_products'])}")
    print(f"  deal packs:           {len(deals)}")
    print(f"  brands:               {len(brands)}")
    print(f"  faqs:                 {len(faqs)}  (new, not in site FAQs: {sum(not f['already_in_site_faqs'] for f in faqs)})")
    print(f"  stats / benefits:     {len(data['stats'])} / {len(data['benefits'])}")
    print(f"  not in catalog:       {len(missing)}")
    if catalog is None:
        print(f"  (could not find {PRODUCTS_FILE} here, so the catalog comparison was skipped)")
    for m in missing:
        print("    -", m["name"], "|", m["url"])


if __name__ == "__main__":
    main()