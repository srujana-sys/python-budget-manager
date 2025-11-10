"""
Command-line interface for the budget manager.
"""

import argparse
import os
import sqlite3
from typing import Optional

from . import db

def _get_conn_or_exit(dbpath: str) -> sqlite3.Connection:
    if not os.path.exists(dbpath):
        print(f"Database file '{dbpath}' does not exist. Run 'init' first to create it.")
        raise SystemExit(1)
    return db.connect(dbpath)

def cmd_init(args):
    dbpath = args.db
    os.makedirs(os.path.dirname(dbpath) or ".", exist_ok=True)
    db.init_db(dbpath)
    print(f"Initialized database at {dbpath}")

def cmd_add_category(args):
    conn = _get_conn_or_exit(args.db)
    cid = db.add_category(conn, args.name)
    print(f"Category '{args.name}' -> id {cid}")

def cmd_add_transaction(args):
    conn = _get_conn_or_exit(args.db)
    try:
        tid = db.add_transaction(conn, date=args.date, amount=args.amount, ttype=args.type, category=args.category, description=args.description)
    except ValueError as e:
        print("Error:", e)
        raise SystemExit(1)
    print(f"Added transaction {tid}")

def cmd_list(args):
    conn = _get_conn_or_exit(args.db)
    rows = db.list_transactions(conn, limit=args.limit)
    if not rows:
        print("No transactions found.")
        return
    for r in rows:
        cat = r["category"] or "Uncategorized"
        print(f"{r['id']:4d} | {r['date']} | {r['type']:7s} | {r['amount']:10.2f} | {cat:15s} | {r['description'] or ''}")

def cmd_balance(args):
    conn = _get_conn_or_exit(args.db)
    bal = db.get_balance(conn)
    print(f"Balance: {bal:.2f}")

def cmd_report(args):
    conn = _get_conn_or_exit(args.db)
    report = db.monthly_report(conn, args.year, args.month)
    print(f"Report for {report['year']}-{report['month']:02d}")
    print(f"Income:  {report['income']:.2f}")
    print(f"Expense: {report['expense']:.2f}")
    print(f"Net:     {report['net']:.2f}")
    print()
    print("By category:")
    for c in report["by_category"]:
        print(f"  {c['category'] or 'Uncategorized':20s} {c['net']:10.2f}")

def build_parser():
    parser = argparse.ArgumentParser(prog="budget-manager")
    parser.add_argument("--db", default="data/budget.db", help="Path to sqlite database file")

    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="Initialize database")
    p_init.set_defaults(func=cmd_init)

    p_add_cat = sub.add_parser("add-category", help="Add a category")
    p_add_cat.add_argument("name")
    p_add_cat.set_defaults(func=cmd_add_category)

    p_add = sub.add_parser("add", help="Add a transaction")
    p_add.add_argument("--type", choices=["income", "expense"], required=True)
    p_add.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_add.add_argument("--amount", type=float, required=True)
    p_add.add_argument("--category", help="Category name")
    p_add.add_argument("--description", help="Optional description")
    p_add.set_defaults(func=cmd_add_transaction)

    p_list = sub.add_parser("list", help="List transactions")
    p_list.add_argument("--limit", type=int, help="Limit number of rows")
    p_list.set_defaults(func=cmd_list)

    p_bal = sub.add_parser("balance", help="Show current balance")
    p_bal.set_defaults(func=cmd_balance)

    p_rep = sub.add_parser("report", help="Monthly report")
    p_rep.add_argument("--year", type=int, required=True)
    p_rep.add_argument("--month", type=int, required=True, choices=list(range(1, 13)))
    p_rep.set_defaults(func=cmd_report)

    return parser

def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except SystemExit:
        raise
    except Exception as e:
        print("Unhandled error:", e)
        raise

