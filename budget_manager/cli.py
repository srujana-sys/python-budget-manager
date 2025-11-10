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

    # Show any new unread alerts after adding an expense
    if args.type == "expense":
        unread_alerts = db.get_unread_alerts(conn)
        if unread_alerts:
            print("\n⚠️  SPENDING ALERTS:")
            for alert in unread_alerts:
                print(f"  [{alert['id']}] {alert['category']}: Spent ${alert['spent_amount']:.2f} exceeds {alert['period']} limit of ${alert['limit_amount']:.2f}")

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

def cmd_set_limit(args):
    conn = _get_conn_or_exit(args.db)
    try:
        db.set_category_limit(conn, args.category, args.amount, args.period)
        print(f"Set {args.period} spending limit for '{args.category}' to ${args.amount:.2f}")
    except ValueError as e:
        print("Error:", e)
        raise SystemExit(1)

def cmd_list_limits(args):
    conn = _get_conn_or_exit(args.db)
    limits = db.list_category_limits(conn)
    if not limits:
        print("No category limits set.")
        return
    print("Category spending limits:")
    for lim in limits:
        print(f"  {lim['category']:20s} | {lim['period']:10s} | ${lim['limit_amount']:.2f}")

def cmd_remove_limit(args):
    conn = _get_conn_or_exit(args.db)
    removed = db.remove_category_limit(conn, args.category)
    if removed:
        print(f"Removed spending limit for '{args.category}'")
    else:
        print(f"No limit found for category '{args.category}'")

def cmd_alerts(args):
    conn = _get_conn_or_exit(args.db)
    if args.unread_only:
        alerts = db.get_unread_alerts(conn)
    else:
        alerts = db.get_all_alerts(conn, limit=args.limit)

    if not alerts:
        print("No spending alerts." if not args.unread_only else "No unread spending alerts.")
        return

    print("Spending alerts:")
    for alert in alerts:
        status = "" if args.unread_only else ("[READ] " if alert.get("is_read") else "[UNREAD] ")
        print(f"  {status}[{alert['id']}] {alert['alert_date']} | {alert['category']:15s} | Spent ${alert['spent_amount']:.2f} > ${alert['limit_amount']:.2f} ({alert['period']})")

    if args.mark_read and alerts:
        db.mark_all_alerts_as_read(conn)
        print(f"\nMarked {len([a for a in alerts if not a.get('is_read', False)])} alerts as read.")

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

    p_set_limit = sub.add_parser("set-limit", help="Set spending limit for a category")
    p_set_limit.add_argument("--category", required=True, help="Category name")
    p_set_limit.add_argument("--amount", type=float, required=True, help="Limit amount")
    p_set_limit.add_argument("--period", choices=["daily", "weekly", "monthly", "yearly"], default="monthly", help="Time period for limit")
    p_set_limit.set_defaults(func=cmd_set_limit)

    p_list_limits = sub.add_parser("list-limits", help="List all category spending limits")
    p_list_limits.set_defaults(func=cmd_list_limits)

    p_remove_limit = sub.add_parser("remove-limit", help="Remove spending limit from a category")
    p_remove_limit.add_argument("--category", required=True, help="Category name")
    p_remove_limit.set_defaults(func=cmd_remove_limit)

    p_alerts = sub.add_parser("alerts", help="View spending alerts")
    p_alerts.add_argument("--limit", type=int, help="Limit number of alerts to show")
    p_alerts.add_argument("--unread-only", action="store_true", help="Show only unread alerts")
    p_alerts.add_argument("--mark-read", action="store_true", help="Mark all alerts as read")
    p_alerts.set_defaults(func=cmd_alerts)

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

