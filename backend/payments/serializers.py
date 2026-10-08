import re
from decimal import Decimal

from rest_framework import serializers

from .models import (
    Bank,
    CardNetwork,
    PaymentMethod,
    Transaction,
    WalletProvider,
)

UPI_ID_PATTERN = re.compile(r'^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31}$')
DESCRIPTION_MAX_LENGTH = Transaction._meta.get_field('description').max_length

# payment method -> (serializer field holding its detail, model choices or None, label)
METHOD_DETAIL_FIELDS = {
    PaymentMethod.CARD: ('card_network', CardNetwork, 'card type'),
    PaymentMethod.UPI: ('upi_id', None, 'UPI ID'),
    PaymentMethod.BANK_TRANSFER: ('bank_name', Bank, 'bank'),
    PaymentMethod.WALLET: ('wallet_provider', WalletProvider, 'wallet provider'),
}
ALL_DETAIL_FIELDS = [field for field, _, _ in METHOD_DETAIL_FIELDS.values()]


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
    card_network = serializers.CharField(required=False, allow_blank=True, max_length=20)
    upi_id = serializers.CharField(required=False, allow_blank=True, max_length=100)
    bank_name = serializers.CharField(required=False, allow_blank=True, max_length=20)
    wallet_provider = serializers.CharField(required=False, allow_blank=True, max_length=20)
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

    def validate(self, attrs):
        method = attrs['payment_method']
        field, choices, label = METHOD_DETAIL_FIELDS[method]
        value = (attrs.get(field) or '').strip()

        if not value:
            raise serializers.ValidationError({field: [f'Select or enter the {label}.' if choices else f'Enter the {label}.']})
        if choices is not None and value not in choices.values:
            raise serializers.ValidationError({field: [f'Choose a valid {label}.']})
        if method == PaymentMethod.UPI and not UPI_ID_PATTERN.match(value):
            raise serializers.ValidationError({field: ['Enter a valid UPI ID, like name@bank.']})

        # Keep only the detail relevant to the chosen method; discard the rest.
        for other in ALL_DETAIL_FIELDS:
            attrs[other] = ''
        attrs[field] = value.lower() if method == PaymentMethod.UPI else value
        return attrs


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
