import os

# Gunicorn configuration file

# Read the PORT environment variable set by Render/local env, default to 10000
port = os.environ.get("PORT", "10000")
bind = f"0.0.0.0:{port}"

# Worker configuration
workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
threads = 2
timeout = 120
keepalive = 5
