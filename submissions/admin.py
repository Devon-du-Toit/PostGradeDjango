from django.contrib import admin

from submissions.models import SubmissionAudit


@admin.register(SubmissionAudit)
class SubmissionAuditAdmin(admin.ModelAdmin):
    list_display = ("submission", "actor", "timestamp", "previous_status", "new_status")
    readonly_fields = tuple(field.name for field in SubmissionAudit._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
