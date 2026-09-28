"""
database.py - SQLite storage: invoice history, vendor contracts, vendor memory.

Changes vs. old version:
- DB path is absolute (next to this file, or AUDIT_DB env var) so it does not
  depend on where you launch from.
- No init at import time; schema is created lazily on first connection.
- New: get_history (3-month trend), invoice_exists (duplicates), contracts table
  (agreed price, max increase %, renewal date, notice window, clause text).
"""
import json
import os
import sqlite3
from contextlib import closing

DB_FILE = os.environ.get(
    "AUDIT_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "audit_records.db")
)
_ready = False


def _init(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS invoices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vendor_name TEXT,
        invoice_number TEXT,
        total_amount REAL,
        currency TEXT,
        raw_data TEXT,
        uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.execute("""
    CREATE TABLE IF NOT EXISTS contracts (
        vendor_key TEXT PRIMARY KEY,
        vendor_name TEXT,
        agreed_amount REAL,
        max_increase_pct REAL,
        renewal_date TEXT,
        notice_days INTEGER,
        clause TEXT
    )""")
    conn.commit()


def _conn():
    global _ready
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    if not _ready:
        _init(conn)
        _ready = True
    return conn


def init_db():
    with closing(_conn()):
        pass


# ---------------- invoices ----------------
def get_history(vendor_name: str, limit: int = 3) -> list:
    """Most recent invoices for a vendor, newest first (parsed dicts)."""
    if not vendor_name:
        return []
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT raw_data FROM invoices WHERE LOWER(vendor_name)=LOWER(?) ORDER BY id DESC LIMIT ?",
            (vendor_name, limit),
        ).fetchall()
    return [json.loads(r["raw_data"]) for r in rows]


def get_latest_invoice_for_vendor(vendor_name: str):
    """Kept for backwards compatibility."""
    hist = get_history(vendor_name, 1)
    return hist[0] if hist else None


def invoice_exists(vendor_name: str, invoice_number: str) -> bool:
    if not vendor_name or not invoice_number:
        return False
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT 1 FROM invoices WHERE LOWER(vendor_name)=LOWER(?) AND invoice_number=? LIMIT 1",
            (vendor_name, invoice_number),
        ).fetchone()
    return row is not None


def count_invoices(vendor_name: str) -> int:
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM invoices WHERE LOWER(vendor_name)=LOWER(?)", (vendor_name,)
        ).fetchone()
    return row["n"]


def save_invoice(parsed_invoice: dict) -> int:
    """Saves the parsed invoice for future comparisons. Returns the row id."""
    with closing(_conn()) as conn, conn:
        cur = conn.execute(
            """INSERT INTO invoices (vendor_name, invoice_number, total_amount, currency, raw_data)
               VALUES (?, ?, ?, ?, ?)""",
            (
                parsed_invoice["vendor"]["name"],
                parsed_invoice["invoice"]["number"],
                parsed_invoice["amounts"]["total"],
                parsed_invoice["invoice"]["currency"],
                json.dumps(parsed_invoice),
            ),
        )
        return cur.lastrowid


def list_invoices(limit: int = 200) -> list:
    """Flat list used for bank reconciliation."""
    with closing(_conn()) as conn:
        rows = conn.execute(
            """SELECT vendor_name, invoice_number, total_amount, currency, uploaded_at
               FROM invoices ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------- contracts / vendor memory ----------------
def save_contract(vendor_name, agreed_amount=None, max_increase_pct=None,
                  renewal_date=None, notice_days=None, clause=None):
    with closing(_conn()) as conn, conn:
        conn.execute(
            """INSERT INTO contracts (vendor_key, vendor_name, agreed_amount, max_increase_pct,
                                      renewal_date, notice_days, clause)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(vendor_key) DO UPDATE SET
                 vendor_name=excluded.vendor_name, agreed_amount=excluded.agreed_amount,
                 max_increase_pct=excluded.max_increase_pct, renewal_date=excluded.renewal_date,
                 notice_days=excluded.notice_days, clause=excluded.clause""",
            (vendor_name.strip().lower(), vendor_name.strip(), agreed_amount, max_increase_pct,
             renewal_date, notice_days, clause),
        )


def get_contract(vendor_name: str):
    if not vendor_name:
        return None
    with closing(_conn()) as conn:
        row = conn.execute(
            "SELECT * FROM contracts WHERE vendor_key=?", (vendor_name.strip().lower(),)
        ).fetchone()
    return dict(row) if row else None


def list_contracts() -> list:
    with closing(_conn()) as conn:
        rows = conn.execute(
            "SELECT * FROM contracts ORDER BY (renewal_date IS NULL), renewal_date"
        ).fetchall()
    return [dict(r) for r in rows]
