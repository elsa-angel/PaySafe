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
    recipient_email = models.EmailField()

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
