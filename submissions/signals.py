import logging

from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from submissions.models import RecognitionAttempt, ScriptPage, ScriptUpload, Submission

logger = logging.getLogger(__name__)


def delete_file_after_commit(storage, name, owner):
    # Files are removed only once the delete commits, so a rolled-back
    # delete keeps its file. A storage failure is logged, not raised:
    # the row is already gone and the request must not fail afterwards.
    def delete():
        try:
            storage.delete(name)
        except Exception:
            # The stored name can contain the uploaded filename (often a
            # student number), so only the owning record is logged.
            logger.exception("Failed to delete stored file for %s", owner)

    transaction.on_commit(delete)


@receiver(post_delete, sender=Submission)
def delete_submission_file(sender, instance, **kwargs):
    # Also fires on cascade deletes (assessment, course), since Django
    # sends post_delete for every row it collects.
    if not instance.file:
        return

    delete_file_after_commit(
        instance.file.storage,
        instance.file.name,
        f"submission {instance.pk}",
    )


@receiver(post_delete, sender=RecognitionAttempt)
def delete_region_image(sender, instance, **kwargs):
    # Also fires for attempts deleted by a Submission cascade.
    if not instance.region_image:
        return

    delete_file_after_commit(
        instance.region_image.storage,
        instance.region_image.name,
        f"recognition attempt {instance.pk}",
    )


@receiver(post_delete, sender=ScriptPage)
@receiver(post_delete, sender=ScriptUpload)
def delete_script_page_file(sender, instance, **kwargs):
    if instance.file:
        delete_file_after_commit(
            instance.file.storage, instance.file.name, f"script evidence {instance.pk}"
        )
