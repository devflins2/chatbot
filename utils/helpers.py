"""
General utility helpers: input validation, CSRF, pagination, CSV export, etc.
"""

import re
import csv
import io
import json
from datetime import datetime, timezone
from functools import wraps
from flask import session, jsonify, request, abort
from flask_login import current_user


def login_required_api(f):
    """Decorator for API routes that require authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"error": "Authentication required"}), 401
        return f(*args, **kwargs)
    return decorated


def validate_url(url: str) -> bool:
    """Validate a URL string."""
    pattern = re.compile(
        r"^https?://"                             # http:// or https://
        r"(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|"
        r"localhost|"
        r"\d{1,3}(?:\.\d{1,3}){3})"              # IP address
        r"(?::\d+)?"                              # Port
        r"(?:/?|[/?]\S+)$",
        re.IGNORECASE,
    )
    return bool(pattern.match(url))


def sanitize_string(s: str, max_length: int = 1000) -> str:
    """Sanitize and truncate a string input."""
    if not isinstance(s, str):
        return ""
    return s.strip()[:max_length]


def paginate_query(query, page: int, per_page: int = 20):
    """Apply pagination to a SQLAlchemy query."""
    page = max(1, page)
    per_page = min(max(1, per_page), 100)
    total = query.count()
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": items,
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "has_prev": page > 1,
        "has_next": page * per_page < total,
    }


def logs_to_csv(logs: list) -> str:
    """Convert log records to CSV format."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "Time", "Provider", "Model", "Status",
        "Latency (ms)", "Prompt Tokens", "Completion Tokens",
        "Total Tokens", "Error"
    ])
    for log in logs:
        d = log.to_dict()
        writer.writerow([
            d["id"], d["created_at"], d["provider_name"], d["model"],
            d["status"], d["latency_ms"], d["prompt_tokens"],
            d["completion_tokens"], d["total_tokens"], d["error_message"] or "",
        ])
    return output.getvalue()


def get_client_ip() -> str:
    """Get the real client IP address."""
    if request.headers.get("X-Forwarded-For"):
        return request.headers["X-Forwarded-For"].split(",")[0].strip()
    return request.remote_addr or "unknown"