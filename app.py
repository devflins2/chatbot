"""
Main application entry point.
Initializes Flask, database, login manager, and registers all blueprints.
"""

import os
import json
import logging
from datetime import datetime, timezone

from flask import Flask, render_template, redirect, url_for, jsonify
from flask_login import LoginManager, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from config.config import config, Config
from models.database import db, User, Provider, Setting
from routes.auth import auth_bp
from routes.providers import providers_bp
from routes.api_keys import api_keys_bp
from routes.chat import chat_bp
from routes.logs import logs_bp
from routes.stats import stats_bp
from routes.settings import settings_bp

# ─────────────────────────────────────────────────────────────────────────────
# Logging setup
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Extensions
# ─────────────────────────────────────────────────────────────────────────────
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
)


# ─────────────────────────────────────────────────────────────────────────────
# Application factory
# ─────────────────────────────────────────────────────────────────────────────
def create_app(config_name: str = "default") -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Load configuration
    app.config.from_object(config[config_name])

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # Login manager settings
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    # Exempt public chat API from CSRF (uses Bearer token / programmatic access)
    csrf.exempt(chat_bp)

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(providers_bp, url_prefix="/api")
    app.register_blueprint(api_keys_bp, url_prefix="/api")
    app.register_blueprint(chat_bp, url_prefix="/api")
    app.register_blueprint(logs_bp, url_prefix="/api")
    app.register_blueprint(stats_bp, url_prefix="/api")
    app.register_blueprint(settings_bp, url_prefix="/api")

    # Register main page routes
    _register_main_routes(app)

    # Initialize database
    with app.app_context():
        _seed_database()

    return app


def _register_main_routes(app: Flask):
    """Register HTML page routes."""

    @app.route("/")
    @login_required
    def index():
        return redirect(url_for("main.dashboard"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    @app.route("/providers-page")
    @login_required
    def providers_page():
        return render_template("providers.html")

    @app.route("/api-keys-page")
    @login_required
    def api_keys_page():
        return render_template("api_keys.html")

    @app.route("/chat-page")
    @login_required
    def chat_page():
        return render_template("chat.html")

    @app.route("/logs-page")
    @login_required
    def logs_page():
        return render_template("logs.html")

    @app.route("/analytics-page")
    @login_required
    def analytics_page():
        return render_template("analytics.html")

    @app.route("/settings-page")
    @login_required
    def settings_page():
        return render_template("settings.html")

    # Register this blueprint for named routes
    from flask import Blueprint
    main_bp = Blueprint("main", __name__)

    @main_bp.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html")

    app.register_blueprint(main_bp)

    @app.errorhandler(404)
    def not_found(e):
        return render_template("error.html", code=404, message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template("error.html", code=500, message="Internal server error"), 500

    @app.context_processor
    def inject_globals():
        return {
            "app_name": Config.APP_NAME,
            "app_version": Config.APP_VERSION,
            "current_year": datetime.now().year,
        }


@login_manager.user_loader
def load_user(user_id: str) -> User:
    """Load user by ID for Flask-Login."""
    return User.query.get(user_id)


def _seed_database():
    """Create default admin user and seed providers on first run."""
    # Create default admin
    if not User.query.first():
        admin = User(username="admin", email="admin@example.com")
        admin.set_password("admin123")
        admin.save()
        logger.info("Created default admin user (username: admin, password: admin123)")

    # Seed default settings
    default_settings = {
        "api_timeout": "30",
        "max_tokens": "2048",
        "temperature": "0.7",
        "top_p": "1.0",
        "max_context_length": "10",
        "system_prompt": "You are a helpful AI assistant.",
        "streaming_enabled": "true",
        "selection_strategy": "priority",
        "theme": "dark",
    }
    for key, value in default_settings.items():
        if not Setting.query.filter_by(key=key).first():
            setting = Setting(key=key, value=value)
            setting.save()

    # Seed built-in providers
    provider_seeds = [
        {"name": "groq", "display_name": "Groq", "type": "groq",
         "url": "https://api.groq.com/openai/v1",
         "model": "llama-3.3-70b-versatile", "priority": 1},
        {"name": "google_gemini", "display_name": "Google Gemini", "type": "google_gemini",
         "url": "https://generativelanguage.googleapis.com/v1beta/openai",
         "model": "gemini-2.5-flash-preview-05-20", "priority": 2},
        {"name": "openrouter", "display_name": "OpenRouter", "type": "openrouter",
         "url": "https://openrouter.ai/api/v1",
         "model": "openai/gpt-4o", "priority": 3},
        {"name": "openai", "display_name": "OpenAI", "type": "openai",
         "url": "https://api.openai.com/v1",
         "model": "gpt-4o", "priority": 4},
        {"name": "anthropic", "display_name": "Anthropic", "type": "anthropic",
         "url": "https://api.anthropic.com/v1",
         "model": "claude-sonnet-4-5", "priority": 5},
        {"name": "deepseek", "display_name": "DeepSeek", "type": "deepseek",
         "url": "https://api.deepseek.com/v1",
         "model": "deepseek-chat", "priority": 6},
        {"name": "mistral", "display_name": "Mistral AI", "type": "mistral",
         "url": "https://api.mistral.ai/v1",
         "model": "mistral-large-latest", "priority": 7},
        {"name": "huggingface", "display_name": "Hugging Face", "type": "huggingface",
         "url": "https://api-inference.huggingface.co/models",
         "model": "mistralai/Mistral-7B-Instruct-v0.3", "priority": 8},
    ]

    for seed in provider_seeds:
        if not Provider.query.filter_by(name=seed["name"]).first():
            defaults = Config.PROVIDER_DEFAULTS.get(seed["type"], {})
            p = Provider(
                name=seed["name"],
                display_name=seed["display_name"],
                provider_type=seed["type"],
                base_url=seed["url"],
                default_model=seed["model"],
                available_models=defaults.get("models", [seed["model"]]),
                is_enabled=False,   # Disabled until keys are added
                priority=seed["priority"],
            )
            p.save()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    env = os.environ.get("FLASK_ENV", "development")
    application = create_app(env)
    application.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=(env == "development"),
    )