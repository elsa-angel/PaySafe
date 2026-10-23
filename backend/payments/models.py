import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

DEFAULT_CURRENCY = 'INR'


def generate_transaction_id():
    """Backend-generated public transaction reference, e.g. PS-9F3A0C1B7D42."""
    return f'PS-{secrets.token_hex(6).upper()}'


class PaymentMethod(models.TextChoices):
    CARD = 'CARD', 'Card'
    UPI = 'UPI', 'UPI'
    BANK_TRANSFER = 'BANK_TRANSFER', 'Bank Transfer'
    WALLET = 'WALLET', 'Wallet'


class CardNetwork(models.TextChoices):
    VISA = 'VISA', 'Visa'
    MASTERCARD = 'MASTERCARD', 'Mastercard'
    RUPAY = 'RUPAY', 'RuPay'
    OTHER = 'OTHER', 'Other'


class Bank(models.TextChoices):
    SBI = 'SBI', 'State Bank of India'
    HDFC = 'HDFC', 'HDFC Bank'
    ICICI = 'ICICI', 'ICICI Bank'
    AXIS = 'AXIS', 'Axis Bank'
    KOTAK = 'KOTAK', 'Kotak Mahindra Bank'
    PNB = 'PNB', 'Punjab National Bank'
    BOB = 'BOB', 'Bank of Baroda'
    CANARA = 'CANARA', 'Canara Bank'
    OTHER = 'OTHER', 'Other'


class WalletProvider(models.TextChoices):
    PAYTM = 'PAYTM', 'Paytm'
    PHONEPE = 'PHONEPE', 'PhonePe'
    GOOGLE_PAY = 'GOOGLE_PAY', 'Google Pay'
    AMAZON_PAY = 'AMAZON_PAY', 'Amazon Pay'
    OTHER = 'OTHER', 'Other'


class UpiProvider(models.TextChoices):
    GOOGLE_PAY = 'GOOGLE_PAY', 'Google Pay'
    PHONEPE = 'PHONEPE', 'PhonePe'
    PAYTM = 'PAYTM', 'Paytm'
    BHIM = 'BHIM', 'BHIM'
    AMAZON_PAY = 'AMAZON_PAY', 'Amazon Pay'
    OTHER = 'OTHER', 'Other'


class WalletIdentifierType(models.TextChoices):
    MOBILE = 'MOBILE', 'Mobile number'
    WALLET_ID = 'WALLET_ID', 'Wallet ID'


class TransactionStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending'
    COMPLETED = 'COMPLETED', 'Completed'
    FAILED = 'FAILED', 'Failed'
    CANCELLED = 'CANCELLED', 'Cancelled'


class FraudStatus(models.TextChoices):
    # Only NOT_CHECKED is assigned today. The other values are reserved for the
    # future XGBoost stage, which is the only code that may set them.
    NOT_CHECKED = 'NOT_CHECKED', 'Not checked'
    LEGITIMATE = 'LEGITIMATE', 'Legitimate'
    SUSPICIOUS = 'SUSPICIOUS', 'Suspicious'
    FRAUDULENT = 'FRAUDULENT', 'Fraudulent'


class FraudAnalysisStatus(models.TextChoices):
    # EVALUATED   a genuine model prediction exists.
    # UNAVAILABLE the transaction is outside what the model can evaluate (or the server is not set up for it).
    # ERROR       the model should have run but a technical failure prevented a prediction.
    EVALUATED = 'EVALUATED', 'Evaluated'
    UNAVAILABLE = 'UNAVAILABLE', 'Prediction unavailable'
    ERROR = 'ERROR', 'Analysis error'


class LocationStatus(models.TextChoices):
    PROVIDED = 'PROVIDED', 'Provided'
    DENIED = 'DENIED', 'Permission denied'
    UNAVAILABLE = 'UNAVAILABLE', 'Unavailable'


class DeviceType(models.TextChoices):
    MOBILE = 'MOBILE', 'Mobile'
    TABLET = 'TABLET', 'Tablet'
    DESKTOP = 'DESKTOP', 'Desktop'
    UNKNOWN = 'UNKNOWN', 'Unknown'


class Transaction(models.Model):
    """A simulated payment made by an authenticated PaySafe user.

    Holds only non-sensitive payment details: never card numbers, CVV, PINs,
    passwords or OTPs.
    """

    # --- identification ---
    transaction_id = models.CharField(
        max_length=20, unique=True, editable=False, default=generate_transaction_id
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='transactions'
    )
    idempotency_key = models.CharField(max_length=64, null=True, blank=True, editable=False)
    timestamp = models.DateTimeField(default=timezone.now, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # --- recipient ---
    recipient_name = models.CharField(max_length=120)
    # Optional. Blank means "not provided": it is never used to deliver codes or alerts (those go to the sender's
    # registered address) and the fraud model reports the payment as unavailable rather than guessing a domain.
    recipient_email = models.EmailField(blank=True, default='')

    # --- payment ---
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default=DEFAULT_CURRENCY)
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    description = models.CharField(max_length=255, blank=True)

    # --- method-specific, non-sensitive details ---
    card_network = models.CharField(max_length=20, choices=CardNetwork.choices, blank=True)
    upi_id = models.CharField(max_length=100, blank=True)
    bank_name = models.CharField(max_length=20, choices=Bank.choices, blank=True)
    wallet_provider = models.CharField(max_length=20, choices=WalletProvider.choices, blank=True)
    upi_provider = models.CharField(max_length=20, choices=UpiProvider.choices, blank=True)
    ifsc_code = models.CharField(max_length=11, blank=True)  # public branch code, not an account number
    wallet_identifier_type = models.CharField(max_length=12, choices=WalletIdentifierType.choices, blank=True)
    # Display-only masked value ("**** 4242" for a card or bank account, a masked wallet
    # mobile/ID). Full card numbers, CVVs, expiry dates and account numbers are validated
    # and then discarded; they are never stored.
    masked_reference = models.CharField(max_length=32, blank=True)

    # --- location (optional; null when permission denied/unavailable) ---
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_status = models.CharField(
        max_length=12, choices=LocationStatus.choices, default=LocationStatus.UNAVAILABLE
    )

    # --- device (derived server-side from the request) ---
    device_type = models.CharField(max_length=10, choices=DeviceType.choices, default=DeviceType.UNKNOWN)
    browser = models.CharField(max_length=60, blank=True)
    operating_system = models.CharField(max_length=60, blank=True)

    # --- processing status ---
    status = models.CharField(
        max_length=10, choices=TransactionStatus.choices, default=TransactionStatus.PENDING
    )
    failure_reason = models.CharField(max_length=255, blank=True)

    # --- fraud screening (filled by the future XGBoost stage; never faked) ---
    fraud_status = models.CharField(
        max_length=12, choices=FraudStatus.choices, default=FraudStatus.NOT_CHECKED
    )
    fraud_probability = models.FloatField(null=True, blank=True)
    model_version = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [
            models.Index(fields=['user', '-created_at'], name='txn_user_created_idx'),
            models.Index(fields=['user', 'status', '-timestamp'], name='txn_user_status_time_idx'),
            models.Index(fields=['user', 'recipient_email'], name='txn_user_recipient_idx'),
            models.Index(fields=['user', 'payment_method'], name='txn_user_method_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=Decimal('0')), name='txn_amount_positive'
            ),
            models.CheckConstraint(
                condition=(
                    Q(payment_method='CARD', card_network__gt='')
                    | Q(payment_method='UPI', upi_id__gt='')
                    | Q(payment_method='BANK_TRANSFER', bank_name__gt='')
                    | Q(payment_method='WALLET', wallet_provider__gt='')
                ),
                name='txn_method_details_present',
            ),
            models.CheckConstraint(
                condition=(
                    Q(latitude__isnull=True)
                    | Q(latitude__gte=Decimal('-90'), latitude__lte=Decimal('90'))
                ),
                name='txn_latitude_range',
            ),
            models.CheckConstraint(
                condition=(
                    Q(longitude__isnull=True)
                    | Q(longitude__gte=Decimal('-180'), longitude__lte=Decimal('180'))
                ),
                name='txn_longitude_range',
            ),
            models.CheckConstraint(
                condition=(
                    Q(fraud_probability__isnull=True)
                    | Q(fraud_probability__gte=0, fraud_probability__lte=1)
                ),
                name='txn_fraud_probability_range',
            ),
            models.UniqueConstraint(
                fields=['user', 'idempotency_key'],
                condition=Q(idempotency_key__isnull=False),
                name='txn_user_idempotency_unique',
            ),
        ]

    def __str__(self):
        return f'{self.transaction_id} ({self.amount} {self.currency}, {self.status})'

    @property
    def payment_method_detail(self):
        """Human-readable, non-sensitive method detail, e.g. 'Visa · **** 4242'.

        Older records have no masked reference or provider, so they fall back to
        the original single value (e.g. just 'Visa').
        """
        method = self.payment_method
        if method == PaymentMethod.CARD:
            parts = [self.get_card_network_display(), self.masked_reference]
        elif method == PaymentMethod.UPI:
            parts = [self.upi_id, self.get_upi_provider_display()]
        elif method == PaymentMethod.BANK_TRANSFER:
            parts = [self.get_bank_name_display(), self.masked_reference, f'IFSC {self.ifsc_code}' if self.ifsc_code else '']
        else:
            parts = [self.get_wallet_provider_display(), self.masked_reference]
        return ' · '.join(part for part in parts if part)


class FraudAnalysis(models.Model):
    """The fraud-model outcome for one transaction. Kept apart from ``Transaction.status``: a predicted
    fraud class never changes whether the payment completed, and a prediction is not confirmed fraud.

    Transactions created before the model was integrated simply have no row here; they are reported
    as "not evaluated" and are never back-filled.

    The legacy ``Transaction.fraud_status`` / ``fraud_probability`` / ``model_version`` columns are left
    untouched and unused so that existing data and migrations stay valid; this table is the single
    source of truth for model output.
    """

    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name='fraud_analysis')
    status = models.CharField(max_length=12, choices=FraudAnalysisStatus.choices)
    # Only for EVALUATED rows. 1 = the model's fraud class, 0 = its genuine class (a prediction, not a fact).
    predicted_class = models.PositiveSmallIntegerField(null=True, blank=True)
    fraud_probability = models.FloatField(null=True, blank=True)
    threshold_used = models.FloatField(null=True, blank=True)
    threshold_source = models.CharField(max_length=24, blank=True)
    model_version = models.CharField(max_length=50, blank=True)
    # Fixed safe category (see payments.fraud.errors); never raw exception text.
    failure_category = models.CharField(max_length=40, blank=True)
    evaluated_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-evaluated_at', '-id']
        verbose_name_plural = 'fraud analyses'
        indexes = [
            models.Index(fields=['status', '-evaluated_at'], name='fa_status_time_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(status='EVALUATED', predicted_class__in=[0, 1], fraud_probability__gte=0,
                      fraud_probability__lte=1, threshold_used__isnull=False, failure_category='')
                    | Q(status__in=['UNAVAILABLE', 'ERROR'], predicted_class__isnull=True,
                        fraud_probability__isnull=True, threshold_used__isnull=True)
                ),
                name='fa_evaluated_has_prediction_only',
            ),
        ]

    @property
    def risk_category(self):
        """Backend-derived risk from the stored score and the threshold that was applied to it.
        HIGH when probability >= threshold, LOW when below, UNAVAILABLE when there is no valid
        prediction. Low is never a guarantee that a payment is genuine."""
        if self.status != FraudAnalysisStatus.EVALUATED or self.fraud_probability is None \
                or self.threshold_used is None:
            return RiskCategory.UNAVAILABLE
        return RiskCategory.HIGH if self.fraud_probability >= self.threshold_used else RiskCategory.LOW

    def __str__(self):
        return f'{self.transaction_id}: {self.status}'


# ============================================================================ Phase 3: fraud response
class RiskCategory(models.TextChoices):
    LOW = 'LOW', 'Low risk'
    HIGH = 'HIGH', 'High risk'
    UNAVAILABLE = 'UNAVAILABLE', 'Prediction unavailable'


class VerificationStatus(models.TextChoices):
    """OTP / fraud-response status. Deliberately separate from Transaction.status (the payment) and
    from FraudAnalysis.status (the model outcome)."""

    AWAITING_USER_DECISION = 'AWAITING_USER_DECISION', 'Awaiting your decision'   # high risk: continue or cancel
    AWAITING_OTP = 'AWAITING_OTP', 'Awaiting one-time code'
    VERIFIED = 'VERIFIED', 'Verified'
    CANCELLED = 'CANCELLED', 'Cancelled by user'
    FAILED = 'FAILED', 'Verification failed'                  # code limits exhausted
    EXPIRED = 'EXPIRED', 'Verification expired'
    INVALIDATED = 'INVALIDATED', 'Invalidated (details changed)'
    UNAVAILABLE = 'UNAVAILABLE', 'Fraud verification unavailable'


ACTIVE_VERIFICATION_STATUSES = (
    VerificationStatus.AWAITING_USER_DECISION, VerificationStatus.AWAITING_OTP, VerificationStatus.UNAVAILABLE,
)


class AlertStatus(models.TextChoices):
    NOT_APPLICABLE = 'NOT_APPLICABLE', 'Not applicable'
    SENT = 'SENT', 'Sent'
    FAILED = 'FAILED', 'Delivery failed'


class PaymentVerification(models.Model):
    """The fraud-response workflow state of one transaction (one row per transaction)."""

    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name='verification')
    status = models.CharField(max_length=24, choices=VerificationStatus.choices)
    # Snapshot taken from the stored FraudAnalysis when the workflow started. Set by the backend only.
    risk_category = models.CharField(max_length=12, choices=RiskCategory.choices)
    # Safe category explaining an UNAVAILABLE outcome (payments.fraud.errors / workflow); never raw errors.
    reason = models.CharField(max_length=40, blank=True)
    alert_status = models.CharField(max_length=14, choices=AlertStatus.choices, default=AlertStatus.NOT_APPLICABLE)
    # Hash of the payment details the verification is bound to; a mismatch invalidates it.
    details_fingerprint = models.CharField(max_length=64)
    continued_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['status', 'risk_category'], name='pv_status_risk_idx')]

    def __str__(self):
        return f'{self.transaction_id}: {self.status}'


class OneTimeCodeStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    USED = 'USED', 'Used'
    REPLACED = 'REPLACED', 'Replaced by a newer code'
    EXPIRED = 'EXPIRED', 'Expired'
    LOCKED = 'LOCKED', 'Locked (too many attempts)'
    INVALIDATED = 'INVALIDATED', 'Invalidated'


class OneTimeCode(models.Model):
    """One issued code. Only a salted keyed hash is stored, never the code itself."""

    verification = models.ForeignKey(PaymentVerification, on_delete=models.CASCADE, related_name='codes')
    code_hash = models.CharField(max_length=64, editable=False)
    salt = models.CharField(max_length=32, editable=False)
    status = models.CharField(max_length=12, choices=OneTimeCodeStatus.choices, default=OneTimeCodeStatus.ACTIVE)
    attempts = models.PositiveSmallIntegerField(default=0)
    email_delivered = models.BooleanField(default=False)   # True only if the mail backend accepted the message
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['verification'], condition=Q(status='ACTIVE'),
                                    name='otp_one_active_per_verification'),
        ]


class WorkflowEvent(models.TextChoices):
    FRAUD_EVALUATED = 'FRAUD_EVALUATED', 'Fraud evaluation completed'
    VERIFICATION_UNAVAILABLE = 'VERIFICATION_UNAVAILABLE', 'Fraud verification unavailable'
    HIGH_RISK_ALERT_SENT = 'HIGH_RISK_ALERT_SENT', 'High-risk alert e-mailed'
    HIGH_RISK_ALERT_FAILED = 'HIGH_RISK_ALERT_FAILED', 'High-risk alert e-mail failed'
    USER_CHOSE_CONTINUE = 'USER_CHOSE_CONTINUE', 'User chose to continue'
    OTP_REQUESTED = 'OTP_REQUESTED', 'One-time code requested'
    OTP_SENT = 'OTP_SENT', 'One-time code e-mailed'
    OTP_SEND_FAILED = 'OTP_SEND_FAILED', 'One-time code e-mail failed'
    OTP_VERIFIED = 'OTP_VERIFIED', 'One-time code verified'
    OTP_FAILED = 'OTP_FAILED', 'Incorrect one-time code'
    OTP_EXPIRED = 'OTP_EXPIRED', 'One-time code expired'
    OTP_LOCKED = 'OTP_LOCKED', 'One-time code locked'
    USER_CANCELLED = 'USER_CANCELLED', 'User cancelled the transaction'
    DETAILS_CHANGED = 'DETAILS_CHANGED', 'Payment details changed; verification invalidated'
    VERIFICATION_EXPIRED = 'VERIFICATION_EXPIRED', 'Verification window expired'
    VERIFICATION_FAILED = 'VERIFICATION_FAILED', 'Verification failed (limits reached)'
    TRANSACTION_FINALIZED = 'TRANSACTION_FINALIZED', 'Transaction reached its final status'


class FraudWorkflowEvent(models.Model):
    """Append-only audit trail. `detail` is a short, safe string: never OTPs, passwords or card data."""

    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='workflow_events')
    event_type = models.CharField(max_length=30, choices=WorkflowEvent.choices)
    detail = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['event_type', 'created_at'], name='fwe_type_time_idx'),
            models.Index(fields=['transaction', 'created_at'], name='fwe_txn_time_idx'),
        ]
