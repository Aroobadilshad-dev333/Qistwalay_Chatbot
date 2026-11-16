"""
build_database.py
Single Source of Truth: Builds the complete SQLite eligibility database
from applicant CSV and latest 15 appliance categories with live prices & tenures.
Outputs directly to: backend/qistwalay_eligibility.db
"""
import shutil
import sqlite3
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "applicant_credit_eligibility_dataset.csv"
DB_PATH = HERE.parent / "qistwalay_eligibility.db"
BACKUP_PATH = HERE / "qistwalay_eligibility_backup.db"

# 15 Categories with updated live prices and max tenures
APPLIANCE_CATEGORIES = [
    ("Air Conditioner", 115000, 570000, 12),
    ("Air Cooler", 26400, 37620, 6),
    ("Air Purifier", 14999, 118999, 12),
    ("Deep Freezer", 57000, 133500, 10),
    ("Fans", 8200, 25900, 3),
    ("Geyser", 19000, 66000, 12),
    ("Kitchen Appliances", 20399, 78240, 12),
    ("Microwave Oven", 14400, 62900, 12),
    ("Mobile Phones", 39999, 505000, 12),
    ("Motorcycle", 115000, 245000, 13),
    ("Refrigerator", 49000, 381200, 10),
    ("Room Heaters", 8500, 16499, None),
    ("LED / Smart TV", 47500, 899900, 10),
    ("Washing Machine", 18000, 195000, 10),
    ("Water Dispenser", 29500, 40500, 6),
]


def build():
    # 1. Backup existing DB if present
    if DB_PATH.exists() and not BACKUP_PATH.exists():
        shutil.copy(DB_PATH, BACKUP_PATH)
        print(f"Backup created: {BACKUP_PATH.name}")

    conn = sqlite3.connect(DB_PATH)

    # 2. Build applicants table from CSV
    if CSV_PATH.exists():
        df = pd.read_csv(CSV_PATH)
        df.to_sql("applicants", conn, if_exists="replace", index=False)
        print(f"Table 'applicants' created ({len(df)} rows, {len(df.columns)} columns)")

    # 3. Build appliance_categories table
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS appliance_categories")
    cursor.execute("""
    CREATE TABLE appliance_categories (
        category TEXT PRIMARY KEY,
        price_min INTEGER,
        price_max INTEGER,
        max_tenure_months INTEGER
    )
    """)
    cursor.executemany("""
    INSERT INTO appliance_categories (category, price_min, price_max, max_tenure_months)
    VALUES (?, ?, ?, ?)
    """, APPLIANCE_CATEGORIES)
    conn.commit()
    print(f"Table 'appliance_categories' created ({len(APPLIANCE_CATEGORIES)} categories)")

    # 4. Verify JOIN
    test_query = """
    SELECT a.applicant_id, a.full_name, a.requested_appliance_category, c.price_min, c.price_max, c.max_tenure_months
    FROM applicants a
    JOIN appliance_categories c ON a.requested_appliance_category = c.category
    LIMIT 3
    """
    print("\nVerification Test JOIN:")
    print(pd.read_sql(test_query, conn))

    conn.close()
    print(f"\nDatabase successfully updated at: {DB_PATH}")


if __name__ == "__main__":
    build()