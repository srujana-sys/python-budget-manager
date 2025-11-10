import os
import tempfile
import sqlite3

from budget_manager import db

def test_add_category_and_transactions():
    # Use a temporary file database
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        db.init_db(path)
        conn = db.connect(path)

        # Add category
        cat_id = db.add_category(conn, "TestCat")
        assert isinstance(cat_id, int)

        # Add income and expense
        t1 = db.add_transaction(conn, date="2025-11-01", amount=100.0, ttype="income", category="TestCat", description="Salary")
        t2 = db.add_transaction(conn, date="2025-11-02", amount=25.5, ttype="expense", category="TestCat", description="Lunch")

        # List transactions
        rows = db.list_transactions(conn)
        assert len(rows) >= 2

        # Balance
        bal = db.get_balance(conn)
        assert abs(bal - (100.0 - 25.5)) < 1e-6

        # Monthly report
        report = db.monthly_report(conn, 2025, 11)
        assert report["income"] >= 100.0
        assert report["expense"] >= 25.5
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
