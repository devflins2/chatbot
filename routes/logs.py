"""
Log viewing and export routes.
"""

import logging
from flask import Blueprint, request, jsonify, Response
from flask_login import login_required

from models.database import Log, Provider
from utils.helpers import paginate_query, logs_to_csv

logger = logging.getLogger(__name__)
logs_bp = Blueprint("logs", __name__)


@logs_bp.route("/logs", methods=["GET"])
@login_required
def get_logs():
    """Get paginated request logs with search and filter."""
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    provider_id = request.args.get("provider_id")
    status_filter = request.args.get("status", "")
    search = request.args.get("search", "").strip()

    query = Log.query
    filter_dict = {}

    if provider_id:
        from bson.objectid import ObjectId
        if isinstance(provider_id, str) and ObjectId.is_valid(provider_id):
            filter_dict["provider_id"] = ObjectId(provider_id)
        else:
            filter_dict["provider_id"] = provider_id

    if status_filter in ("success", "failed"):
        filter_dict["status"] = status_filter

    if search:
        filter_dict["$or"] = [
            {"model": {"$regex": search, "$options": "i"}},
            {"error_message": {"$regex": search, "$options": "i"}},
            {"prompt_preview": {"$regex": search, "$options": "i"}},
        ]

    query = query.filter(filter_dict)
    query = query.order_by(Log.created_at.desc())
    paginated = paginate_query(query, page, per_page)

    return jsonify({
        "logs": [l.to_dict() for l in paginated["items"]],
        "total": paginated["total"],
        "page": paginated["page"],
        "pages": paginated["pages"],
    })


@logs_bp.route("/logs/export", methods=["GET"])
@login_required
def export_logs():
    """Export all logs as CSV."""
    logs = Log.query.order_by(Log.created_at.desc()).limit(10000).all()
    csv_data = logs_to_csv(logs)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ai_logs.csv"},
    )