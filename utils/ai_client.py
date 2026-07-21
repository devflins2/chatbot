"""
Unified AI client that abstracts communication with multiple AI providers.
Handles provider selection, key rotation, fallback, and error handling.
"""

import json
import time
import logging
import requests
from datetime import datetime, timezone
from typing import Optional, Generator

from models.database import db, Provider, APIKey, Log, Setting
from utils.encryption import decrypt_api_key

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


class AIClientError(Exception):
    """Custom exception for AI client errors."""
    def __init__(self, message: str, provider: str = None, status_code: int = None):
        super().__init__(message)
        self.provider = provider
        self.status_code = status_code


class AIClient:
    """
    Unified client for all supported AI providers.
    Implements provider selection, failover, and request logging.
    """

    def __init__(self):
        self.timeout = int(Setting.get("api_timeout", 30))
        self.max_tokens = int(Setting.get("max_tokens", 2048))
        self.temperature = float(Setting.get("temperature", 0.7))
        self.top_p = float(Setting.get("top_p", 1.0))
        self.system_prompt = Setting.get("system_prompt", "You are a helpful AI assistant.")
        self.streaming = Setting.get("streaming_enabled", "true").lower() == "true"

    # ──────────────────────────────────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────────────────────────────────

    def chat(
        self,
        message: str,
        chat_history: list = None,
        provider_id: int = None,
        model: str = None,
        stream: bool = False,
        ip_address: str = None,
    ) -> dict:
        """
        Send a chat message and return the response.
        Automatically selects provider and handles failover.
        """
        chat_history = chat_history or []
        start_time = time.time()
        log_entry = None

        # Select provider(s) to try
        providers_to_try = self._select_providers(provider_id)
        if not providers_to_try:
            raise AIClientError("No enabled providers with active keys available.")

        last_error = None
        for provider in providers_to_try:
            api_key_obj = self._get_active_key(provider)
            if not api_key_obj:
                continue

            try:
                raw_key = decrypt_api_key(api_key_obj.encrypted_key)
                selected_model = model or provider.default_model
                messages = self._build_messages(message, chat_history)

                result = self._call_provider(
                    provider=provider,
                    api_key=raw_key,
                    messages=messages,
                    model=selected_model,
                    stream=stream,
                )

                latency = int((time.time() - start_time) * 1000)
                self._record_success(api_key_obj, provider, selected_model,
                                     message, result, latency, ip_address)
                return result

            except AIClientError as e:
                last_error = e
                latency = int((time.time() - start_time) * 1000)
                self._record_failure(api_key_obj, provider,
                                     model or provider.default_model,
                                     message, str(e), latency, ip_address)
                logger.warning(f"Provider {provider.name} failed: {e}")
                # Mark key as failed for persistent errors
                if e.status_code in (401, 403):
                    self._mark_key_failed(api_key_obj, str(e))
                continue

        raise AIClientError(
            f"All providers failed. Last error: {last_error}",
            provider="all",
        )

    def chat_stream(
        self,
        message: str,
        chat_history: list = None,
        provider_id: int = None,
        model: str = None,
        ip_address: str = None,
    ) -> Generator[str, None, None]:
        """
        Stream chat response as Server-Sent Events.
        Yields chunks of text as they arrive.
        """
        chat_history = chat_history or []
        start_time = time.time()

        providers_to_try = self._select_providers(provider_id)
        if not providers_to_try:
            yield f"data: {json.dumps({'error': 'No providers available'})}\n\n"
            return

        for provider in providers_to_try:
            api_key_obj = self._get_active_key(provider)
            if not api_key_obj:
                continue

            try:
                raw_key = decrypt_api_key(api_key_obj.encrypted_key)
                selected_model = model or provider.default_model
                messages = self._build_messages(message, chat_history)

                full_response = ""
                for chunk in self._stream_provider(provider, raw_key, messages, selected_model):
                    full_response += chunk
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"

                latency = int((time.time() - start_time) * 1000)
                result = {"response": full_response, "model": selected_model,
                          "provider": provider.name}
                self._record_success(api_key_obj, provider, selected_model,
                                     message, result, latency, ip_address)
                yield f"data: {json.dumps({'done': True, 'provider': provider.name, 'model': selected_model})}\n\n"
                return

            except Exception as e:
                logger.warning(f"Stream failed for {provider.name}: {e}")
                continue

        yield f"data: {json.dumps({'error': 'All providers failed'})}\n\n"

    # ──────────────────────────────────────────────────────────────────────────
    # Provider selection
    # ──────────────────────────────────────────────────────────────────────────

    def _select_providers(self, provider_id: int = None) -> list:
        """Select providers to try, ordered by priority."""
        if provider_id:
            p = Provider.query.filter_by(id=provider_id, is_enabled=True).first()
            return [p] if p else []

        strategy = Setting.get("selection_strategy", "priority")
        providers = Provider.query.filter_by(is_enabled=True).order_by(
            Provider.priority.asc()
        ).all()

        if strategy == "random":
            import random
            random.shuffle(providers)

        return providers

    def _get_active_key(self, provider: Provider) -> Optional[APIKey]:
        """Get an active, non-failed API key for the given provider."""
        return APIKey.query.filter_by(
            provider_id=provider.id,
            is_active=True,
            is_failed=False,
        ).order_by(APIKey.total_requests.asc()).first()

    # ──────────────────────────────────────────────────────────────────────────
    # Message building
    # ──────────────────────────────────────────────────────────────────────────

    def _build_messages(self, message: str, chat_history: list) -> list:
        """Build the messages array with system prompt and history."""
        max_context = int(Setting.get("max_context_length", 10))
        system_prompt = Setting.get("system_prompt", "You are a helpful AI assistant.")

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        # Limit history to max_context turns (each turn = 1 message)
        limited_history = chat_history[-(max_context * 2):]
        for entry in limited_history:
            if isinstance(entry, dict) and "role" in entry and "content" in entry:
                messages.append({
                    "role": entry["role"],
                    "content": str(entry["content"])[:4000],  # Limit per message
                })

        messages.append({"role": "user", "content": message})
        return messages

    # ──────────────────────────────────────────────────────────────────────────
    # Provider-specific call implementations
    # ──────────────────────────────────────────────────────────────────────────

    def _call_provider(self, provider: Provider, api_key: str,
                       messages: list, model: str, stream: bool = False) -> dict:
        """Route to the correct provider implementation."""
        ptype = provider.provider_type

        if ptype == "anthropic":
            return self._call_anthropic(provider, api_key, messages, model)
        elif ptype == "huggingface":
            return self._call_huggingface(provider, api_key, messages, model)
        elif ptype in ("openai", "groq", "openrouter", "deepseek",
                       "mistral", "google_gemini", "custom"):
            return self._call_openai_compatible(provider, api_key, messages, model)
        else:
            return self._call_openai_compatible(provider, api_key, messages, model)

    def _call_openai_compatible(self, provider: Provider, api_key: str,
                                 messages: list, model: str) -> dict:
        """Call any OpenAI-compatible API endpoint."""
        base_url = provider.base_url or "https://api.openai.com/v1"
        url = f"{base_url.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # OpenRouter requires additional headers
        if provider.provider_type == "openrouter":
            headers["HTTP-Referer"] = "https://ai-dashboard.local"
            headers["X-Title"] = "AI Dashboard"

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
        }

        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=self.timeout
            )
        except requests.Timeout:
            raise AIClientError("Request timed out", provider=provider.name)
        except requests.ConnectionError as e:
            raise AIClientError(f"Connection error: {e}", provider=provider.name)

        if resp.status_code != 200:
            raise AIClientError(
                f"API error {resp.status_code}: {resp.text[:200]}",
                provider=provider.name,
                status_code=resp.status_code,
            )

        data = resp.json()
        response_text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})

        return {
            "response": response_text,
            "model": model,
            "provider": provider.name,
            "provider_display": provider.display_name,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }

    def _call_anthropic(self, provider: Provider, api_key: str,
                        messages: list, model: str) -> dict:
        """Call the Anthropic Claude API."""
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # Extract system prompt and user messages separately
        system_content = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                user_messages.append(msg)

        payload = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": user_messages,
        }
        if system_content:
            payload["system"] = system_content

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.Timeout:
            raise AIClientError("Request timed out", provider=provider.name)
        except requests.ConnectionError as e:
            raise AIClientError(f"Connection error: {e}", provider=provider.name)

        if resp.status_code != 200:
            raise AIClientError(
                f"Anthropic API error {resp.status_code}: {resp.text[:200]}",
                provider=provider.name,
                status_code=resp.status_code,
            )

        data = resp.json()
        response_text = data["content"][0]["text"]
        usage = data.get("usage", {})

        return {
            "response": response_text,
            "model": model,
            "provider": provider.name,
            "provider_display": provider.display_name,
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
            "total_tokens": (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)),
        }

    def _call_huggingface(self, provider: Provider, api_key: str,
                           messages: list, model: str) -> dict:
        """Call the HuggingFace Inference API."""
        base_url = provider.base_url or "https://api-inference.huggingface.co/models"
        url = f"{base_url.rstrip('/')}/{model}"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Build a simple prompt from messages
        prompt = "\n".join(
            f"{m['role'].capitalize()}: {m['content']}"
            for m in messages
            if m["role"] != "system"
        )
        prompt += "\nAssistant:"

        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": self.max_tokens,
                "temperature": self.temperature,
                "return_full_text": False,
            },
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.Timeout:
            raise AIClientError("Request timed out", provider=provider.name)
        except requests.ConnectionError as e:
            raise AIClientError(f"Connection error: {e}", provider=provider.name)

        if resp.status_code != 200:
            raise AIClientError(
                f"HuggingFace API error {resp.status_code}: {resp.text[:200]}",
                provider=provider.name,
                status_code=resp.status_code,
            )

        data = resp.json()
        if isinstance(data, list) and data:
            response_text = data[0].get("generated_text", "")
        else:
            response_text = str(data)

        return {
            "response": response_text,
            "model": model,
            "provider": provider.name,
            "provider_display": provider.display_name,
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
        }

    def _stream_provider(self, provider: Provider, api_key: str,
                          messages: list, model: str) -> Generator[str, None, None]:
        """Stream from an OpenAI-compatible endpoint."""
        base_url = provider.base_url or "https://api.openai.com/v1"
        url = f"{base_url.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if provider.provider_type == "openrouter":
            headers["HTTP-Referer"] = "https://ai-dashboard.local"
            headers["X-Title"] = "AI Dashboard"

        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": True,
        }

        with requests.post(url, headers=headers, json=payload,
                           stream=True, timeout=self.timeout) as resp:
            if resp.status_code != 200:
                raise AIClientError(
                    f"API error {resp.status_code}",
                    provider=provider.name,
                    status_code=resp.status_code,
                )
            for line in resp.iter_lines():
                if line:
                    line = line.decode("utf-8")
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue

    # ──────────────────────────────────────────────────────────────────────────
    # Logging and key management
    # ──────────────────────────────────────────────────────────────────────────

    def _record_success(self, key_obj: APIKey, provider: Provider, model: str,
                        message: str, result: dict, latency: int, ip: str):
        """Record successful request in logs and update key stats."""
        key_obj.total_requests = (key_obj.total_requests or 0) + 1
        key_obj.successful_requests = (key_obj.successful_requests or 0) + 1
        key_obj.last_used = utcnow()
        key_obj.is_failed = False
        key_obj.save()

        log = Log(
            provider_id=provider.id,
            api_key_id=key_obj.id,
            model=model,
            prompt_preview=str(message)[:500],
            response_preview=str(result.get("response", ""))[:500],
            status="success",
            latency_ms=latency,
            prompt_tokens=result.get("prompt_tokens"),
            completion_tokens=result.get("completion_tokens"),
            total_tokens=result.get("total_tokens"),
            ip_address=ip,
        )
        log.save()

    def _record_failure(self, key_obj: APIKey, provider: Provider, model: str,
                        message: str, error: str, latency: int, ip: str):
        """Record failed request in logs and update key stats."""
        key_obj.total_requests = (key_obj.total_requests or 0) + 1
        key_obj.failed_requests = (key_obj.failed_requests or 0) + 1
        key_obj.save()

        log = Log(
            provider_id=provider.id,
            api_key_id=key_obj.id,
            model=model,
            prompt_preview=str(message)[:500],
            status="failed",
            error_message=error,
            latency_ms=latency,
            ip_address=ip,
        )
        log.save()

    def _mark_key_failed(self, key_obj: APIKey, reason: str):
        """Mark an API key as permanently failed (e.g., invalid credentials)."""
        key_obj.is_failed = True
        key_obj.fail_reason = reason
        key_obj.save()


def test_api_key(provider: Provider, encrypted_key: str) -> dict:
    """
    Test an API key with a simple request.
    Returns {'success': bool, 'message': str, 'latency_ms': int}
    """
    start = time.time()
    try:
        raw_key = decrypt_api_key(encrypted_key)
        client = AIClient()
        test_messages = [{"role": "user", "content": "Say 'OK' in one word."}]

        if provider.provider_type == "anthropic":
            result = client._call_anthropic(
                provider, raw_key, test_messages, provider.default_model or "claude-3-haiku-20240307"
            )
        elif provider.provider_type == "huggingface":
            result = client._call_huggingface(
                provider, raw_key, test_messages,
                provider.default_model or "mistralai/Mistral-7B-Instruct-v0.3"
            )
        else:
            result = client._call_openai_compatible(
                provider, raw_key, test_messages, provider.default_model or "gpt-3.5-turbo"
            )

        latency = int((time.time() - start) * 1000)
        return {"success": True, "message": "Key is valid and working", "latency_ms": latency}

    except AIClientError as e:
        latency = int((time.time() - start) * 1000)
        return {"success": False, "message": str(e), "latency_ms": latency}
    except Exception as e:
        latency = int((time.time() - start) * 1000)
        return {"success": False, "message": f"Unexpected error: {str(e)}", "latency_ms": latency}