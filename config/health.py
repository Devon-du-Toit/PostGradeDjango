"""Health checks for the hosting platform's probes.

Served by middleware at the top of the stack rather than by URL routes:
platforms probe with the container's internal IP as the Host header, which
ALLOWED_HOSTS would reject, and a probe needs none of the session,
authentication or CORS work that follows.
"""

from django.db import DatabaseError, connection
from django.http import JsonResponse

LIVE_PATH = "/health/live/"
READY_PATH = "/health/ready/"


def database_ready():
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return False
    return True


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path not in (LIVE_PATH, READY_PATH):
            return self.get_response(request)

        if request.method != "GET":
            return JsonResponse({"status": "method not allowed"}, status=405)

        # Live: the process answers. Ready: it can also reach the database,
        # so the platform only sends traffic to instances that can serve it.
        if request.path == READY_PATH and not database_ready():
            return JsonResponse({"status": "unavailable"}, status=503)

        return JsonResponse({"status": "ok"})
