from django.contrib.auth import get_user_model
from rest_framework import serializers

from payments.fraud.presentation import describe, get_analysis, short_label
from payments.workflow import describe_verification
from payments.models import Transaction

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
        """Short model-outcome label, or None when the transaction was never analysed."""
        return short_label(get_analysis(txn))


class AdminTransactionDetailSerializer(AdminTransactionListSerializer):
    """Administrative detail. No coordinates, credentials or model internals."""

    sender_id = serializers.IntegerField(source='user_id', read_only=True)
    payment_method_detail = serializers.CharField(read_only=True)
    device_type_label = serializers.CharField(source='get_device_type_display', read_only=True)
    location_status_label = serializers.CharField(source='get_location_status_display', read_only=True)
    fraud_analysis_detail = serializers.SerializerMethodField()
    verification = serializers.SerializerMethodField()
    workflow_events = serializers.SerializerMethodField()

    class Meta(AdminTransactionListSerializer.Meta):
        fields = AdminTransactionListSerializer.Meta.fields + (
            'fraud_analysis_detail', 'verification', 'workflow_events',
            'sender_id', 'description', 'payment_method_detail', 'failure_reason',
            'device_type_label', 'browser', 'operating_system', 'location_status_label', 'updated_at',
        )
        read_only_fields = fields

    def get_verification(self, txn):
        """Workflow state for administrators. No code, hash or salt exists in this representation."""
        return describe_verification(txn)

    def get_workflow_events(self, txn):
        return [{'event_type': e.event_type, 'label': e.get_event_type_display(), 'detail': e.detail,
                 'created_at': e.created_at} for e in txn.workflow_events.all()]

    def get_fraud_analysis_detail(self, txn):
        """Full model outcome for administrators: prediction, model version and the threshold used."""
        analysis = get_analysis(txn)
        data = describe(analysis)
        data['failure_category'] = analysis.failure_category or None if analysis else None
        data['threshold_used'] = analysis.threshold_used if analysis else None
        data['threshold_source'] = (analysis.threshold_source or None) if analysis else None
        return data


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
