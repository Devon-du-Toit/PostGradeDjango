import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from distribution.dispatch import (
    process_next_email,
    recover_expired_sends,
)


logger = logging.getLogger(__name__)

RECOVERY_INTERVAL = 60


class Command(BaseCommand):
    help = "Send queued result emails."

    def add_arguments(self, parser):
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=2.0,
            help="Seconds to wait when the queue is empty.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Send all due emails, then exit.",
        )

    def handle(self, *args, **options):
        self.stopping = False

        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        self.stdout.write("Mail worker started.")

        next_recovery = 0.0

        while not self.stopping:
            # Long-running process: drop connections the database has closed.
            close_old_connections()

            if time.monotonic() >= next_recovery:
                self.recover()
                next_recovery = time.monotonic() + RECOVERY_INTERVAL

            try:
                processed = process_next_email()
            except Exception:
                logger.exception("Mail worker loop failed")
                processed = False

            if processed:
                continue

            if options["once"]:
                break

            time.sleep(options["poll_interval"])

        self.stdout.write("Mail worker stopped.")

    def request_stop(self, signum, frame):
        # Finish the current email, then exit the loop.
        self.stopping = True

    def recover(self):
        try:
            recovered = recover_expired_sends()
        except Exception:
            logger.exception("Result email recovery failed")
            return

        if recovered:
            self.stdout.write(
                f"Marked {recovered} interrupted email(s) as delivery unknown."
            )
