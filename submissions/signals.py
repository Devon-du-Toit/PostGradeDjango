import logging

from django.db.models.signals import post_delete
from django.dispatch import receiver

from submissions.models import Submission

logger = logging.getLogger(__name__)


@receiver(post_delete, sender=Submission)
def delete_submission_file_from_storage(sender, instance, **kwargs):
    """
    Remove the uploaded file from storage once its Submission row
    is gone. Also fires on cascade delete (e.g. deleting the
    parent Assessment or Course), since Django sends this signal
    for every row it collects, not just the one .delete() was
    called on directly.
    """
    if not instance.file:
        return

    try:
        instance.file.storage.delete(instance.file.name)
    except Exception:
        logger.exception(
            "Failed to delete storage file for submission %s (%s)",
            instance.pk,
            instance.file.name,
        )