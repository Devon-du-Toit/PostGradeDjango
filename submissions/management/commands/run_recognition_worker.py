import logging
import signal
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from submissions.jobs import process_next_job


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Process queued submission recognition jobs."

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
            help="Process all due jobs, then exit.",
        )

    def handle(self, *args, **options):
        self.stopping = False

        signal.signal(signal.SIGINT, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)

        self.stdout.write("Recognition worker started.")

        while not self.stopping:
            close_old_connections()

            try:
                processed = process_next_job()
            except Exception:
                logger.exception(
                    "Recognition worker loop failed"
                )
                processed = False

            if processed:
                continue

            if options["once"]:
                break

            time.sleep(options["poll_interval"])

        self.stdout.write("Recognition worker stopped.")

    def request_stop(self, signum, frame):
        self.stopping = True