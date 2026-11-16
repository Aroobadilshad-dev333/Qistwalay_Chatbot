"""
scrape_installment_plans.py

Visits every product page in qistwalay_products.json and reads what the site itself shows:
the live cash price, the plan durations with their markups, and the down-payment choices.

Output: qistwalay_installment_plans.json

Formulas (checked against the site's installment calculator):
  First Installment (no down payment):
      total   = price * (1 + markup_no_advance / 100)
      monthly = total / months              (the first instalment is paid today)
  Down payment (20% ... 50%):
      down     = price * pct / 100
      financed = (price - down) * (1 + markup_advance / 100)
      monthly  = financed / (months - 1)
      total    = down + financed
"""
import json
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).resolve().parents[1] / "qistwalay_data"

HEADERS = {"User-Agent": "Mozilla/5.0"}


def fetch(url):
    for _ in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
        except Exception:
            time.sleep(2)
    return None


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def live_price(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string)
        except Exception:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and item.get("@type") == "Product":
                offers = item.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                return to_float(offers.get("price"))
    return None


def parse_options(soup):
    plans = []
    for opt in soup.select("select#installment-plan-select option"):
        months = opt.get("data-duration") or opt.get("value")
        try:
            months = int(months)
        except (TypeError, ValueError):
            continue
        plans.append({
            "duration_months": months,
            "markup_advance": to_float(opt.get("data-markup-advance")),
            "markup_advance_type": opt.get("data-markup-advance-type"),
            "markup_no_advance": to_float(opt.get("data-markup-no-advance")),
            "markup_no_advance_type": opt.get("data-markup-no-advance-type"),
        })
    down = []
    for opt in soup.select("select#down-payment-select option"):
        v = opt.get("value")
        if v and v.isdigit():
            down.append(int(v))
    return plans, down


def compute_table(price, plans, down_options):
    rows = []
    if not price:
        return rows
    for p in plans:
        m = p["duration_months"]
        if p["markup_no_advance_type"] == "percent" and p["markup_no_advance"] is not None:
            total = price * (1 + p["markup_no_advance"] / 100)
            rows.append({
                "down_payment_pct": 0, "duration_months": m,
                "pay_today": round(total / m), "monthly": round(total / m),
                "remaining_payments": m - 1, "total": round(total),
            })
        if m > 1 and p["markup_advance_type"] == "percent" and p["markup_advance"] is not None:
            for pct in down_options:
                down = price * pct / 100
                financed = (price - down) * (1 + p["markup_advance"] / 100)
                rows.append({
                    "down_payment_pct": pct, "duration_months": m,
                    "pay_today": round(down), "monthly": round(financed / (m - 1)),
                    "remaining_payments": m - 1, "total": round(down + financed),
                })
    return rows


def main():
    with (DATA_DIR / "qistwalay_products.json").open(encoding="utf-8") as f:
        catalog = json.load(f)

    results, failed, no_plans, price_changed = [], [], [], []
    for i, c in enumerate(catalog, 1):
        url = c["url"]
        print(f"[{i}/{len(catalog)}] {url}")
        soup = fetch(url)
        if soup is None:
            failed.append(url)
            continue

        plans, down = parse_options(soup)
        catalog_price = to_float(c.get("price"))
        price = live_price(soup) or catalog_price
        if not plans:
            no_plans.append(url)
        if catalog_price and price and int(catalog_price) != int(price):
            price_changed.append((c.get("name"), int(catalog_price), int(price)))

        results.append({
            "url": url,
            "name": c.get("name"),
            "price_catalog": catalog_price,
            "price_live": price,
            "plans": plans,
            "down_payment_options_pct": down,
            "installment_table": compute_table(price, plans, down),
        })
        time.sleep(1)

    with (DATA_DIR / "qistwalay_installment_plans.json").open("w", encoding="utf-8") as f:
        json.dump({"products": results}, f, indent=2, ensure_ascii=False)

    print("\n" + "=" * 50)
    print(f"Products saved: {len(results)} of {len(catalog)}")
    print(f"With plans: {len(results) - len(no_plans)} | without plans: {len(no_plans)}")
    for u in no_plans:
        print("  NO PLANS:", u)
    print(f"Failed requests: {len(failed)}")
    for u in failed:
        print("  FAILED:", u)
    print(f"Price changed since the catalog was built: {len(price_changed)}")
    for n, a, b in price_changed:
        print(f"  {n} | catalog: {a} | live: {b}")

    check = "haier-df-385-inv-1360-cubic-ft-double-door-ref-freezer"
    for r in results:
        if r["url"].endswith(check):
            print("\nSample check (Haier DF-385 INV):", r["price_live"])
            for p in r["plans"]:
                print("  ", p)


if __name__ == "__main__":
    main()