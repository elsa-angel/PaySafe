# PaySafe backend (Django + Django REST Framework)

## Setup

```bash
python -m venv env && source env/bin/activate
pip install -r requirements.txt
cp .env.example .env            # optional in development
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

## Fraud monitoring and the future XGBoost model

The XGBoost model is **not integrated**. The dashboards report that status and show no fraud counts,
probabilities or model metrics.

* `adminpanel/monitoring/rules.py`: preliminary, documented rule-based indicators (not fraud detection).
* `adminpanel/monitoring/model_status.py`: the single place that reports model/label availability. Replace
  it when the model is integrated.
* `payments/fraud/`: real behavioural history features and a `FeatureMapper` interface for the exact
  IEEE-CIS feature mapping, to be implemented from the trained model's artifacts.

## Tests

```bash
python manage.py test
```
