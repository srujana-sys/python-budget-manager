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

CREATE TABLE IF NOT EXISTS category_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL UNIQUE,
    limit_amount REAL NOT NULL,
    period TEXT NOT NULL CHECK(period IN ('daily', 'weekly', 'monthly', 'yearly')),
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS spending_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER NOT NULL,
    alert_date TEXT NOT NULL,
    spent_amount REAL NOT NULL,
    limit_amount REAL NOT NULL,
    period TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    FOREIGN KEY(category_id) REFERENCES categories(id) ON DELETE CASCADE
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
    transaction_id = cur.lastrowid

    # Check for spending alerts if this is an expense with a category
    if ttype == "expense" and category_id:
        check_and_create_alerts(conn, category_id, date)

    return transaction_id


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


# Category limits
def set_category_limit(
    conn: sqlite3.Connection,
    category_name: str,
    limit_amount: float,
    period: str = "monthly"
) -> None:
    """Set spending limit for a category."""
    if period not in ("daily", "weekly", "monthly", "yearly"):
        raise ValueError("period must be 'daily', 'weekly', 'monthly', or 'yearly'")

    if limit_amount <= 0:
        raise ValueError("limit_amount must be positive")

    category_id = add_category(conn, category_name)

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO category_limits(category_id, limit_amount, period)
        VALUES(?, ?, ?)
        ON CONFLICT(category_id) DO UPDATE SET
            limit_amount = excluded.limit_amount,
            period = excluded.period
        """,
        (category_id, limit_amount, period)
    )
    conn.commit()


def get_category_limit(conn: sqlite3.Connection, category_name: str) -> Optional[Dict]:
    """Get limit for a specific category."""
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT cl.limit_amount, cl.period
        FROM category_limits cl
        JOIN categories c ON cl.category_id = c.id
        WHERE c.name = ?
        """,
        (category_name,)
    ).fetchone()

    if row:
        return {"limit_amount": float(row["limit_amount"]), "period": row["period"]}
    return None


def list_category_limits(conn: sqlite3.Connection) -> List[Dict]:
    """List all category limits."""
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT c.name as category, cl.limit_amount, cl.period
        FROM category_limits cl
        JOIN categories c ON cl.category_id = c.id
        ORDER BY c.name
        """
    ).fetchall()

    return [{"category": r["category"], "limit_amount": float(r["limit_amount"]), "period": r["period"]} for r in rows]


def remove_category_limit(conn: sqlite3.Connection, category_name: str) -> bool:
    """Remove limit for a category. Returns True if limit existed and was removed."""
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM category_limits
        WHERE category_id = (SELECT id FROM categories WHERE name = ?)
        """,
        (category_name,)
    )
    conn.commit()
    return cur.rowcount > 0


# Spending alerts
def check_and_create_alerts(conn: sqlite3.Connection, category_id: int, transaction_date: str) -> None:
    """Check if spending in a category exceeds limit and create alert if needed."""
    from datetime import datetime, timedelta

    # Get the category limit
    cur = conn.cursor()
    limit_row = cur.execute(
        "SELECT limit_amount, period FROM category_limits WHERE category_id = ?",
        (category_id,)
    ).fetchone()

    if not limit_row:
        return  # No limit set for this category

    limit_amount = float(limit_row["limit_amount"])
    period = limit_row["period"]

    # Calculate the date range based on period
    trans_date = datetime.strptime(transaction_date, "%Y-%m-%d")

    if period == "daily":
        start_date = transaction_date
        end_date = (trans_date + timedelta(days=1)).strftime("%Y-%m-%d")
    elif period == "weekly":
        # Start of week (Monday)
        start_of_week = trans_date - timedelta(days=trans_date.weekday())
        start_date = start_of_week.strftime("%Y-%m-%d")
        end_date = (start_of_week + timedelta(days=7)).strftime("%Y-%m-%d")
    elif period == "monthly":
        start_date = f"{trans_date.year:04d}-{trans_date.month:02d}-01"
        if trans_date.month == 12:
            end_date = f"{trans_date.year+1:04d}-01-01"
        else:
            end_date = f"{trans_date.year:04d}-{trans_date.month+1:02d}-01"
    else:  # yearly
        start_date = f"{trans_date.year:04d}-01-01"
        end_date = f"{trans_date.year+1:04d}-01-01"

    # Calculate total spending in the period
    spent_row = cur.execute(
        """
        SELECT SUM(amount) as total
        FROM transactions
        WHERE category_id = ?
          AND type = 'expense'
          AND date >= ?
          AND date < ?
        """,
        (category_id, start_date, end_date)
    ).fetchone()

    spent_amount = float(spent_row["total"] or 0.0)

    # If spending exceeds limit, create an alert
    if spent_amount > limit_amount:
        # Check if an alert already exists for this period
        existing_alert = cur.execute(
            """
            SELECT id FROM spending_alerts
            WHERE category_id = ?
              AND alert_date >= ?
              AND alert_date < ?
            """,
            (category_id, start_date, end_date)
        ).fetchone()

        if not existing_alert:
            # Create new alert
            cur.execute(
                """
                INSERT INTO spending_alerts(category_id, alert_date, spent_amount, limit_amount, period, is_read)
                VALUES(?, ?, ?, ?, ?, 0)
                """,
                (category_id, transaction_date, spent_amount, limit_amount, period)
            )
            conn.commit()


def get_unread_alerts(conn: sqlite3.Connection) -> List[Dict]:
    """Get all unread spending alerts."""
    cur = conn.cursor()
    rows = cur.execute(
        """
        SELECT sa.id, c.name as category, sa.alert_date, sa.spent_amount, sa.limit_amount, sa.period
        FROM spending_alerts sa
        JOIN categories c ON sa.category_id = c.id
        WHERE sa.is_read = 0
        ORDER BY sa.alert_date DESC
        """
    ).fetchall()

    return [{
        "id": r["id"],
        "category": r["category"],
        "alert_date": r["alert_date"],
        "spent_amount": float(r["spent_amount"]),
        "limit_amount": float(r["limit_amount"]),
        "period": r["period"]
    } for r in rows]


def get_all_alerts(conn: sqlite3.Connection, limit: Optional[int] = None) -> List[Dict]:
    """Get all spending alerts (read and unread)."""
    cur = conn.cursor()
    query = """
        SELECT sa.id, c.name as category, sa.alert_date, sa.spent_amount, sa.limit_amount, sa.period, sa.is_read
        FROM spending_alerts sa
        JOIN categories c ON sa.category_id = c.id
        ORDER BY sa.alert_date DESC, sa.id DESC
    """

    if limit:
        query += " LIMIT ?"
        rows = cur.execute(query, (limit,)).fetchall()
    else:
        rows = cur.execute(query).fetchall()

    return [{
        "id": r["id"],
        "category": r["category"],
        "alert_date": r["alert_date"],
        "spent_amount": float(r["spent_amount"]),
        "limit_amount": float(r["limit_amount"]),
        "period": r["period"],
        "is_read": bool(r["is_read"])
    } for r in rows]


def mark_alert_as_read(conn: sqlite3.Connection, alert_id: int) -> bool:
    """Mark an alert as read. Returns True if alert existed and was marked."""
    cur = conn.cursor()
    cur.execute("UPDATE spending_alerts SET is_read = 1 WHERE id = ?", (alert_id,))
    conn.commit()
    return cur.rowcount > 0


def mark_all_alerts_as_read(conn: sqlite3.Connection) -> int:
    """Mark all alerts as read. Returns number of alerts marked."""
    cur = conn.cursor()
    cur.execute("UPDATE spending_alerts SET is_read = 1 WHERE is_read = 0")
    conn.commit()
    return cur.rowcount

