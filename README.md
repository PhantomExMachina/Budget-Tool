# Budget Tool

A simple command-line budgeting tool for tracking income and expenses. Data is stored locally using SQLite so it can be easily ported to Android or iOS later. The CLI now supports multiple users, budget goals and CSV export.

## Features
- Create budget categories (e.g. Groceries, Rent, Fun)
- Add income and expense entries associated with categories
- View balances per category
- View total income, total expenses and net balance
- Manage multiple users and set per-category spending goals
- Export transactions to CSV

## Usage
Run the CLI with Python 3:

```bash
python3 budget_tool.py init                            # initialize the database
python3 budget_tool.py add-user <name>                 # add a user
python3 budget_tool.py add-category <name>             # add a category
python3 budget_tool.py add-income <category> <amount> [--user NAME] [-d DESC]
python3 budget_tool.py add-expense <category> <amount> [--user NAME] [-d DESC]
python3 budget_tool.py set-goal <category> <amount> [--user NAME]
python3 budget_tool.py export-csv [--output FILE] [--user NAME]
python3 budget_tool.py balance <category> [--user NAME]
python3 budget_tool.py totals [--user NAME]            # show overall totals
python3 budget_tool.py list                            # list all categories
python3 budget_tool.py history [CATEGORY] [--user NAME] [--limit N]
python3 budget_tool.py --db mydata.db totals          # use a custom database
```

By default the database file `budget.db` is created in the same directory as the
script. Set the `--db` option or the `BUDGET_DB` environment variable to use a
different location.

## Running tests

Install `pytest` and run the test suite:

```bash
pip install pytest
pytest
```
