# AI-Powered Personal Finance & Subscription Tracker

CSE final-year project. Flask + SQLite backend, scikit-learn for the AI/ML parts, Chart.js dashboard.

| Proposal item | Implementation |
|---|---|
| Data collection / preprocessing | Manual entry and CSV import (`app/ml/preprocess.py`): date normalisation, cleaning, de-duplication |
| AI expense categorisation | TF-IDF char n-grams + logistic regression (`app/ml/categorizer.py`); retrains on categories you correct |
| Subscription detection | Groups repeated charges, checks interval and amount consistency, predicts the next renewal (`app/ml/subscriptions.py`) |
| Spending analysis & reports | Monthly and yearly summaries, category breakdown, trend chart |
| Recommendations & anomalies | Rule-based tips; robust median/MAD outlier detection per category (`app/ml/analysis.py`) |
| Budgets & notifications | Per-category monthly budgets, over-budget alerts and renewals due within 7 days (dashboard alerts) |
| Autopay | Recurring rules (weekly/monthly/quarterly/yearly) record transactions automatically when due, catch up after downtime, can be paused or deleted (`app/ml/recurring.py`). They record payments only and do not move real money. |
| Authentication | Registration/login with hashed passwords and per-user data isolation |

## Run
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python run.py          # http://localhost:5000
python -m pytest
```
Public pages: `/`, `/features`, `/how-it-works`, `/about`, `/faq`, `/contact`, `/privacy`. The UI uses a sage/forest palette inspired by spade.com (layout and style only; all copy and branding are this project's own).

Set `SECRET_KEY` in the environment for stable sessions across restarts.

CSV format: `date,description,amount[,type]`. Without a `type` column, negative amounts are expenses.

## Not yet done (proposal "future scope")
Cash-flow prediction, natural-language assistant, bank/payment integrations, email/push notifications. Notifications are in-dashboard only.
