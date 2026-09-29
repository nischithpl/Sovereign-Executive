import sqlite3
import json
import os

# Always keep the database beside the project files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_FILE = os.path.join(BASE_DIR, "invoices.db")


def get_connection():
    return sqlite3.connect(DB_FILE)


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Invoice memory
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

    # Contract memory
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_name TEXT NOT NULL,
            agreed_price REAL,
            max_annual_increase REAL,
            renewal_date TEXT,
            notice_days INTEGER DEFAULT 30,
            price_clause TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def invoice_exists(vendor: str, invoice_number: str) -> bool:
    init_db()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT 1
        FROM invoices
        WHERE LOWER(TRIM(vendor_name)) = LOWER(TRIM(?))
        AND LOWER(TRIM(invoice_number)) = LOWER(TRIM(?))
        LIMIT 1
    """, (vendor, invoice_number))

    exists = cur.fetchone() is not None

    conn.close()
    return exists


def save_invoice(invoice_dict: dict):
    init_db()

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

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO invoices (
            vendor_name,
            invoice_number,
            total,
            currency,
            raw_data
        )
        VALUES (?, ?, ?, ?, ?)
    """, (
        vendor,
        inv_num,
        float(total),
        currency,
        json.dumps(invoice_dict)
    ))

    conn.commit()
    conn.close()


def get_history(vendor: str, limit: int = 3) -> list:
    init_db()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT raw_data
        FROM invoices
        WHERE LOWER(vendor_name) = LOWER(?)
        ORDER BY id DESC
        LIMIT ?
    """, (vendor.strip(), limit))

    rows = cur.fetchall()
    conn.close()

    return [json.loads(r[0]) for r in reversed(rows)]


def save_contract(
    vendor_name: str,
    agreed_price=None,
    max_annual_increase=None,
    renewal_date=None,
    notice_days=30,
    price_clause=None
):
    init_db()

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO contracts (
            vendor_name,
            agreed_price,
            max_annual_increase,
            renewal_date,
            notice_days,
            price_clause
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        vendor_name.strip(),
        agreed_price,
        max_annual_increase,
        renewal_date,
        notice_days,
        price_clause
    ))

    conn.commit()
    conn.close()


def list_contracts() -> list:
    init_db()

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            vendor_name,
            agreed_price,
            max_annual_increase,
            renewal_date,
            notice_days,
            price_clause,
            created_at
        FROM contracts
        ORDER BY id DESC
    """)

    rows = cur.fetchall()
    conn.close()

    return [dict(row) for row in rows]

def get_contract(vendor_name: str):
    init_db()

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            vendor_name,
            agreed_price,
            max_annual_increase,
            renewal_date,
            notice_days,
            price_clause,
            created_at
        FROM contracts
        WHERE LOWER(TRIM(vendor_name)) = LOWER(TRIM(?))
        ORDER BY id DESC
        LIMIT 1
    """, (vendor_name,))

    row = cur.fetchone()
    conn.close()

    return dict(row) if row else None
def count_invoices(vendor_name=None) -> int:
    init_db()

    conn = get_connection()
    cur = conn.cursor()

    if vendor_name:
        cur.execute("""
            SELECT COUNT(*)
            FROM invoices
            WHERE LOWER(TRIM(vendor_name)) = LOWER(TRIM(?))
        """, (vendor_name,))
    else:
        cur.execute("SELECT COUNT(*) FROM invoices")

    count = cur.fetchone()[0]

    conn.close()
    return count

# IMPORTANT:
# Initialize the database whenever this module is imported.
init_db()
def list_invoices() -> list:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            vendor_name,
            invoice_number,
            total,
            currency,
            raw_data,
            created_at
        FROM invoices
        ORDER BY id DESC
    """)

    rows = cur.fetchall()
    conn.close()

    invoices = []

    for row in rows:
        invoice = dict(row)

        # Prefer the original parsed invoice structure
        if invoice.get("raw_data"):
            try:
                parsed = json.loads(invoice["raw_data"])
                if isinstance(parsed, dict):
                    invoices.append(parsed)
                    continue
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback if raw_data cannot be decoded
        invoices.append(invoice)

    return invoices
def list_invoices() -> list:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
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

    cur.execute("""
        SELECT
            vendor_name,
            invoice_number,
            total,
            currency,
            raw_data,
            created_at
        FROM invoices
        ORDER BY id DESC
    """)

    rows = cur.fetchall()
    conn.close()

    invoices = []

    for row in rows:
        try:
            data = json.loads(row["raw_data"])
        except (json.JSONDecodeError, TypeError):
            data = {}

        # Make sure reconcile_bank() gets the exact fields it expects
        data["vendor_name"] = (
            data.get("vendor_name")
            or row["vendor_name"]
            or "Unknown"
        )

        data["invoice_number"] = (
            data.get("invoice_number")
            or data.get("invoice", {}).get("number")
            or row["invoice_number"]
            or ""
        )

        data["total_amount"] = (
            data.get("total_amount")
            or data.get("amounts", {}).get("total")
            or row["total"]
            or 0.0
        )

        data["currency"] = data.get("currency") or row["currency"] or "USD"

        invoices.append(data)

    return invoices