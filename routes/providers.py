"""
Provider management routes: CRUD for AI providers.
"""

import json
import logging
from flask import Blueprint, request, jsonify
from flask_login import login_required

from models.database import db, Provider
from utils.helpers import login_required_api, sanitize_string, validate_url
from config.config import Config

logger = logging.getLogger(__name__)
providers_bp = Blueprint("providers", __name__)


@providers_bp.route("/providers", methods=["GET"])
@login_required
def get_providers():
    """List all providers."""
    providers = Provider.query.order_by(Provider.priority.asc()).all()
    return jsonify({
        "providers": [p.to_dict() for p in providers],
        "total": len(providers),
    })


@providers_bp.route("/providers", methods=["POST"])
@login_required
def create_provider():
    """Create a new provider."""
    data = request.get_json(silent=True) or {}

    name = sanitize_string(data.get("name", ""), 100)
    display_name = sanitize_string(data.get("display_name", ""), 100)
    provider_type = sanitize_string(data.get("provider_type", "custom"), 50)
    base_url = sanitize_string(data.get("base_url", ""), 500)
    default_model = sanitize_string(data.get("default_model", ""), 200)
    available_models = data.get("available_models", [])
    priority = int(data.get("priority", 0))

    # Validation
    if not name:
        return jsonify({"error": "Provider name is required"}), 400
    if base_url and not validate_url(base_url):
        return jsonify({"error": "Invalid base URL format"}), 400
    if Provider.query.filter_by(name=name).first():
        return jsonify({"error": "Provider name already exists"}), 409

    # Apply defaults for known provider types
    if provider_type in Config.PROVIDER_DEFAULTS and not base_url:
        defaults = Config.PROVIDER_DEFAULTS[provider_type]
        base_url = defaults.get("base_url", "")
        if not available_models:
            available_models = defaults.get("models", [])

    provider = Provider(
        name=name,
        display_name=display_name or name,
        provider_type=provider_type,
        base_url=base_url,
        default_model=default_model,
        available_models=available_models,
        is_custom=(provider_type == "custom"),
        priority=priority,
    )
    provider.save()
    logger.info(f"Created provider: {name}")
    return jsonify({"message": "Provider created", "provider": provider.to_dict()}), 201


@providers_bp.route("/providers/<provider_id>", methods=["PUT"])
@login_required
def update_provider(provider_id):
    """Update an existing provider."""
    provider = Provider.query.get_or_404(provider_id)
    data = request.get_json(silent=True) or {}

    if "display_name" in data:
        provider.display_name = sanitize_string(data["display_name"], 100)
    if "base_url" in data:
        url = sanitize_string(data["base_url"], 500)
        if url and not validate_url(url):
            return jsonify({"error": "Invalid base URL format"}), 400
        provider.base_url = url
    if "default_model" in data:
        provider.default_model = sanitize_string(data["default_model"], 200)
    if "available_models" in data:
        models = data["available_models"]
        if isinstance(models, list):
            provider.available_models = models
    if "is_enabled" in data:
        provider.is_enabled = bool(data["is_enabled"])
    if "priority" in data:
        provider.priority = int(data["priority"])

    provider.save()
    logger.info(f"Updated provider: {provider.name}")
    return jsonify({"message": "Provider updated", "provider": provider.to_dict()})


@providers_bp.route("/providers/<provider_id>", methods=["DELETE"])
@login_required
def delete_provider(provider_id):
    """Delete a provider and all its API keys."""
    provider = Provider.query.get_or_404(provider_id)
    name = provider.name
    # Delete dependent API keys first
    for key in provider.api_keys:
        key.delete()
    provider.delete()
    logger.info(f"Deleted provider: {name}")
    return jsonify({"message": f"Provider '{name}' deleted"})


@providers_bp.route("/providers/<provider_id>/toggle", methods=["POST"])
@login_required
def toggle_provider(provider_id):
    """Enable or disable a provider."""
    provider = Provider.query.get_or_404(provider_id)
    provider.is_enabled = not provider.is_enabled
    provider.save()
    state = "enabled" if provider.is_enabled else "disabled"
    return jsonify({"message": f"Provider {state}", "is_enabled": provider.is_enabled})


@providers_bp.route("/providers/defaults/<provider_type>", methods=["GET"])
@login_required
def get_provider_defaults(provider_type):
    """Get default configuration for a known provider type."""
    defaults = Config.PROVIDER_DEFAULTS.get(provider_type, {})
    return jsonify(defaults)