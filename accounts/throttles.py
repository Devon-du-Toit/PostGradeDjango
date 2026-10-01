from django.core.cache import caches
from rest_framework.throttling import ScopedRateThrottle


class AuthRateThrottle(ScopedRateThrottle):
    """Per-client limit for the unauthenticated auth views.

    Counts live in the shared "throttle" cache, so the limit holds
    across gunicorn workers instead of multiplying by their number.
    """

    cache = caches["throttle"]
