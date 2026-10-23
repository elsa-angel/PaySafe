# PaySafe backend (Django + Django REST Framework)

## Setup

> Python 3.11+ is required (pandas 3; numpy 2.4). The model pickle loads only with the pinned `xgboost` and `scikit-learn` in `requirements.txt`. A Python 3.10 environment cannot run it.

```bash
python3.12 -m venv env312 && source env312/bin/activate
pip install -r requirements.txt
cp .env.example .env            # set FRAUD_INR_PER_USD here to enable fraud predictions
python manage.py migrate
python manage.py runserver      # http://127.0.0.1:8000
```

## Creating the administrator

Administrators are Django superusers. There is no public admin signup and no default admin account.

```bash
python manage.py createsuperuser
```

**Enter an email address when prompted.** Everyone, including administrators, signs in on the normal
PaySafe login page using their *email*; the backend recognises superusers and the app sends them to the
admin dashboard. Django's own admin site stays available at `/admin/`.

## API overview

| Area | Endpoints |
|---|---|
| Auth | `POST /api/auth/signup/`, `login/`, `logout/`, `change-password/`, `GET/PATCH /api/auth/user/` |
| Payments (own data only) | `GET/POST /api/payments/`, `GET /api/payments/<id>/` |
| Admin (superusers only) | `GET /api/admin/overview/`, `fraud-statistics/`, `users/`, `users/<id>/`, `PATCH users/<id>/status/`, `users/<id>/transactions/`, `transactions/`, `transactions/<id>/`, `reports/<transactions\|users\|activity\|fraud-monitoring>/` |

Admin endpoints enforce `is_superuser` on the server for every request. Reports return JSON for the
in-app preview, or a CSV download with `?export=csv`. Filters: `date_from`, `date_to` (YYYY-MM-DD),
`status`, `payment_method`, `account_status`, `group_by` (`day|week|month`).

**Report periods.** `date_from` / `date_to` are inclusive calendar days, read in the time zone named by the optional `tz` query
parameter (an IANA name such as `Asia/Kolkata`; UTC when omitted; unknown names are a 400). The admin app sends the browser's zone,
so filters and chart buckets use the same days the admin sees. A day is `[00:00:00 of date_from, 00:00:00 of the day after date_to)`.
Every report section (summary, breakdowns, fraud/verification/OTP figures, series, CSV) is scoped by the creation time of the
transaction, and a period without records returns `empty_message` plus real zeros.

**Recipient e-mail** is optional on `POST /api/payments/` (omitted, `""` and `null` all mean "not provided"; a non-empty value must be
a valid address). It is never used for codes or alerts. Without one the fraud analysis is recorded as unavailable
(`MISSING_EMAIL_FEATURES`): the payment stays pending, no code is sent and it can only be cancelled.

## Payment method details (simulated payments)

No real payment gateway is used and no money moves. The form collects the details below; the API validates
them and then **discards the sensitive parts**: only the masked or non-sensitive values are stored.

| Method | Collected and validated | Stored |
|---|---|---|
| Card | cardholder name, network, card number (length + Luhn), expiry (MM/YY, not expired), CVV (3 digits; 3-4 for "Other") | network, masked `**** 1234` |
| UPI | UPI app, UPI ID (name@bank) | UPI app, UPI ID |
| Bank transfer | bank, account holder, account number (9-18 digits) + confirmation, IFSC (format + matches the bank) | bank, IFSC, masked `**** 1234` |
| Wallet | provider, identifier type (mobile or wallet ID), identifier | provider, identifier type, masked identifier |

Never collected: PINs, passwords, OTPs. Never stored: full card number, CVV, expiry, cardholder or account
holder name, full account number, full wallet identifier. Logging never includes request bodies, and the
payment view marks these parameters as sensitive for error reports. Test card: `4111 1111 1111 1111`.

Validation lives in `payments/validators.py`. Older transactions (made before these fields existed) keep
working and display as before.

## Metric definitions

* **Counts** include every transaction in the selected period.
* **Amounts** (totals, averages, minimum, maximum) include **completed** transactions only.
* **Registered users** exclude administrator accounts.

## Fraud response: XGBoost risk -> OTP / alert (Phase 3)

After the PENDING transaction is created, the XGBoost pipeline (`fraud_model/aligned/`) scores it and the
backend decides what happens next. **The payment is processed only after the user verifies it.**

| Model result | Backend risk category | What happens |
|---|---|---|
| probability < `HIGH_RISK_THRESHOLD` | LOW | A one-time code is e-mailed to the account's registered address. |
| probability >= `HIGH_RISK_THRESHOLD` | HIGH | A high-risk alert is e-mailed; the user must choose **Continue** (then a code is e-mailed) or **Terminate**. |
| no valid prediction | UNAVAILABLE | The payment **stays PENDING and cannot proceed**; the user can cancel it. Never treated as low risk, never bypassed. |

Three statuses are kept apart: `Transaction.status` (the payment), `FraudAnalysis.status` (model outcome) and
`PaymentVerification.status` (this workflow). `FraudWorkflowEvent` is an append-only audit trail; `OneTimeCode`
stores only a salted keyed hash (HMAC-SHA256 bound to the transaction and user), attempts and expiry.

Endpoints (all POST, signed-in owner only, throttled): `/api/payments/<id>/continue/`, `/cancel/`,
`/verify-otp/` (`{"code": "123456"}`), `/resend-otp/`. `GET /api/payments/<id>/` and the create response carry
`fraud_analysis` and `verification` (the next action and what is allowed); the client never supplies risk, threshold or status.

OTP rules: cryptographically random (`secrets`), expiry, max attempts per code, max resends, resend cooldown,
per-user hourly cap, previous code replaced on resend, single use, invalidated on cancel / details change / window
expiry, and bound to one transaction and user. A payment whose details change after verification started is
cancelled and must be re-submitted for a new fraud evaluation. Verification windows are enforced on access;
run `python manage.py expire_verifications` periodically (cron) to close abandoned ones.

**Configuration** (see `.env.example`): `FRAUD_INR_PER_USD` (required), `HIGH_RISK_THRESHOLD` (default: the Phase 1
validation threshold), `OTP_*`, `VERIFICATION_WINDOW_SECONDS`, and the e-mail settings (`EMAIL_BACKEND`, `EMAIL_HOST`,
`EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL`). E-mail goes through Django's
e-mail framework; the default backend is SMTP. For local development use the console backend (it prints each message,
including the code, to the server console). If the mail backend rejects a message the API says so (HTTP 503 or
`delivery: FAILED`) and never claims it was sent.

**Configuration precedence.** (1) a real environment variable with a non-empty value, (2) `backend/.env`, (3) the default in
`config/settings.py`. An *empty* inherited variable (for example a stray `export FRAUD_INR_PER_USD=` in a shell profile or IDE run
configuration) is treated as unset, so it cannot hide the `.env` value. `.env` is never overridden over a deployment variable. If
`FRAUD_INR_PER_USD` is missing, non-numeric, zero, negative or out of range, it is ignored, every fraud analysis is reported as
\"unavailable\" and no payment proceeds; `python manage.py check` names the problem (never the value). `HIGH_RISK_THRESHOLD` is optional:
empty means \"use the validation-chosen threshold from `model_metadata.json`\" (about 0.1055), never \"low risk\".

**E-mail.** `.env.example` has two options. *Development:* the console backend prints messages, including the one-time code, to the
server terminal (never for production). *Gmail SMTP:* turn on 2-Step Verification for the account, create an App Password at
https://myaccount.google.com/apppasswords, set `EMAIL_HOST_USER` and `DEFAULT_FROM_EMAIL` to that address and put the 16 characters
(no spaces) in `EMAIL_HOST_PASSWORD` in your local `.env` only. Check it with `python manage.py check` (flags missing credentials and a
sender that differs from the Gmail account), then make a payment with a low-risk card and confirm the code arrives at the signed-in
user's registered address. There is no silent fallback to the console backend; a failed send is reported as failed.

**Currency.** PaySafe stores, accepts and displays INR only. The model was trained on USD-scale amounts, so the INR amount
is divided by `FRAUD_INR_PER_USD` once, inside `payments/fraud/mapper.py`, when the model input row is built. The stored
`Transaction.amount` is never changed.

**What can be scored.** Card payments only (training data), in INR, from a desktop or mobile device with a known browser
and OS, where both e-mail providers appeared in training (e.g. gmail.com, yahoo.com, hotmail.com, outlook.com). Everything
else is "prediction unavailable" and is therefore held. See `PHASE3_NOTES.md` for the consequences.

Code: `payments/workflow.py` (state machine), `otp.py`, `notifications.py`, `payments/fraud/` (model service, mapper, analysis),
`adminpanel/monitoring/` (model status, prediction and fraud-response statistics).

## Tests

```bash
python manage.py test
```
