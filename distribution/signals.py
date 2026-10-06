from django.db.models.signals import post_delete, pre_delete
from django.dispatch import receiver

from distribution.models import ScriptEmail
from distribution.services import supersede_submission_emails
from submissions.models import Submission
from submissions.signals import delete_file_after_commit


@receiver(pre_delete, sender=Submission)
def cancel_deleted_script_deliveries(sender, instance, **kwargs):
    supersede_submission_emails(instance)


@receiver(post_delete, sender=ScriptEmail)
def delete_attachment(sender, instance, **kwargs):
    if instance.attachment:
        delete_file_after_commit(
            instance.attachment.storage,
            instance.attachment.name,
            f"script email {instance.pk}",
        )
