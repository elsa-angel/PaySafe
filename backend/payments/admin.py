from django.contrib import admin

from .models import Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    """Read-only view for inspecting records; transactions are not edited by hand."""

    list_display = ('transaction_id', 'user', 'recipient_email', 'amount', 'payment_method', 'status', 'created_at')
    list_filter = ('status', 'payment_method', 'fraud_status')
    search_fields = ('transaction_id', 'recipient_email', 'user__email')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
