from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver

from submissions.models import RecognitionAttempt


@receiver(post_delete, sender=RecognitionAttempt)
def delete_region_image(sender, instance, **kwargs):
    # Also fires for attempts deleted by a Submission cascade. The file is
    # removed only once the delete commits, so a rolled-back delete keeps it.
    if not instance.region_image:
        return

    storage = instance.region_image.storage
    name = instance.region_image.name

    transaction.on_commit(lambda: storage.delete(name))
