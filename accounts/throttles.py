from django.conf import settings
from django.core.cache import caches
from rest_framework.throttling import SimpleRateThrottle


class AuthRateThrottle(SimpleRateThrottle):
    def get_rate(self):
        return getattr(settings, f"{self.scope.upper()}_THROTTLE_RATE")

    @property
    def cache(self):
        return caches["throttle"]

    def get_cache_key(self, request, view):
        # Always limit by client, even if a stale Authorization header is sent.
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class LoginThrottle(AuthRateThrottle):
    scope = "login"


class RegisterThrottle(AuthRateThrottle):
    scope = "register"


class RefreshThrottle(AuthRateThrottle):
    scope = "refresh"


class LogoutThrottle(AuthRateThrottle):
    scope = "logout"
