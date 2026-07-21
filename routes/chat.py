"""
Chat endpoint — the unified AI API.
POST /chat accepts a message and returns a response from the best available provider.
"""

import json
import logging
from flask import Blueprint, request, jsonify, Response, render_template, stream_with_context
from flask_login import login_required

from utils.ai_client import AIClient, AIClientError
from utils.helpers import sanitize_string, get_client_ip
from models.database import db, ChatHistory

logger = logging.getLogger(__name__)
chat_bp = Blueprint("chat", __name__)


@chat_bp.route("/chat", methods=["POST"])
def chat():
    """
    Unified chat endpoint.
    Accepts JSON body with: message, chat_history, provider (optional), model (optional)
    Returns AI response with provider and model information.
    """
    data = request.get_json(silent=True) or {}

    message = sanitize_string(data.get("message", ""), 8000)
    if not message:
        return jsonify({"error": "Message is required"}), 400

    chat_history = data.get("chat_history", [])
    if not isinstance(chat_history, list):
        chat_history = []

    # Limit history entries to prevent abuse
    chat_history = chat_history[-50:]

    provider_id = data.get("provider_id") or data.get("provider")
    if provider_id and not isinstance(provider_id, int):
        try:
            provider_id = int(provider_id)
        except (ValueError, TypeError):
            from bson.objectid import ObjectId
            if not (isinstance(provider_id, str) and ObjectId.is_valid(provider_id)):
                provider_id = None

    model = sanitize_string(data.get("model", ""), 200) or None
    system_prompt = sanitize_string(data.get("system_prompt", ""), 4000) or None
    stream = data.get("stream", False)
    session_id = sanitize_string(data.get("session_id", "default"), 100)
    ip = get_client_ip()

    try:
        client = AIClient()

        if stream:
            # Return a streaming response
            def generate():
                for chunk in client.chat_stream(
                    message=message,
                    chat_history=chat_history,
                    provider_id=provider_id,
                    model=model,
                    system_prompt=system_prompt,
                    ip_address=ip,
                ):
                    yield chunk

            return Response(
                stream_with_context(generate()),
                mimetype="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                },
            )

        # Non-streaming response
        result = client.chat(
            message=message,
            chat_history=chat_history,
            provider_id=provider_id,
            model=model,
            system_prompt=system_prompt,
            ip_address=ip,
        )

        # Optionally save to chat history
        if session_id:
            _save_chat_history(session_id, message, result)

        return jsonify({
            "response": result["response"],
            "provider": result.get("provider"),
            "provider_display": result.get("provider_display"),
            "model": result.get("model"),
            "prompt_tokens": result.get("prompt_tokens"),
            "completion_tokens": result.get("completion_tokens"),
            "total_tokens": result.get("total_tokens"),
        })

    except AIClientError as e:
        logger.error(f"Chat error: {e}")
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        logger.exception(f"Unexpected chat error: {e}")
        return jsonify({"error": "Internal server error"}), 500


@chat_bp.route("/chat/history/<session_id>", methods=["GET"])
@login_required
def get_chat_history(session_id):
    """Get chat history for a session."""
    session_id = sanitize_string(session_id, 100)
    history = ChatHistory.query.filter_by(session_id=session_id).order_by(
        ChatHistory.created_at.asc()
    ).all()
    return jsonify({"history": [h.to_dict() for h in history]})


@chat_bp.route("/chat/history/<session_id>", methods=["DELETE"])
@login_required
def clear_chat_history(session_id):
    """Clear chat history for a session."""
    session_id = sanitize_string(session_id, 100)
    ChatHistory.query.filter_by(session_id=session_id).delete()
    return jsonify({"message": "Chat history cleared"})


def _save_chat_history(session_id: str, message: str, result: dict):
    """Save a chat exchange to the database."""
    try:
        user_msg = ChatHistory(
            session_id=session_id,
            role="user",
            content=message[:4000],
        )
        assistant_msg = ChatHistory(
            session_id=session_id,
            role="assistant",
            content=str(result.get("response", ""))[:4000],
            model=result.get("model"),
        )
        user_msg.save()
        assistant_msg.save()
    except Exception as e:
        logger.warning(f"Failed to save chat history: {e}")