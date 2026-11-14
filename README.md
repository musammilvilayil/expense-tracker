# AI-Powered Personal Finance & Subscription Tracker

CSE final-year project. Flask + SQLite backend, scikit-learn for the AI/ML parts, Chart.js dashboard.

## Features

| Area | What it does |
|---|---|
| Statement import | Upload a **PDF bank statement** (including **password-protected** PDFs) or a CSV. A preview shows every row, its type, predicted category and whether it is a duplicate; nothing is saved until you confirm. Imports can be undone. (`app/ml/statement.py`, `app/imports.py`) |
| Duplicate detection | One-to-one matching on date + amount + type + merchant words. Uploading 3 months and later 6 months (containing those 3) adds only the new months; re-uploading a file adds nothing; manual entries and autopay rows are recognised too; genuine same-day repeats are kept. (`app/ml/dedupe.py`) |
| AI categorization | TF-IDF (word + character n-grams) + logistic regression, learns from your corrections. **Measured quality: see `docs/CATEGORIZER_EVALUATION.md`.** |
| Subscriptions | Finds recurring charges and predicts the next renewal. |
| Forecasting | Next-month spend, income and savings (total and per category) with a likely range, a 3-month outlook and this month's pace. (`app/ml/forecast.py`) |
| Budgets, anomalies, tips | Per-category budgets, unusual-spending detection, plain-language recommendations. |
| Autopay rules | Recurring rules that record transactions when due (they do not move real money). |
| Savings goals | Targets with contributions, required monthly amount, projected completion and status. |
| Reports | Monthly/yearly **PDF and CSV** downloads. |
| Reminders | In-app bell plus optional email digest (autopay due, renewals, budgets, goal deadlines, unusual charges). |
| Accounts | Email, password reset by email, login rate limiting, CSRF protection, change password, data export, account deletion. |
| Admin panel | User management (enable/disable, roles, send reset email), contact messages, audit log. Admins **cannot** see users' transactions. |
| Public site | Landing, Features, How it works, About, FAQ, Contact, Privacy. |

## Run (Windows, macOS, Linux)

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py                   # http://localhost:5000
```
If your PC blocks `pip.exe`, always use `python -m pip`. Run tests with `python -m pytest`.

Upgrading an existing install: `git pull`, then `python -m pip install -r requirements.txt` (new: pypdf, cryptography, reportlab). Your database is migrated automatically; no data is lost.

## Make yourself an admin

```bash
python manage.py make-admin <username>
```
or set `ADMIN_USERNAMES=alice,bob` in the environment (those users become admins when they sign up or sign in). Then open `/admin`.

## Reminder emails and password reset email

Without configuration, emails are written to `instance/outbox.log` (handy for testing the reset link). To send real email set:

`SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_FROM`, and `BASE_URL` (for example `https://tracker.example.com`, used to build reset links).

Send the daily reminder digest by scheduling this command (cron, or Windows Task Scheduler):

```bash
python manage.py send-reminders
```

## Other settings

- `SECRET_KEY`: keeps sessions valid across restarts (set it in production).
- `COOKIE_SECURE=1`: send session cookies only over HTTPS.
- Data lives in `instance/tracker.sqlite`.

## Evaluate the categorizer

```bash
python -m app.ml.evaluate     # rewrites docs/CATEGORIZER_EVALUATION.md
```

## CSV format

`date,description,amount[,type]`. Without `type`, negative amounts are expenses.

## Limits to know about

- The PDF reader is heuristic and works on text PDFs only (not scanned images). Always check the preview.
- Bank PDF passwords are used once and never stored; the app cannot recover or guess a forgotten password.
- Categorization accuracy on brand-new merchants is about 52% (measured on synthetic data); known merchants are near-perfect. See the evaluation report.
- Duplicate matching uses exact dates; a bank posting date that differs by a day from a manual entry will not match.
- Forecasts need several months of data; they are guidance, not financial advice.
- `run.py` uses Flask's development server. Use a production server and HTTPS for real deployment.
