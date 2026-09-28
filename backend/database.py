import sqlite3
import json

DB_FILE = "invoices.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_name TEXT,
            invoice_number TEXT,
            total REAL,
            currency TEXT,
            raw_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_invoice(invoice_dict: dict):
    # Member 1's parser can nest vendor under ["vendor"]["name"] or top-level
    vendor = (
        invoice_dict.get("vendor", {}).get("name")
        or invoice_dict.get("vendor_name")
        or "Unknown"
    )
    inv_num = (
        invoice_dict.get("invoice", {}).get("number")
        or invoice_dict.get("invoice_number")
        or ""
    )
    amounts = invoice_dict.get("amounts", {})
    total = amounts.get("total") or invoice_dict.get("total_amount") or 0.0
    currency = invoice_dict.get("currency", "USD")

    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO invoices (vendor_name, invoice_number, total, currency, raw_data)
        VALUES (?, ?, ?, ?, ?)
    """, (vendor, inv_num, float(total), currency, json.dumps(invoice_dict)))
    conn.commit()
    conn.close()

def get_history(vendor: str, limit: int = 3) -> list:
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        SELECT raw_data FROM invoices
        WHERE LOWER(vendor_name) = ?
        ORDER BY id DESC LIMIT ?
    """, (vendor.strip().lower(), limit))
    rows = cur.fetchall()
    conn.close()
    
    # Return chronologically (oldest to newest)
    return [json.loads(r[0]) for r in reversed(rows)]
