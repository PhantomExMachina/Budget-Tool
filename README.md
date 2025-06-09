# Budget Tool

A simple command-line budgeting tool for tracking income and expenses. Data is stored locally using SQLite so it can be easily ported to Android or iOS later. The CLI now supports multiple users, budget goals, CSV export and optional Firebase authentication.

## Features
- Create budget categories (e.g. Groceries, Rent, Fun)
- Add income and expense entries associated with categories
- View balances per category
- View total income, total expenses and net balance
- View available funds across bank, crypto and stock accounts
- Forecast account balances for future months
- Manage multiple users and set per-category spending goals
- Export transactions to CSV
- Automatically detect recurring expenses from uploaded statements
- Store recurring charges as monthly expenses
- Login via Firebase ID token
  - Authentication is disabled by default; set `AUTH_ENABLED=1` to enable

## Usage
Run the CLI with Python 3:

```bash
python3 budget_tool.py init                            # initialize the database
AUTH_ENABLED=1 python3 budget_tool.py login <id_token> # verify Firebase token
python3 budget_tool.py add-user <name>                 # add a user
python3 budget_tool.py add-category <name>             # add a category
python3 budget_tool.py add-income <category> <amount> [--user NAME] [-d DESC]
python3 budget_tool.py add-expense <category> <amount> [--user NAME] [-d DESC]
python3 budget_tool.py set-goal <category> <amount> [--user NAME]
python3 budget_tool.py export-csv [--output FILE] [--user NAME]
python3 budget_tool.py balance <category> [--user NAME]
python3 budget_tool.py totals [--user NAME] [--months N] # show overall totals and forecast
python3 budget_tool.py list                            # list all categories
python3 budget_tool.py delete-category <name>          # remove a category
python3 budget_tool.py set-account <name> <balance> [--payment AMT]
                             [--type TYPE] [--apr RATE]
                             [--escrow AMT] [--insurance AMT]
                             [--tax AMT]
python3 budget_tool.py delete-account <name>           # remove an account
python3 budget_tool.py list-accounts                   # show account balances
python3 budget_tool.py forecast [--months N]           # forecast account balances
python3 budget_tool.py bank-balance <months>           # forecast bank balance
python3 budget_tool.py history [CATEGORY] [--user NAME] [--limit N]
python3 budget_tool.py --db mydata.db totals          # use a custom database
```

By default the database file `budget.db` is created in the same directory as the
script. Set the `--db` option or the `BUDGET_DB` environment variable to use a
different location.

## Running tests

Install the required packages before running the tests:

```bash
pip install -r requirements.txt
pytest
```

If you prefer a separate development environment, a `requirements-dev.txt`
file is provided with the packages needed for testing:

```bash
pip install -r requirements-dev.txt
```

## Web Interface

A simple Flask web interface is provided for easier interaction. Install the requirements and run:

```bash
pip install -r requirements.txt
python3 webapp.py
```

This launches a local web server at `http://127.0.0.1:5000/` where you can view totals, manage categories, track account balances, set spending goals, export transactions to CSV and add income or expenses using a basic Bootstrap UI.
The interface also provides an **Auto Scan** page for uploading CSV statements and identifying recurring expenses. After scanning, you can choose which charges to store as monthly expenses via check boxes before saving.
Use the **Auto Scan** link in the navigation bar to access this page.

### Environment Variables

The web server reads `FLASK_SECRET_KEY` to sign session cookies. Set this to a
secure random value when deploying. Firebase authentication also requires the
`FIREBASE_CREDENTIALS` variable pointing to your service account JSON file and
`AUTH_ENABLED=1` to enable login.

### Supported statement formats

Uploaded CSV statements may be comma or tab delimited. The parser will automatically detect the delimiter. Dates may be in ISO format (`YYYY-MM-DD`), compact form (`YYYYMMDD`) or U.S. style (`MM/DD/YYYY`). The first row should include `Date`, `Description` and `Amount` columns. If a column containing the word `Category` (e.g. `Transaction Category`) is present it will be used to assign categories when saving monthly expenses.
