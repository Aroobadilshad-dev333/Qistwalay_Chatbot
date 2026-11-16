"""
scrape_deals.py
Scrapes all 6 deal and bundle packages (Jahez and Room packages) from Qistwalay:
- Jahez Package 1, 2, 3
- Room Package 1, 2, 3
Extracts cash price, starting monthly installment, included items, and descriptions.
Output: qistwalay_deals.json
"""
import json
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).resolve().parents[1] / "qistwalay_data"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

DEAL_URLS = [
    "https://www.qistwalay.com/shop/deal/jahez-package-1",
    "https://www.qistwalay.com/shop/deal/jahez-package-2",
    "https://www.qistwalay.com/shop/deal/jahez-package-3",
    "https://www.qistwalay.com/shop/deal/room-package-1",
    "https://www.qistwalay.com/shop/deal/room-package-2",
    "https://www.qistwalay.com/shop/deal/room-package-3",
]


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def scrape_deals():
    deals = []
    print("Scraping all 6 Qistwalay deals...")

    for url in DEAL_URLS:
        slug = url.split("/")[-1]
        print(f"Scraping {slug}...")

        soup = None
        for attempt in range(2):
            try:
                r = requests.get(url, headers=HEADERS, timeout=30)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, "html.parser")
                break
            except Exception as e:
                print(f"Retry {attempt+1} for {url} due to {e}")
                time.sleep(2)

        if not soup:
            print(f"Failed to fetch {url}")
            continue

        # Extract name, price, description from JSON-LD
        ld = {}
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string)
                if data.get("@type") == "Product":
                    ld = data
                    break
            except Exception:
                pass

        name = ld.get("name") or slug.replace("-", " ").title()

        price = None
        if ld.get("offers") and "price" in ld["offers"]:
            try:
                price = int(ld["offers"]["price"])
            except (ValueError, TypeError):
                pass

        desc = ld.get("description", "")

        # Extract items listed (1 x Item Name ...)
        raw_items = [
            t.strip()
            for t in soup.find_all(string=lambda s: s and ("1 x" in s or "2 x" in s))
        ]
        items = list(dict.fromkeys(raw_items))

        # Extract available installment durations from select
        durations = []
        select = soup.find("select", id="installment-plan-select")
        if select:
            for opt in select.find_all("option"):
                d = opt.get("data-duration")
                if d and d.isdigit():
                    durations.append(int(d))
        durations = sorted(set(durations)) or [3, 6, 12]

        deals.append({
            "name": name,
            "slug": slug,
            "url": url,
            "cash_price": price,
            "durations_months": durations,
            "items": items,
            "description": desc,
        })
        time.sleep(1)

    output_path = DATA_DIR / "qistwalay_deals.json"
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(deals, f, indent=2, ensure_ascii=False)

    print(f"\nSuccessfully saved all {len(deals)} deals to {output_path}!")


if __name__ == "__main__":
    scrape_deals()