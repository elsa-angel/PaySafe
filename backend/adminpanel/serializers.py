from django.contrib.auth import get_user_model
from rest_framework import serializers

from payments.models import FraudStatus, Transaction

User = get_user_model()


def display_name(user):
    return user.first_name or user.email.split('@')[0] or user.username


class AdminTransactionListSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    sender_email = serializers.CharField(source='user.email', read_only=True)
    payment_method_label = serializers.CharField(source='get_payment_method_display', read_only=True)
    status_label = serializers.CharField(source='get_status_display', read_only=True)
    fraud_analysis = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = (
            'transaction_id', 'created_at', 'sender_name', 'sender_email',
            'recipient_name', 'recipient_email', 'amount', 'currency',
            'payment_method', 'payment_method_label', 'status', 'status_label', 'fraud_analysis',
        )
        read_only_fields = fields

    def get_sender_name(self, txn):
        return display_name(txn.user)

    def get_fraud_analysis(self, txn):
        """Only present when a real fraud screening result exists (none until the model is integrated)."""
        if txn.fraud_status == FraudStatus.NOT_CHECKED:
            return None
        return txn.get_fraud_status_display()


class AdminTransactionDetailSerializer(AdminTransactionListSerializer):
    """Administrative detail. No coordinates, credentials or model internals."""

    sender_id = serializers.IntegerField(source='user_id', read_only=True)
    payment_method_detail = serializers.CharField(read_only=True)
    device_type_label = serializers.CharField(source='get_device_type_display', read_only=True)
    location_status_label = serializers.CharField(source='get_location_status_display', read_only=True)

    class Meta(AdminTransactionListSerializer.Meta):
        fields = AdminTransactionListSerializer.Meta.fields + (
            'sender_id', 'description', 'payment_method_detail', 'failure_reason',
            'device_type_label', 'browser', 'operating_system', 'location_status_label', 'updated_at',
        )
        read_only_fields = fields


class AdminUserListSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    transaction_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = User
        fields = ('id', 'full_name', 'email', 'date_joined', 'last_login', 'is_active', 'transaction_count')
        read_only_fields = fields

    def get_full_name(self, user):
        return display_name(user)


class AdminUserDetailSerializer(AdminUserListSerializer):
    completed_transaction_count = serializers.IntegerField(read_only=True)
    total_completed_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    last_transaction_at = serializers.DateTimeField(read_only=True)

    class Meta(AdminUserListSerializer.Meta):
        fields = AdminUserListSerializer.Meta.fields + (
            'completed_transaction_count', 'total_completed_amount', 'last_transaction_at',
        )
        read_only_fields = fields
