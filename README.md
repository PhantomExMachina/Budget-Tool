# Budget Tool

A simple command-line budgeting tool for tracking income and expenses. Data is stored locally using SQLite so it can be easily ported to Android or iOS later.

## Features
- Create budget categories (e.g. Groceries, Rent, Fun)
- Add income and expense entries associated with categories
- View balances per category
- View total income, total expenses and net balance

## Usage
Run the CLI with Python 3:

```bash
python3 budget_tool.py init                 # initialize the database
python3 budget_tool.py add-category <name>  # add a category
python3 budget_tool.py add-income <category> <amount> [-d DESCRIPTION]
python3 budget_tool.py add-expense <category> <amount> [-d DESCRIPTION]
python3 budget_tool.py balance <category>   # show category balance
python3 budget_tool.py totals               # show overall totals
python3 budget_tool.py list                 # list all categories
python3 budget_tool.py history [CATEGORY] [--limit N]  # show recent transactions
```

The database file `budget.db` is created in the same directory as the script.

## Running tests

Install `pytest` and run the test suite:

```bash
pip install pytest
pytest
```
