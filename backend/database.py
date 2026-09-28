
import sqlite3
import json

DB_FILE = "audit_records.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_name TEXT,
        invoice_number TEXT,
        total_amount REAL,
        currency TEXT,
        raw_data TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

def get_latest_invoice_for_vendor(vendor_name: str):
    """Fetches the most recent invoice for this vendor."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT raw_data FROM invoices 
        WHERE LOWER(vendor_name) = LOWER(?) 
        ORDER BY id DESC LIMIT 1
    """, (vendor_name,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])  # Returns the previous parsed invoice dict
    return None

def save_invoice(parsed_invoice: dict):
    """Saves the parsed invoice for future comparisons."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    vendor = parsed_invoice["vendor"]["name"]
    inv_num = parsed_invoice["invoice"]["number"]
    total = parsed_invoice["amounts"]["total"]
    currency = parsed_invoice["invoice"]["currency"]
    raw_json = json.dumps(parsed_invoice)

    cursor.execute("""
        INSERT INTO invoices (vendor_name, invoice_number, total_amount, currency, raw_data)
        VALUES (?, ?, ?, ?, ?)
    """, (vendor, inv_num, total, currency, raw_json))
    conn.commit()
    conn.close()

init_db()