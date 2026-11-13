# AI-Powered Personal Finance and Subscription Tracker: Expanded Project Plan

Legend: **[Built]** is in the current MVP, **[Planned]** is proposed for the final submission, **[Future]** is future scope.

## 1. Expanded project idea

People now pay for food, travel, shopping and bills through UPI, cards and wallets, and also hold many auto-renewing subscriptions (streaming, cloud storage, gym, apps). Existing trackers only *record* transactions. The user still has to categorise, spot forgotten subscriptions and judge their own spending.

This project is an **intelligent financial assistant** that turns raw transactions into decisions:

1. **Capture**: manual entry, CSV/bank-statement import [Built]; SMS/e-mail receipt parsing and bank APIs [Future].
2. **Understand**: ML categorisation of each transaction [Built], learning from user corrections [Built].
3. **Detect**: recurring-payment and subscription discovery with renewal prediction [Built]; price-hike and duplicate-subscription detection [Planned].
4. **Analyse**: monthly/yearly reports, trends, savings rate [Built]; month-over-month comparison and category forecasting [Planned].
5. **Advise**: rule-based recommendations and outlier alerts [Built]; personalised savings goals and "what-if" simulation [Planned].
6. **Notify**: in-dashboard alerts [Built]; e-mail/push reminders before renewal [Planned].

**Unique selling points**
- Subscription-first view: "you pay X per year for things you may not use".
- Explainable AI: each alert says *why* (e.g. "typical Food charge is 12, this was 400").
- Learns from the user: corrections retrain the categoriser for that user.
- Privacy-friendly: runs locally, with no bank credentials needed (CSV import).

## 2. Stakeholders and user roles

| Role | Who | Permissions | Status |
|---|---|---|---|
| **Guest** | Visitor, not signed in | View landing/login page; register; log in. No data access. | [Built] |
| **Registered User** | Individual managing own money | Full CRUD on own transactions; CSV import; correct categories; set budgets; view dashboard, subscriptions, anomalies, recommendations; export reports; delete own account and data. | [Built], except export and account deletion [Planned] |
| **Family / Shared member** | Spouse, parent, flatmate | Join a shared household; add and view shared transactions; shared budgets. Cannot see another member's private transactions. | [Planned] |
| **Advisor (read-only)** | Financial advisor or mentor the user invites | Time-limited read-only access to summaries and reports the user chooses to share. Cannot edit or see raw descriptions unless granted. | [Future] |
| **Administrator** | Project maintainer | Manage user accounts (disable/reset), view system health and anonymised usage stats, manage the category list and ML seed data, retrain/roll back the global model. **No access to users' transaction details.** | [Planned] |
| **System (automated actors)** | Scheduler, ML service, notifier | Nightly subscription re-detection, renewal reminders, anomaly scans, model retraining. | [Planned] |

### Role-permission matrix

| Capability | Guest | User | Family member | Advisor | Admin |
|---|:-:|:-:|:-:|:-:|:-:|
| Register / log in | ✔ | ✔ | ✔ | ✔ | ✔ |
| Add / edit / delete own transactions | | ✔ | ✔ | | |
| Import CSV | | ✔ | ✔ | | |
| View own dashboard and insights | | ✔ | ✔ | | |
| View shared household data | | | ✔ | | |
| View shared report (read-only) | | | | ✔ | |
| Set budgets | | ✔ | ✔ (shared) | | |
| Manage users / system settings | | | | | ✔ |
| View other users' transactions | | | | | ✘ never |

Implementation note: add a `role` column to `users` (`user`, `admin`), a `households` / `household_members` table for sharing, and a `@role_required` decorator next to `login_required`.

## 3. Functional requirements

**Account and security**: registration, login, logout, password hashing [Built]; password reset, optional 2FA, session timeout [Planned].

**Transactions**: add, delete, recategorise [Built]; edit amount/date, notes, tags, split transactions, multi-currency [Planned].

**AI/ML**
- Categorisation: TF-IDF char n-grams + logistic regression, with a confidence threshold [Built]. Improvement: show confidence and ask the user to confirm low-confidence items [Planned].
- Subscription detection: group by merchant, check interval and amount consistency [Built]. Improvement: detect free-trial-to-paid conversion and price hikes [Planned].
- Anomaly detection: robust median/MAD z-score per category [Built]. Improvement: Isolation Forest across amount, time and merchant [Planned].
- Forecasting: next-month spend per category via moving average / regression [Future: LSTM or Prophet].
- Natural-language assistant ("how much did I spend on food last month?") [Future].

**Autopay / recurring payments**: rules auto-record transactions on due dates, with pause and delete [Built]; real bank mandates (UPI AutoPay / e-NACH) [Future].

**Budgets and goals**: per-category monthly budgets with 80%/100% alerts [Built]; savings goals with progress tracking [Planned]; smart budget suggestions from history [Future].

**Reports**: monthly/yearly summaries and charts [Built]; PDF/CSV export [Planned].

**Notifications**: dashboard alerts [Built]; e-mail/push reminders 7/3/1 days before renewal [Planned].

## 4. Non-functional requirements

- **Security**: hashed passwords [Built]; CSRF tokens, rate-limited login, HTTPS in deployment [Planned]. Per-user data isolation is enforced in every query and covered by tests [Built].
- **Privacy**: collect the minimum data; support data export and deletion; no raw data shared with third parties.
- **Performance**: dashboard under 2 s for 10k transactions; categoriser retrain in under 1 s per user at current scale.
- **Usability**: responsive layout, keyboard-accessible forms, ARIA labels.
- **Reliability and maintainability**: modular `app/ml` package, automated tests [Built].

## 5. System architecture

```
Browser (HTML/JS, Chart.js)
        │  JSON over HTTPS
Flask app (routes, auth, validation)
   ├── preprocess.py     clean + parse + de-duplicate
   ├── categorizer.py    TF-IDF + logistic regression
   ├── subscriptions.py  recurrence detection
   └── analysis.py       summaries, anomalies, budgets, tips
        │
SQLite (users, transactions, budgets) → PostgreSQL for deployment [Planned]
```

Workflow: User data → Preprocessing → ML categorisation → Subscription detection → Spending analysis → AI recommendations → Dashboard and notifications.

## 6. Database design

- `users(id, username, password_hash)`: [Built]. Planned additions: `email`, `role`, `created_at`, `is_active`.
- `transactions(id, user_id, date, description, amount, type, category, confirmed)`: [Built]. `confirmed=1` marks user-verified labels used for retraining.
- `budgets(user_id, category, monthly_limit)`: [Built].
- Planned: `households`, `household_members(role)`, `goals`, `notifications(user_id, kind, message, sent_at, read)`, `audit_log`.

## 7. Key use cases

1. **Import and auto-categorise**: user uploads a bank CSV, the system cleans it, categorises it and shows the dashboard.
2. **Correct a category**: user changes "Zorblax" from Other to Education, and later similar items are categorised correctly.
3. **Discover a forgotten subscription**: the system flags a monthly 199 charge and shows the yearly cost and next renewal.
4. **Overspending alert**: Food budget crosses 100% and a warning is shown with a recommendation.
5. **Unusual charge**: a 400 charge in a category that normally runs around 12 is flagged for review.
6. **Admin maintenance**: an admin disables an abusive account and retrains the global model without seeing anyone's transactions.

## 8. Evaluation plan (for the report)

- **Categoriser**: accuracy, precision/recall and F1 per category on a labelled dataset (hold-out / 5-fold cross-validation); compare against a Naive Bayes baseline. *Not yet measured. The current seed set is too small for meaningful numbers.*
- **Subscription detection**: precision and recall on synthetic and real statements with known subscriptions.
- **Anomaly detection**: injected-outlier recall and false-alert rate.
- **Usability**: a short survey (SUS) with 10 or more users.
- **Baseline comparison**: time to categorise a month of transactions manually versus with the system.

## 9. Development roadmap

| Phase | Deliverables |
|---|---|
| 1. MVP (done) | Auth, CRUD, CSV import, categorisation, subscriptions, anomalies, budgets, dashboard, tests |
| 2. Roles and security | `role` column, admin panel, password reset, CSRF, login rate limit |
| 3. Sharing | Households, shared budgets, advisor read-only links |
| 4. Notifications and reports | E-mail reminders, scheduler, PDF/CSV export, goals |
| 5. ML upgrade | Larger dataset, model comparison, Isolation Forest, forecasting |
| 6. Final | Evaluation, deployment (PostgreSQL, HTTPS), report and demo |

## 10. Risks and limitations

- Small seed training data limits categorisation accuracy until real data is collected.
- Recurrence detection needs 2 or more charges, so first-time subscriptions are not found until they repeat.
- Financial data is sensitive, so production use needs encryption, backups and a privacy policy.
- Recommendations are rule-based guidance, not professional financial advice.
