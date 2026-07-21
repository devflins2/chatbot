"""
Statistics and analytics routes.
"""

import logging
from datetime import datetime, timezone, timedelta
from flask import Blueprint, jsonify, request
from flask_login import login_required

from models.database import db, Log, Provider, APIKey, Setting

logger = logging.getLogger(__name__)
stats_bp = Blueprint("stats", __name__)


@stats_bp.route("/stats", methods=["GET"])
@login_required
def get_stats():
    """Get overall dashboard statistics."""
    total_providers = Provider.query.count()
    enabled_providers = Provider.query.filter_by(is_enabled=True).count()
    total_keys = APIKey.query.count()
    active_keys = APIKey.query.filter_by(is_active=True, is_failed=False).count()
    failed_keys = APIKey.query.filter_by(is_failed=True).count()
    total_requests = Log.query.count()
    success_requests = Log.query.filter_by(status="success").count()
    failed_requests = Log.query.filter_by(status="failed").count()

    from models.database import db
    pipeline = [
        {"$match": {"status": "success"}},
        {"$group": {"_id": None, "avg_latency": {"$avg": "$latency_ms"}}}
    ]
    agg_result = list(db.logs.aggregate(pipeline))
    avg_latency = agg_result[0]["avg_latency"] if agg_result else 0

    return jsonify({
        "total_providers": total_providers,
        "enabled_providers": enabled_providers,
        "total_keys": total_keys,
        "active_keys": active_keys,
        "failed_keys": failed_keys,
        "total_requests": total_requests,
        "success_requests": success_requests,
        "failed_requests": failed_requests,
        "success_rate": round(
            (success_requests / total_requests * 100) if total_requests > 0 else 0, 1
        ),
        "avg_latency_ms": round(avg_latency, 0),
    })


@stats_bp.route("/stats/daily", methods=["GET"])
@login_required
def get_daily_stats():
    """Get daily request counts for the past 30 days."""
    days = int(request.args.get("days", 30))
    since = datetime.now(timezone.utc) - timedelta(days=days)

    from models.database import db
    # Make sure 'since' is timezone-aware
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)

    pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {
            "$project": {
                "date_str": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$created_at"
                    }
                },
                "is_success": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]},
                "is_failed": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}
            }
        },
        {
            "$group": {
                "_id": "$date_str",
                "total": {"$sum": 1},
                "success": {"$sum": "$is_success"},
                "failed": {"$sum": "$is_failed"}
            }
        },
        {"$sort": {"_id": 1}}
    ]
    results = list(db.logs.aggregate(pipeline))

    return jsonify({
        "daily": [
            {
                "date": r["_id"],
                "total": r["total"],
                "success": r["success"],
                "failed": r["failed"],
            }
            for r in results
        ]
    })


@stats_bp.route("/stats/providers", methods=["GET"])
@login_required
def get_provider_stats():
    """Get per-provider usage statistics."""
    from models.database import db
    from bson.objectid import ObjectId

    providers = Provider.query.order_by(Provider.priority.asc()).all()
    provider_stats = []

    for p in providers:
        p_id = ObjectId(p.id) if ObjectId.is_valid(p.id) else p.id
        pipeline = [
            {"$match": {"provider_id": p_id}},
            {
                "$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "success": {"$sum": {"$cond": [{"$eq": ["$status", "success"]}, 1, 0]}},
                    "avg_latency": {"$avg": {"$cond": [{"$eq": ["$status", "success"]}, "$latency_ms", None]}}
                }
            }
        ]
        res = list(db.logs.aggregate(pipeline))
        stats = res[0] if res else {"total": 0, "success": 0, "avg_latency": 0}

        provider_stats.append({
            "name": p.display_name,
            "total": stats.get("total", 0),
            "success": stats.get("success", 0),
            "avg_latency": round(stats.get("avg_latency") or 0, 0),
        })

    return jsonify({"providers": provider_stats})