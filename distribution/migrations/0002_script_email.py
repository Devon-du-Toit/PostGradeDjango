from django.db import migrations, models
import django.db.models.deletion


def retire_result_deliveries(apps, schema_editor):
    Email = apps.get_model("distribution", "ScriptEmail")
    Email.objects.exclude(status="sent").update(
        status="superseded", lease_expires_at=None
    )


class Migration(migrations.Migration):
    dependencies = [
        ("distribution", "0001_initial"),
        ("submissions", "0012_bubble_recognition_method_and_evidence"),
    ]
    operations = [
        migrations.RenameModel("ResultEmail", "ScriptEmail"),
        migrations.RunPython(retire_result_deliveries, migrations.RunPython.noop),
        migrations.RemoveField("scriptemail", "result"),
        migrations.RemoveField("scriptemail", "result_version"),
        migrations.AddField(
            "scriptemail",
            "submission",
            models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="emails",
                to="submissions.submission",
            ),
        ),
        migrations.AddField(
            "scriptemail",
            "enrollment",
            models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="script_emails",
                to="students.enrollment",
            ),
        ),
        migrations.AddField(
            "scriptemail", "submission_version", models.PositiveIntegerField(default=0)
        ),
        migrations.AddField(
            "scriptemail",
            "attachment",
            models.FileField(blank=True, upload_to="script-emails/%Y/%m/%d/"),
        ),
        migrations.AddField(
            "scriptemail",
            "attachment_filename",
            models.CharField(blank=True, max_length=255),
        ),
        migrations.RemoveIndex("scriptemail", "result_email_claim_idx"),
        migrations.AddIndex(
            "scriptemail",
            models.Index(fields=["status", "run_after"], name="script_email_claim_idx"),
        ),
        migrations.AlterField(
            "scriptemail",
            "failure_reason",
            models.CharField(
                blank=True,
                max_length=30,
                choices=[
                    ("missing_recipient", "Student has no email address"),
                    ("recipient_refused", "Mail server refused the recipient"),
                    ("provider_error", "Mail server error"),
                    ("attachment_unavailable", "Script attachment unavailable"),
                    (
                        "delivery_unknown",
                        "Worker stopped while sending; delivery unknown",
                    ),
                ],
            ),
        ),
    ]
