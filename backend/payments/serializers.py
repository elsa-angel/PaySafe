import re
from decimal import Decimal

from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework import serializers

from .models import PaymentMethod, Transaction
from .validators import validate_method_details

DESCRIPTION_MAX_LENGTH = Transaction._meta.get_field('description').max_length


PLAIN_DECIMAL_PATTERN = re.compile(r'^-?\d+(\.\d+)?$')


class PlainDecimalField(serializers.DecimalField):
    """DecimalField that only accepts plain decimal text (no 1e3, NaN, commas, spaces)."""

    def to_internal_value(self, data):
        if isinstance(data, str):
            data = data.strip()
            if not PLAIN_DECIMAL_PATTERN.match(data):
                self.fail('invalid')
        return super().to_internal_value(data)


class PaymentCreateSerializer(serializers.Serializer):
    """Everything the user types. Sender, ID, status, fraud and device fields are
    never accepted from the client: unknown keys are simply ignored."""

    amount = PlainDecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal('0.01'),
        error_messages={
            'invalid': 'Enter a valid amount.',
            'min_value': 'Amount must be greater than zero.',
            'max_digits': 'Amount is too large.',
            'max_whole_digits': 'Amount is too large.',
            'max_decimal_places': 'Amount can have at most 2 decimal places.',
            'required': 'Amount is required.',
            'null': 'Amount is required.',
        },
    )
    payment_method = serializers.ChoiceField(
        choices=PaymentMethod.choices,
        error_messages={'invalid_choice': 'Choose a valid payment method.', 'required': 'Choose a payment method.'},
    )
    # Method-specific input. Raw sensitive values (card number, CVV, expiry, account
    # numbers) are validated in validate() and never leave it.
    card_network = serializers.CharField(required=False, allow_blank=True, max_length=20)
    cardholder_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    card_number = serializers.CharField(required=False, allow_blank=True, max_length=32)
    card_expiry = serializers.CharField(required=False, allow_blank=True, max_length=12)
    card_cvv = serializers.CharField(required=False, allow_blank=True, max_length=8)
    upi_provider = serializers.CharField(required=False, allow_blank=True, max_length=20)
    upi_id = serializers.CharField(required=False, allow_blank=True, max_length=100)
    bank_name = serializers.CharField(required=False, allow_blank=True, max_length=20)
    account_holder_name = serializers.CharField(required=False, allow_blank=True, max_length=120)
    account_number = serializers.CharField(required=False, allow_blank=True, max_length=32)
    confirm_account_number = serializers.CharField(required=False, allow_blank=True, max_length=32)
    ifsc_code = serializers.CharField(required=False, allow_blank=True, max_length=20)
    wallet_provider = serializers.CharField(required=False, allow_blank=True, max_length=20)
    wallet_identifier_type = serializers.CharField(required=False, allow_blank=True, max_length=12)
    wallet_identifier = serializers.CharField(required=False, allow_blank=True, max_length=80)
    description = serializers.CharField(
        required=False, allow_blank=True, max_length=DESCRIPTION_MAX_LENGTH,
        error_messages={'max_length': f'Note can be at most {DESCRIPTION_MAX_LENGTH} characters.'},
    )
    recipient_name = serializers.CharField(max_length=120, error_messages={'required': 'Recipient name is required.', 'blank': 'Recipient name is required.'})
    recipient_email = serializers.EmailField(max_length=254, error_messages={'required': 'Recipient email is required.', 'blank': 'Recipient email is required.', 'invalid': 'Enter a valid email address.'})

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Amount must be greater than zero.')
        return value

    def validate_recipient_name(self, value):
        value = ' '.join(value.split())
        if len(value) < 2:
            raise serializers.ValidationError('Enter the recipient\'s full name.')
        return value

    def validate_recipient_email(self, value):
        return value.strip().lower()

    def validate_description(self, value):
        return ' '.join(value.split())

    @sensitive_variables()  # keep sensitive locals out of error-report tracebacks
    def validate(self, attrs):
        stored, errors = validate_method_details(attrs['payment_method'], attrs, timezone.now().date())
        if errors:
            raise serializers.ValidationError({field: [message] for field, message in errors.items()})
        # Return only what may be stored. Raw card/account details are dropped here.
        return {
            'amount': attrs['amount'],
            'payment_method': attrs['payment_method'],
            'description': attrs.get('description', ''),
            'recipient_name': attrs['recipient_name'],
            'recipient_email': attrs['recipient_email'],
            **stored,
        }


class TransactionListSerializer(serializers.ModelSerializer):
    payment_method_label = serializers.CharField(source='get_payment_method_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Transaction
        fields = (
            'transaction_id', 'recipient_name', 'amount', 'currency',
            'payment_method', 'payment_method_label', 'status', 'status_label', 'created_at',
        )
        read_only_fields = fields


class TransactionDetailSerializer(TransactionListSerializer):
    """Adds user-relevant detail. Deliberately omits location, device, fraud
    and other internal fields."""

    payment_method_detail = serializers.CharField(read_only=True)

    class Meta(TransactionListSerializer.Meta):
        fields = TransactionListSerializer.Meta.fields + (
            'recipient_email', 'payment_method_detail', 'description',
        )
        read_only_fields = fields
