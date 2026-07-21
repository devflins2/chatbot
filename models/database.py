"""
Database models for the AI Dashboard application using MongoDB.
"""

import logging
from datetime import datetime, timezone
from pymongo import MongoClient
from bson.objectid import ObjectId
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)

def utcnow():
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


class PyMongoDatabase:
    """Wrapper class for PyMongo client & database connection."""
    def __init__(self):
        self.client = None
        self.db = None

    def init_app(self, app):
        mongo_uri = app.config.get("MONGO_URI") or "mongodb://localhost:27017/ai_dashboard"
        self.client = MongoClient(mongo_uri)
        
        # Extract database name from connection string
        import urllib.parse
        parsed = urllib.parse.urlparse(mongo_uri)
        db_name = parsed.path.lstrip('/') or "ai_dashboard"
        self.db = self.client[db_name]
        logger.info(f"Initialized PyMongo database connection to: {db_name}")

    def __getattr__(self, name):
        if self.db is None:
            raise RuntimeError("Database not initialized. Call init_app first.")
        return getattr(self.db, name)

    def __getitem__(self, name):
        if self.db is None:
            raise RuntimeError("Database not initialized. Call init_app first.")
        return self.db[name]

# Global database instance
db = PyMongoDatabase()


class MongoFieldDescriptor:
    """Emulates database field attributes to support order_by asc/desc expressions."""
    def __init__(self, name):
        self.name = name

    def desc(self):
        return MongoSortOrder(self.name, desc=True)

    def asc(self):
        return MongoSortOrder(self.name, desc=False)

    def __str__(self):
        return self.name


class MongoSortOrder:
    """Represents a sort order expression (descending or ascending)."""
    def __init__(self, field_name, desc=False):
        self.field_name = field_name
        self.is_desc = desc

    def __str__(self):
        return f"{self.field_name} {'DESC' if self.is_desc else 'ASC'}"


class MongoQuery:
    """Helper query class mimicking SQLAlchemy queries."""
    def __init__(self, model_class):
        self.model_class = model_class
        self.collection = db[model_class.collection_name]
        self.filter_dict = {}
        self.sort_fields = []
        self._offset = 0
        self._limit = None

    def filter_by(self, **kwargs):
        for k, v in kwargs.items():
            if k == "id":
                k = "_id"
            if k in ("_id", "provider_id", "api_key_id") and isinstance(v, str) and ObjectId.is_valid(v):
                self.filter_dict[k] = ObjectId(v)
            else:
                self.filter_dict[k] = v
        return self

    def filter(self, *args):
        for arg in args:
            if isinstance(arg, dict):
                self.filter_dict.update(arg)
            elif isinstance(arg, tuple) and len(arg) == 2:
                # E.g., tuple pairs
                self.filter_dict[arg[0]] = arg[1]
        return self

    def order_by(self, *args):
        for arg in args:
            if hasattr(arg, "field_name"):
                self.sort_fields.append((arg.field_name, -1 if arg.is_desc else 1))
            elif isinstance(arg, str):
                if arg.startswith("-"):
                    self.sort_fields.append((arg[1:], -1))
                else:
                    self.sort_fields.append((arg, 1))
            else:
                str_arg = str(arg)
                if "DESC" in str_arg.upper() or "desc" in str_arg:
                    field = str_arg.split(".")[1].split()[0] if "." in str_arg else str_arg.split()[0]
                    self.sort_fields.append((field, -1))
                else:
                    field = str_arg.split(".")[1].split()[0] if "." in str_arg else str_arg.split()[0]
                    self.sort_fields.append((field, 1))
        return self

    def offset(self, val):
        self._offset = val
        return self

    def limit(self, val):
        self._limit = val
        return self

    def count(self):
        return self.collection.count_documents(self.filter_dict)

    def first(self):
        res = self.collection.find_one(self.filter_dict)
        return self.model_class(res) if res else None

    def all(self):
        cursor = self.collection.find(self.filter_dict)
        if self.sort_fields:
            cursor = cursor.sort(self.sort_fields)
        if self._offset:
            cursor = cursor.skip(self._offset)
        if self._limit:
            cursor = cursor.limit(self._limit)
        return [self.model_class(item) for item in cursor]

    def get(self, doc_id):
        if not doc_id:
            return None
        try:
            oid = ObjectId(doc_id) if isinstance(doc_id, str) and ObjectId.is_valid(doc_id) else doc_id
            res = self.collection.find_one({"_id": oid})
            return self.model_class(res) if res else None
        except Exception:
            res = self.collection.find_one({"_id": doc_id})
            return self.model_class(res) if res else None

    def get_or_404(self, doc_id):
        obj = self.get(doc_id)
        if not obj:
            from flask import abort
            abort(404)
        return obj

    def delete(self):
        self.collection.delete_many(self.filter_dict)


class MongoModelMetaclass(type):
    """Metaclass to expose a query property and field descriptors on models."""
    @property
    def query(cls):
        return MongoQuery(cls)

    def __getattr__(cls, name):
        return MongoFieldDescriptor(name)


class MongoModel(metaclass=MongoModelMetaclass):
    """Base wrapper class for MongoDB documents."""
    collection_name = None

    def __init__(self, data=None, **kwargs):
        self._data = data or {}
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getattr__(self, name):
        if name == "id":
            val = self._data.get("_id")
            return str(val) if val else None
        if name in self._data:
            return self._data[name]
        return None

    def __setattr__(self, name, value):
        if name == "_data":
            super().__setattr__(name, value)
        elif name == "id":
            if value:
                self._data["_id"] = ObjectId(value) if isinstance(value, str) and ObjectId.is_valid(value) else value
            else:
                self._data.pop("_id", None)
        else:
            self._data[name] = value

    def save(self):
        col = db[self.collection_name]
        if "_id" in self._data:
            col.replace_one({"_id": self._data["_id"]}, self._data, upsert=True)
        else:
            res = col.insert_one(self._data)
            self._data["_id"] = res.inserted_id
        return self

    def delete(self):
        if "_id" in self._data:
            db[self.collection_name].delete_one({"_id": self._data["_id"]})


# ─────────────────────────────────────────────────────────────────────────────
# User model
# ─────────────────────────────────────────────────────────────────────────────
class User(UserMixin, MongoModel):
    """Admin user model with secure password hashing."""
    collection_name = "users"

    def set_password(self, password: str) -> None:
        """Hash and store password securely."""
        self.password_hash = generate_password_hash(
            password, method="pbkdf2:sha256:600000"
        )

    def check_password(self, password: str) -> bool:
        """Verify password against stored hash."""
        return check_password_hash(self.password_hash, password)

    def is_locked(self) -> bool:
        """Check if account is temporarily locked."""
        if self.locked_until:
            now = datetime.now(timezone.utc)
            locked = self.locked_until
            if locked.tzinfo is None:
                locked = locked.replace(tzinfo=timezone.utc)
            if locked > now:
                return True
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Provider model
# ─────────────────────────────────────────────────────────────────────────────
class Provider(MongoModel):
    """AI provider configuration model."""
    collection_name = "providers"

    @property
    def api_keys(self):
        return APIKey.query.filter_by(provider_id=self.id).all()

    @property
    def logs(self):
        return Log.query.filter_by(provider_id=self.id).all()

    def to_dict(self, include_keys=False) -> dict:
        """Serialize provider to dictionary."""
        import json
        available = self._data.get("available_models", [])
        if isinstance(available, str):
            try:
                available = json.loads(available)
            except Exception:
                available = []
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "default_model": self.default_model,
            "available_models": available,
            "is_enabled": self.is_enabled,
            "is_custom": self.is_custom,
            "priority": self.priority or 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "key_count": len(self.api_keys),
            "active_key_count": sum(1 for k in self.api_keys if k.is_active),
        }


# ─────────────────────────────────────────────────────────────────────────────
# API Key model
# ─────────────────────────────────────────────────────────────────────────────
class APIKey(MongoModel):
    """Encrypted API key storage."""
    collection_name = "api_keys"

    @property
    def provider(self):
        return Provider.query.get(self.provider_id)

    def to_dict(self) -> dict:
        """Serialize key metadata."""
        return {
            "id": self.id,
            "provider_id": str(self.provider_id) if self.provider_id else None,
            "provider_name": self.provider.display_name if self.provider else None,
            "name": self.name or "Unnamed Key",
            "key_preview": self.key_preview or "••••••••",
            "is_active": self.is_active,
            "is_failed": self.is_failed,
            "fail_reason": self.fail_reason,
            "total_requests": self.total_requests or 0,
            "successful_requests": self.successful_requests or 0,
            "failed_requests": self.failed_requests or 0,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "last_tested": self.last_tested.isoformat() if self.last_tested else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Log model
# ─────────────────────────────────────────────────────────────────────────────
class Log(MongoModel):
    """Request/response log model for audit trail and analytics."""
    collection_name = "logs"

    @property
    def provider(self):
        return Provider.query.get(self.provider_id)

    def to_dict(self) -> dict:
        """Serialize log entry to dictionary."""
        return {
            "id": self.id,
            "provider_id": str(self.provider_id) if self.provider_id else None,
            "provider_name": self.provider.display_name if self.provider else "Unknown",
            "api_key_id": str(self.api_key_id) if self.api_key_id else None,
            "model": self.model or "unknown",
            "prompt_preview": self.prompt_preview,
            "response_preview": self.response_preview,
            "status": self.status,
            "error_message": self.error_message,
            "latency_ms": self.latency_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Settings model
# ─────────────────────────────────────────────────────────────────────────────
class Setting(MongoModel):
    """Application settings as key-value pairs."""
    collection_name = "settings"

    @classmethod
    def get(cls, key: str, default=None):
        """Get a setting value by key."""
        setting = db.settings.find_one({"key": key})
        if setting is None:
            return default
        return setting.get("value")

    @classmethod
    def set(cls, key: str, value, description: str = None):
        """Set a setting value, creating if it doesn't exist."""
        db.settings.replace_one(
            {"key": key},
            {
                "key": key,
                "value": str(value) if value is not None else None,
                "description": description,
                "updated_at": utcnow(),
            },
            upsert=True
        )


# ─────────────────────────────────────────────────────────────────────────────
# Chat History model
# ─────────────────────────────────────────────────────────────────────────────
class ChatHistory(MongoModel):
    """Persistent chat history model."""
    collection_name = "chat_history"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "model": self.model,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }