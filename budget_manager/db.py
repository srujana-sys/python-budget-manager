"""
Simple SQLite-backed database layer for the budget manager.
Uses built-in sqlite3 (no external dependencies).
"""

import sqlite3
from contextlib import closing
from datetime import datetime
from typing import Optional, List, Dict, Tuple


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL, -- ISO YYYY-MM-DD
    amount REAL NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
    category_id INTEGER,
    description TEXT,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE SET NULL
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    conn = connect(path)
    with closing(conn):
        conn.executescript(SCHEMA)
        conn.commit()


# Category helpers
def add_category(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO categories(name) VALUES(?)", (name.strip(),))
        conn.commit()
    except sqlite3.IntegrityError:
        # Category exists: fall through to fetch id
        pass
    row = cur.execute("SELECT id FROM categories WHERE name = ?", (name.strip(),)).fetchone()
    return row["id"]


def get_categories(conn: sqlite3.Connection) -> List[Tuple[int, str]]:
    cur = conn.cursor()
    rows = cur.execute("SELECT id, name FROM categories ORDER BY name").fetchall()
    return [(r["id"], r["name"]) for r in rows]


# Transactions
def add_transaction(
    conn: sqlite3.Connection,
    date: str,
    amount: float,
    ttype: str,
    category: Optional[str] = None,
    description: Optional[str] = None,
) -> int:
    # Validate date
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("date must be in YYYY-MM-DD format")

    if ttype not in ("income", "expense"):
        raise ValueError("type must be 'income' or 'expense'")

    category_id = None
    if category:
        category_id = add_category(conn, category)

    cur = conn.cursor()
    cur.execute(
        "INSERT INTO transactions(date, amount, type, category_id, description) VALUES(?,?,?,?,?)",
        (date, amount, ttype, category_id, description),
    )
    conn.commit()
    return cur.lastrowid


def list_transactions(conn: sqlite3.Connection, limit: Optional[int] = None) -> List[Dict]:
    q = """
    SELECT t.id, t.date, t.amount, t.type, c.name as category, t.description
    FROM transactions t
    LEFT JOIN categories c ON t.category_id = c.id
    ORDER BY date DESC, id DESC
    """
    if limit:
        q += " LIMIT ?"
        rows = conn.execute(q, (limit,)).fetchall()
    else:
        rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]


def get_balance(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT SUM(CASE WHEN type = 'income' THEN amount WHEN type = 'expense' THEN -amount END) as bal FROM transactions"
    ).fetchone()
    return float(row["bal"] or 0.0)


def monthly_report(conn: sqlite3.Connection, year: int, month: int) -> Dict:
    # Return totals by category and overall
    start = f"{year:04d}-{month:02d}-01"
    # compute end as next month start (simple)
    if month == 12:
        end = f"{year+1:04d}-01-01"
    else:
        end = f"{year:04d}-{month+1:02d}-01"

    cur = conn.cursor()
    total_row = cur.execute(
        """
        SELECT
          SUM(CASE WHEN type='income' THEN amount ELSE 0 END) as income,
          SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) as expense
        FROM transactions
        WHERE date >= ? AND date < ?
        """,
        (start, end),
    ).fetchone()
    income = float(total_row["income"] or 0.0)
    expense = float(total_row["expense"] or 0.0)

    cat_rows = cur.execute(
        """
        SELECT c.name as category,
          SUM(CASE WHEN t.type='income' THEN t.amount WHEN t.type='expense' THEN -t.amount END) as net
        FROM transactions t
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE t.date >= ? AND t.date < ?
        GROUP BY c.name
        ORDER BY net DESC
        """,
        (start, end),
    ).fetchall()

    categories = [{ "category": r["category"] or "Uncategorized", "net": float(r["net"] or 0.0)} for r in cat_rows]

    return {"year": year, "month": month, "income": income, "expense": expense, "net": income - expense, "by_category": categories}

