"""
Settings management routes.
"""

import logging
from flask import Blueprint, request, jsonify, render_template
from flask_login import login_required

from models.database import db, Setting
from utils.helpers import sanitize_string

logger = logging.getLogger(__name__)
settings_bp = Blueprint("settings", __name__)

# Settings schema: key -> {type, default, description}
SETTINGS_SCHEMA = {
    "api_timeout": {"type": "int", "default": "30", "description": "API request timeout in seconds"},
    "max_tokens": {"type": "int", "default": "2048", "description": "Maximum tokens per response"},
    "temperature": {"type": "float", "default": "0.7", "description": "Response temperature (0-2)"},
    "top_p": {"type": "float", "default": "1.0", "description": "Top-p sampling parameter"},
    "max_context_length": {"type": "int", "default": "10", "description": "Max conversation history turns"},
    "system_prompt": {"type": "string", "default": "You are a helpful AI assistant.", "description": "System prompt"},
    "streaming_enabled": {"type": "bool", "default": "true", "description": "Enable response streaming"},
    "selection_strategy": {"type": "string", "default": "priority", "description": "Provider selection: priority/random"},
    "theme": {"type": "string", "default": "dark", "description": "UI theme"},
}


@settings_bp.route("/settings-data", methods=["GET"])
@login_required
def get_settings():
    """Get all settings."""
    result = {}
    for key, schema in SETTINGS_SCHEMA.items():
        value = Setting.get(key, schema["default"])
        result[key] = {
            "value": value,
            "type": schema["type"],
            "description": schema["description"],
            "default": schema["default"],
        }
    return jsonify(result)


@settings_bp.route("/settings-data", methods=["POST"])
@login_required
def update_settings():
    """Update settings."""
    data = request.get_json(silent=True) or {}

    for key, value in data.items():
        if key not in SETTINGS_SCHEMA:
            continue
        schema = SETTINGS_SCHEMA[key]
        # Type validation
        try:
            if schema["type"] == "int":
                value = str(int(value))
            elif schema["type"] == "float":
                value = str(float(value))
            elif schema["type"] == "bool":
                value = str(value).lower()
            else:
                value = sanitize_string(str(value), 2000)
        except (ValueError, TypeError):
            return jsonify({"error": f"Invalid value for {key}"}), 400

        Setting.set(key, value, schema["description"])

    return jsonify({"message": "Settings saved successfully"})