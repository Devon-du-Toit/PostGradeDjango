"""Gunicorn settings for the web container (Linux only; see DOCS/DEPLOYMENT.md).

The web process only serves the API. Recognition and email run in their own
worker containers, so requests stay short.
"""

import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"

# Processes serving requests. Each holds its own database connection
# (reused for DB_CONN_MAX_AGE seconds).
workers = int(os.getenv("WEB_CONCURRENCY", "3"))

# Uploads of up to 15 MB on a slow connection still fit comfortably.
timeout = int(os.getenv("GUNICORN_TIMEOUT", "60"))

# Replace each process after this many requests, so slow memory growth
# (e.g. from image libraries) can't accumulate.
max_requests = 1000
max_requests_jitter = 100

accesslog = "-"
errorlog = "-"

# The path only, never the query string: ?search= can contain student names.
access_log_format = '%(h)s "%(m)s %(U)s %(H)s" %(s)s %(B)s %(M)sms'
