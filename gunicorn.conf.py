import os

# Gunicorn configuration file

# Hardcode port to 5000 to match Render scanner configuration
bind = "0.0.0.0:5000"

# Worker configuration
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = 2
timeout = 120
keepalive = 5
