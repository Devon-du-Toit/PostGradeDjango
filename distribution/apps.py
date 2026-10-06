from django.apps import AppConfig


class DistributionConfig(AppConfig):
    name = "distribution"

    def ready(self):
        from distribution import signals  # noqa: F401
