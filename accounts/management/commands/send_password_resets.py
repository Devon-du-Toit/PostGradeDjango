from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import PasswordResetRequest
from accounts.recovery import deliver_recovery, recovery_enabled


class Command(BaseCommand):
    help = "Deliver queued recovery messages using the configured email backend; never output credentials."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        PasswordResetRequest.objects.filter(
            created_at__lt=timezone.now()
            - timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT)
        ).delete()
        if not recovery_enabled():
            self.stdout.write("Password recovery is disabled; delivery skipped.")
            return
        ids = list(
            PasswordResetRequest.objects.filter(next_attempt_at__lte=timezone.now())
            .order_by("id")
            .values_list("id", flat=True)[: max(0, min(options["limit"], 1000))]
        )
        processed = 0
        for pk in ids:
            with transaction.atomic():
                item = (
                    PasswordResetRequest.objects.select_for_update(skip_locked=True)
                    .filter(pk=pk, next_attempt_at__lte=timezone.now())
                    .first()
                )
                if item is None:
                    continue
                if deliver_recovery(item.email, item.created_at) is False:
                    item.attempts += 1
                    if item.attempts < 3:
                        item.next_attempt_at = timezone.now() + timedelta(
                            seconds=60 * 2**item.attempts
                        )
                        item.save(update_fields=["attempts", "next_attempt_at"])
                        continue
                item.delete()
                processed += 1
        self.stdout.write(f"Processed {processed} recovery requests.")
