import ast, json, re, time, requests
from pathlib import Path
from bs4 import BeautifulSoup

DATA_DIR = Path(__file__).resolve().parents[1] / "qistwalay_data"
SRC = Path(__file__).resolve().with_name("scrape_qistwalay.py")
WANTED = {"get_full_description", "get_specifications", "get_product_faqs", "scrape_product"}

# purani file se sirf zaroori functions nikalo (poori file chalaye baghair)
ns = {"requests": requests, "BeautifulSoup": BeautifulSoup, "json": json, "re": re, "time": time}
tree = ast.parse(SRC.read_text(encoding="utf-8"))
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in WANTED:
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(SRC), "exec"), ns)
scrape_product = ns["scrape_product"]

BASE = "https://www.qistwalay.com/shop/product/"
SLUGS = [
    "32-google-led",
    "haier-100-qd-mini-led-google-tv",
    "haier-43-google-led",
    "haier-43-qled-google-tv",
    "haier-50-google-led",
    "haier-55-google-led",
    "haier-75-google-led",
    "haier-85-qd-mini-led-google-tv",
    "haier-twin-tub-washing-machine",
    "kenwood-multi-door-inverter-refrigerator-krfi-5504",
    "kenwood-multi-door-refrigerator-krfi-5622sbs",
    "pel-life-pro-refrigerator-room-series",
    "twin-tub-series",
    "vivo-v70-fe",
    "vivo-v80-lite",
    "vivo-x-fold-5",
    "vivo-x300-fe",
    "vivo-y500",
]

results, failed = [], []
for i, slug in enumerate(SLUGS, 1):
    url = BASE + slug
    print(f"[{i}/{len(SLUGS)}] {url}")
    try:
        data = scrape_product(url)
    except Exception as e:
        data = None
        print("   error:", e)
    if data:
        results.append(data)
    else:
        failed.append(url)
    time.sleep(1)

with (DATA_DIR / "new_products_18.json").open("w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n{len(results)} scrape hue, {len(failed)} fail")
for u in failed:
    print("FAILED:", u)

# purane products se format aur duplicate check
with (DATA_DIR / "qistwalay_products.json").open(encoding="utf-8") as old_file:
    old = json.load(old_file)
old_keys = set(old[0].keys())
old_urls = {p.get("url") for p in old}
print("\nPurane products:", len(old))
print("Pehle se maujood (duplicate):", [p["url"] for p in results if p["url"] in old_urls])
for p in results[:3]:
    print(p["name"], "|", p["price"], "|", p["category"],
          "| missing keys:", old_keys - set(p.keys()),
          "| extra keys:", set(p.keys()) - old_keys)