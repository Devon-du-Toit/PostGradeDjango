from django.contrib import admin

from distribution.models import ScriptEmail


@admin.register(ScriptEmail)
class ScriptEmailAdmin(admin.ModelAdmin):
    list_display = [
        "idempotency_key",
        "recipient",
        "status",
        "failure_reason",
        "attempts",
        "sent_at",
        "created_at",
    ]
    list_filter = [
        "status",
        "failure_reason",
    ]

    # Delivery records are an audit trail.
    def has_change_permission(self, request, obj=None):
        return False
