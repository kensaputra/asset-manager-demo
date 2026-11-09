"""Create assets.db and fill it with fake demo data.

Usage:
    python seed.py            # create assets.db next to this file
    python seed.py --force    # delete and rebuild it

Every person and asset here is invented. Demo logins:
    admin  / admin123   (can add, edit, hand over, verify)
    viewer / viewer123  (read only)
"""
import os
import random
import sqlite3
import sys
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FIRST = ["Andi", "Budi", "Citra", "Dewi", "Eka", "Fajar", "Gita", "Hendra", "Indah", "Joko",
         "Kartika", "Lukas", "Maya", "Nadia", "Oki", "Putri", "Rizky", "Sinta", "Taufik", "Wulan"]
LAST = ["Pratama", "Santoso", "Wijaya", "Lestari", "Hidayat", "Kusuma", "Saputri", "Nugroho",
        "Halim", "Setiawan"]
DEPARTMENTS = ["Finance", "HR", "GA", "Marketing", "Sales", "Live Streaming", "Warehouse", "IT"]
LOCATIONS = ["Head Office - Floor 1", "Head Office - Floor 2", "Live Room", "Warehouse",
             "Meeting Room A", "Server Room"]
CATALOG = {
    "Laptop": [("Lenovo", "ThinkPad E14"), ("ASUS", "VivoBook 14"), ("HP", "ProBook 440"),
               ("Apple", "MacBook Air M2")],
    "Desktop PC": [("Lenovo", "ThinkCentre M70"), ("Custom", "Streaming PC (RTX 4060)")],
    "Monitor": [("LG", "24MK430"), ("Samsung", "S24C310"), ("Dell", "P2422H")],
    "Printer": [("Epson", "L6270"), ("Ricoh", "IM 2702"), ("Canon", "G3020")],
    "Network": [("TP-Link", "Omada EAP245 AP"), ("Ruijie", "RG-S2910 Switch"), ("MikroTik", "hEX S Router")],
    "CCTV": [("Hikvision", "DS-2CD1023 Camera"), ("Dahua", "NVR 16ch")],
    "Phone": [("Samsung", "Galaxy A15"), ("Yealink", "T31P IP Phone")],
    "Furniture": [("Informa", "Office Chair"), ("Informa", "Desk 120cm")],
}
PREFIX = {"Laptop": "LT", "Desktop PC": "PC", "Monitor": "MN", "Printer": "PR", "Network": "NW",
          "CCTV": "CC", "Phone": "PH", "Furniture": "FN"}
COUNTS = {"Laptop": 34, "Desktop PC": 18, "Monitor": 30, "Printer": 6, "Network": 14,
          "CCTV": 20, "Phone": 12, "Furniture": 26}


def build(db_path, force=False):
    if os.path.exists(db_path):
        if not force:
            print(f"{db_path} already exists. Use --force to rebuild it.")
            return
        os.remove(db_path)

    rng = random.Random(42)
    today = date.today()
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    with open(os.path.join(BASE_DIR, "schema.sql")) as f:
        con.executescript(f.read())

    con.executemany("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", [
        ("admin", generate_password_hash("admin123", method="pbkdf2:sha256"), "admin"),
        ("viewer", generate_password_hash("viewer123", method="pbkdf2:sha256"), "viewer"),
    ])

    names = rng.sample([f"{a} {b}" for a in FIRST for b in LAST], 48)
    employees = [(n, rng.choice(DEPARTMENTS)) for n in names]
    con.executemany("INSERT INTO employees (name, department) VALUES (?, ?)", employees)
    employee_ids = list(range(1, len(employees) + 1))

    for category, count in COUNTS.items():
        for i in range(1, count + 1):
            brand, model = rng.choice(CATALOG[category])
            status = rng.choices(["active", "in_storage", "repair", "disposed"], [78, 12, 6, 4])[0]
            personal = category in ("Laptop", "Phone")
            holder = rng.choice(employee_ids) if status == "active" and (personal or rng.random() < 0.4) else None
            purchased = today - timedelta(days=rng.randint(60, 1500))
            verified = None
            if status != "disposed" and rng.random() < 0.7:
                verified = (today - timedelta(days=rng.randint(0, 50))).isoformat()
            location = "Server Room" if category == "Network" and rng.random() < 0.5 else rng.choice(LOCATIONS)
            cur = con.execute(
                """INSERT INTO assets (code, name, category, brand, serial_number, location, status,
                                       holder_id, purchased_on, last_verified)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f"{PREFIX[category]}-{i:03d}", f"{brand} {model}", category, brand,
                 f"SN{rng.randint(10**7, 10**8 - 1)}", location, status, holder,
                 purchased.isoformat(), verified),
            )
            if holder:
                previous = rng.choice(employee_ids) if rng.random() < 0.3 else None
                if previous and previous != holder:
                    con.execute(
                        "INSERT INTO handovers (asset_id, from_holder, to_holder, note, recorded_by, recorded_at) "
                        "VALUES (?, NULL, ?, 'Initial issue', 'admin', ?)",
                        (cur.lastrowid, previous, (purchased + timedelta(days=3)).isoformat() + " 09:00:00"))
                    note = rng.choice(["Employee resigned", "Moved to another team", "Replacement unit"])
                    when = today - timedelta(days=rng.randint(1, 40))
                else:
                    previous, note = None, "Initial issue"
                    when = purchased + timedelta(days=3)
                con.execute(
                    "INSERT INTO handovers (asset_id, from_holder, to_holder, note, recorded_by, recorded_at) "
                    "VALUES (?, ?, ?, ?, 'admin', ?)",
                    (cur.lastrowid, previous, holder, note, when.isoformat() + " 10:30:00"))

    con.commit()
    total = con.execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    con.close()
    print(f"Created {db_path} with {total} fake assets and {len(employees)} fake employees.")


if __name__ == "__main__":
    build(os.environ.get("DATABASE") or os.path.join(BASE_DIR, "assets.db"), force="--force" in sys.argv)
