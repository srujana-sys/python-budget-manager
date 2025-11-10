# Budget Manager

A simple command-line budget manager written in Python using SQLite.

Features:
- Add categories (e.g., Groceries, Rent, Salary)
- Record transactions (income or expense) with date, amount, category, description
- List transactions
- Show current balance
- Monthly summary report

Installation:
1. (Optional) Create a virtual environment:
   python -m venv .venv
   source .venv/bin/activate

2. Install dev/test dependencies:
   pip install -r requirements.txt

Usage:
- Initialize a database:
  python app.py init --db data/budget.db

- Add a category:
  python app.py add-category --db data/budget.db "Groceries"

- Add a transaction:
  python app.py add --db data/budget.db --type expense --date 2025-11-10 --amount 12.50 --category Groceries --description "Lunch"

- List transactions (most recent first):
  python app.py list --db data/budget.db --limit 50

- Show balance:
  python app.py balance --db data/budget.db

- Monthly report:
  python app.py report --db data/budget.db --year 2025 --month 11

Running tests:
  pytest -q

Notes:
- The app uses SQLite and will create the required tables when initializing the database.
- Dates are expected in YYYY-MM-DD format.