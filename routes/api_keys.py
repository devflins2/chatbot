"""
API Key management routes.
Keys are encrypted at rest; raw values are NEVER returned to the frontend.
"""

import logging
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
from flask_login import login_required

from models.database import db, APIKey, Provider
from utils.encryption import encrypt_api_key, make_key_preview
from utils.helpers import sanitize_string, paginate_query
from utils.ai_client import test_api_key

logger = logging.getLogger(__name__)
api_keys_bp = Blueprint("api_keys", __name__)


@api_keys_bp.route("/apikeys", methods=["GET"])
@login_required
def get_api_keys():
    """List API keys with search, filter, and pagination. Never returns raw keys."""
    page = int(request.args.get("page", 1))
    per_page = int(request.args.get("per_page", 20))
    provider_id = request.args.get("provider_id")
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "")

    query = APIKey.query
    filter_dict = {}

    if provider_id:
        from bson.objectid import ObjectId
        if isinstance(provider_id, str) and ObjectId.is_valid(provider_id):
            filter_dict["provider_id"] = ObjectId(provider_id)
        else:
            filter_dict["provider_id"] = provider_id

    if search:
        filter_dict["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"key_preview": {"$regex": search, "$options": "i"}},
        ]

    if status_filter == "active":
        filter_dict["is_active"] = True
        filter_dict["is_failed"] = False
    elif status_filter == "failed":
        filter_dict["is_failed"] = True
    elif status_filter == "disabled":
        filter_dict["is_active"] = False

    query = query.filter(filter_dict)
    query = query.order_by(APIKey.created_at.desc())
    paginated = paginate_query(query, page, per_page)

    return jsonify({
        "keys": [k.to_dict() for k in paginated["items"]],
        "total": paginated["total"],
        "page": paginated["page"],
        "pages": paginated["pages"],
        "has_prev": paginated["has_prev"],
        "has_next": paginated["has_next"],
    })


@api_keys_bp.route("/apikeys", methods=["POST"])
@login_required
def add_api_key():
    """
    Add a new API key.
    The raw key is encrypted immediately and the original is not stored.
    """
    data = request.get_json(silent=True) or {}

    provider_id = data.get("provider_id")
    raw_key = data.get("api_key", "").strip()
    name = sanitize_string(data.get("name", ""), 100)

    # Validation
    if not provider_id:
        return jsonify({"error": "Provider ID is required"}), 400
    if not raw_key:
        return jsonify({"error": "API key is required"}), 400
    if len(raw_key) < 8:
        return jsonify({"error": "API key appears too short"}), 400

    provider = Provider.query.get(provider_id)
    if not provider:
        return jsonify({"error": "Provider not found"}), 404

    # Encrypt the key immediately — raw_key is discarded after this
    encrypted = encrypt_api_key(raw_key)
    preview = make_key_preview(raw_key)
    del raw_key  # Explicitly delete from memory

    from bson.objectid import ObjectId
    api_key = APIKey(
        provider_id=ObjectId(provider_id) if ObjectId.is_valid(provider_id) else provider_id,
        name=name or f"Key for {provider.display_name}",
        encrypted_key=encrypted,
        key_preview=preview,
        is_active=True,
        is_failed=False,
        fail_reason=None,
        total_requests=0,
        successful_requests=0,
        failed_requests=0,
        created_at=datetime.now(timezone.utc),
    )
    api_key.save()
    logger.info(f"Added API key for provider: {provider.name}")

    return jsonify({
        "message": "API key added successfully",
        "key": api_key.to_dict(),
    }), 201


@api_keys_bp.route("/apikeys/<key_id>", methods=["PUT"])
@login_required
def update_api_key(key_id):
    """Update API key metadata (name, status). Cannot update the key value directly."""
    key = APIKey.query.get_or_404(key_id)
    data = request.get_json(silent=True) or {}

    if "name" in data:
        key.name = sanitize_string(data["name"], 100)
    if "is_active" in data:
        key.is_active = bool(data["is_active"])
        if key.is_active:
            key.is_failed = False   # Re-enable clears failed state
    if "new_api_key" in data and data["new_api_key"]:
        # Replace the encrypted key
        raw_key = data["new_api_key"].strip()
        if len(raw_key) < 8:
            return jsonify({"error": "API key appears too short"}), 400
        key.encrypted_key = encrypt_api_key(raw_key)
        key.key_preview = make_key_preview(raw_key)
        key.is_failed = False
        key.fail_reason = None
        del raw_key

    key.save()
    return jsonify({"message": "API key updated", "key": key.to_dict()})


@api_keys_bp.route("/apikeys/<key_id>", methods=["DELETE"])
@login_required
def delete_api_key(key_id):
    """Delete an API key."""
    key = APIKey.query.get_or_404(key_id)
    key.delete()
    logger.info(f"Deleted API key {key_id}")
    return jsonify({"message": "API key deleted"})


@api_keys_bp.route("/apikeys/<key_id>/test", methods=["POST"])
@login_required
def test_key(key_id):
    """Test an API key with a simple request."""
    key = APIKey.query.get_or_404(key_id)
    provider = key.provider

    result = test_api_key(provider, key.encrypted_key)

    # Update key status based on test result
    key.last_tested = datetime.now(timezone.utc)
    if result["success"]:
        key.is_failed = False
        key.fail_reason = None
    else:
        # Only mark as failed for auth errors
        if "401" in result["message"] or "403" in result["message"] or "invalid" in result["message"].lower():
            key.is_failed = True
            key.fail_reason = result["message"]
    key.save()

    return jsonify(result)


@api_keys_bp.route("/apikeys/<key_id>/toggle", methods=["POST"])
@login_required
def toggle_api_key(key_id):
    """Enable or disable an API key."""
    key = APIKey.query.get_or_404(key_id)
    key.is_active = not key.is_active
    key.save()
    state = "enabled" if key.is_active else "disabled"
    return jsonify({"message": f"Key {state}", "is_active": key.is_active})