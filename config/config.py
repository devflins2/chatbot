"""
Application configuration module.
Handles all configuration settings for different environments.
"""

import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration class with secure defaults."""

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour

    # ── Database ──────────────────────────────────────────────────────────────
    MONGO_URI = (
        os.environ.get("MONGO_URI")
        or "mongodb://localhost:27017/ai_dashboard"
    )

    # ── Session ───────────────────────────────────────────────────────────────
    PERMANENT_SESSION_LIFETIME = timedelta(hours=24)
    SESSION_COOKIE_SECURE = False      # Set True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # ── Encryption ────────────────────────────────────────────────────────────
    # Fernet encryption key for API keys at rest
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY") or None

    # ── Rate limiting ─────────────────────────────────────────────────────────
    RATELIMIT_DEFAULT = "200 per day;50 per hour"
    RATELIMIT_STORAGE_URL = "memory://"

    # ── AI defaults ───────────────────────────────────────────────────────────
    DEFAULT_TIMEOUT = 30          # seconds
    DEFAULT_MAX_TOKENS = 2048
    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_TOP_P = 1.0
    DEFAULT_MAX_CONTEXT = 10      # number of history turns

    # ── Pagination ────────────────────────────────────────────────────────────
    ITEMS_PER_PAGE = 20

    # ── Application ───────────────────────────────────────────────────────────
    APP_NAME = "AI Dashboard"
    APP_VERSION = "1.0.0"

    # ── Provider base URLs ────────────────────────────────────────────────────
    PROVIDER_DEFAULTS = {
        "groq": {
            "base_url": "https://api.groq.com/openai/v1",
            "models": [
                "llama-3.3-70b-versatile",
                "llama-3.1-70b-versatile",
                "llama-3.1-8b-instant",
                "llama3-70b-8192",
                "llama3-8b-8192",
                "mixtral-8x7b-32768",
                "gemma2-9b-it",
                "gemma-7b-it",
            ],
        },
        "google_gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "models": [
                "gemini-2.5-flash-preview-05-20",
                "gemini-2.5-pro-preview-05-06",
                "gemini-1.5-flash",
                "gemini-1.5-pro",
                "gemini-1.0-pro",
            ],
        },
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "models": [
                "openai/gpt-4o",
                "anthropic/claude-3.5-sonnet",
                "meta-llama/llama-3.1-70b-instruct",
                "mistralai/mistral-7b-instruct",
                "google/gemini-flash-1.5",
            ],
        },
        "huggingface": {
            "base_url": "https://api-inference.huggingface.co/models",
            "models": [
                "mistralai/Mistral-7B-Instruct-v0.3",
                "meta-llama/Meta-Llama-3-8B-Instruct",
                "HuggingFaceH4/zephyr-7b-beta",
                "microsoft/DialoGPT-large",
            ],
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "models": [
                "gpt-4o",
                "gpt-4o-mini",
                "gpt-4-turbo",
                "gpt-4",
                "gpt-3.5-turbo",
            ],
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "models": [
                "deepseek-chat",
                "deepseek-coder",
                "deepseek-reasoner",
            ],
        },
        "mistral": {
            "base_url": "https://api.mistral.ai/v1",
            "models": [
                "mistral-large-latest",
                "mistral-medium-latest",
                "mistral-small-latest",
                "open-mistral-7b",
                "open-mixtral-8x7b",
                "open-mixtral-8x22b",
                "codestral-latest",
            ],
        },
        "anthropic": {
            "base_url": "https://api.anthropic.com/v1",
            "models": [
                "claude-opus-4-5",
                "claude-sonnet-4-5",
                "claude-3-5-haiku-latest",
                "claude-3-5-sonnet-20241022",
                "claude-3-opus-20240229",
            ],
        },
    }


class DevelopmentConfig(Config):
    """Development-specific configuration."""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production-specific configuration."""
    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    WTF_CSRF_ENABLED = True


class TestingConfig(Config):
    """Testing-specific configuration."""
    DEBUG = True
    TESTING = True
    WTF_CSRF_ENABLED = False
    MONGO_URI = "mongodb://localhost:27017/ai_dashboard_test"


# Configuration selector
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}