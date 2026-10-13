"""LLM access.

Aika AI (the default) and every OpenAI-compatible provider speak the same wire
format, so a single streaming implementation with no third-party SDK covers
all of them.

Cancellation is cooperative: the caller owns a :class:`CancelToken`, the token
is checked between streamed chunks, and closing the socket is used to unblock
the read immediately.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from . import paths, prompts
from . import __version__
from .config import Config
from .logger import logger
from .models import World

DEBUG = bool(os.environ.get("VOLT_PY_DEBUG"))
REQUEST_TIMEOUT = 600


class CancelToken:
    """Cancels one generation."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._closers: List[Any] = []

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()
        with self._lock:
            closers = list(self._closers)
        for closer in closers:
            try:
                closer()
            except Exception:
                pass

    def reset(self) -> None:
        with self._lock:
            self._closers.clear()
        self._event.clear()

    def attach(self, closer: Any) -> None:
        with self._lock:
            self._closers.append(closer)

    def detach(self) -> None:
        with self._lock:
            self._closers.clear()


class GenerationResult:
    def __init__(
        self,
        data: Any = None,
        error: str = "",
        canceled: bool = False,
    ) -> None:
        self.data = data
        self.error = error
        self.canceled = canceled

    @property
    def ok(self) -> bool:
        return self.data is not None and not self.canceled

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        if self.canceled:
            return "GenerationResult(canceled)"
        if self.error:
            return "GenerationResult(error=%r)" % self.error
        return "GenerationResult(ok, type=%s)" % type(self.data).__name__


class Engine:
    def __init__(self, config: Config) -> None:
        self._config = config

    # -- public API ---------------------------------------------------------

    def generate_world(self, summary: str, token: CancelToken) -> GenerationResult:
        result = self._complete(
            prompts.world_generation_system_prompt(),
            prompts.world_generation_user_prompt(summary),
            token,
        )
        if not result.ok or not isinstance(result.data, dict):
            return result
        world = World.from_json(result.data)
        if world.id:
            world.save_path = None
        self._dump("world_generation", result.data)
        return GenerationResult(world)

    def generate_player_action_event(
        self, command: str, world: World, token: CancelToken
    ) -> GenerationResult:
        context_json = _encode(world.to_player_action_info(command))
        player_result = self._complete(
            prompts.player_action_event_generation_system_prompt(),
            prompts.player_action_event_generation_user_prompt(context_json),
            token,
        )
        if not player_result.ok or not isinstance(player_result.data, dict):
            return player_result

        player_event = player_result.data
        self._dump("player_action", player_event)

        command_type = str(player_event.get("commandType") or "")
        action_scale = str(player_event.get("actionScale") or "")
        if command_type == "meta_question" or action_scale == "none":
            return GenerationResult({"playerEvent": player_event})

        seconds = 0
        for state in player_event.get("stateChanges") or []:
            if isinstance(state, dict):
                parsed = world.parse_seconds_from_advance_time(state)
                if parsed is not None:
                    seconds = parsed
                    break

        event_info = world.to_event_info()
        event_info["timePassed"] = seconds
        event_info["playerEvent"] = player_event

        local_result = self._complete(
            prompts.local_event_generation_system_prompt(),
            prompts.local_event_generation_user_prompt(_encode(event_info)),
            token,
        )
        if not local_result.ok or not isinstance(local_result.data, dict):
            return local_result

        self._dump("local_event", local_result.data)
        return GenerationResult(
            {"playerEvent": player_event, "localEvent": local_result.data}
        )

    def generate_local_event(
        self, seconds: int, world: World, token: CancelToken
    ) -> GenerationResult:
        info = world.to_event_info()
        info["timePassed"] = seconds
        result = self._complete(
            prompts.local_event_generation_system_prompt(),
            prompts.local_event_generation_user_prompt(_encode(info)),
            token,
        )
        if result.ok and isinstance(result.data, dict):
            self._dump("local_event", result.data)
        return result

    def generate_world_event(
        self, world: World, token: CancelToken
    ) -> GenerationResult:
        result = self._complete(
            prompts.world_event_generation_system_prompt(),
            prompts.world_event_generation_user_prompt(_encode(world.to_event_info())),
            token,
        )
        if result.ok and isinstance(result.data, dict):
            self._dump("world_event", result.data)
        return result

    def check_provider(self) -> Optional[str]:
        """Return a human readable problem with the provider setup, if any."""
        url, api_key, model = self._config.provider_endpoint()
        if not url:
            return "providerUrlMissing"
        if not api_key:
            return "apiKeyMissing"
        if not model:
            return "modelMissing"
        return None

    def list_models(self) -> List[Tuple[str, str]]:
        """``(api_id, display name)`` pairs published by the provider.

        The request body has to carry the api id (``gpt-4o``), while the list
        endpoint shows a friendlier name (``ChatGPT-4o``), so both are kept.
        """
        url = self._config.models_url()
        api_key = self._config.api_key
        if not url or not api_key:
            return []
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer %s" % api_key,
                "User-Agent": "Volt.py/%s" % __version__,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            logger.warning("Model listing failed -> %s" % error.code)
            return []
        except Exception as error:
            logger.exception("Model listing failed", error)
            return []

        entries = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            return []
        models: List[Tuple[str, str]] = []
        seen = set()
        for item in entries:
            if not isinstance(item, dict):
                continue
            api_id = item.get("api_id") or item.get("id")
            label = item.get("id") or item.get("api_id")
            if not isinstance(api_id, str) or not api_id or api_id in seen:
                continue
            seen.add(api_id)
            title = label if isinstance(label, str) and label else api_id
            models.append((api_id, title))
        return models

    # -- transport ----------------------------------------------------------

    def _complete(
        self, system: str, user: str, token: CancelToken
    ) -> GenerationResult:
        problem = self.check_provider()
        if problem:
            return GenerationResult(error=problem)

        url, api_key, model = self._config.provider_endpoint()
        payload: Dict[str, Any] = {
            "model": model,
            "temperature": self._config.get_float("temperature"),
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }

        result = self._stream(url, api_key, payload, token)
        if result.error == "responseFormatRejected" and not result.canceled:
            logger.warning("Provider rejected response_format, retrying without it")
            payload.pop("response_format", None)
            result = self._stream(url, api_key, payload, token)

        if result.canceled:
            return result
        if result.error:
            return result

        raw = result.data if isinstance(result.data, str) else ""
        try:
            parsed = extract_json_object(raw)
        except ValueError as error:
            return GenerationResult(error="badJson: %s" % error)
        self._dump("raw", raw)
        return GenerationResult(parsed)

    def _stream(
        self, url: str, api_key: str, payload: Dict[str, Any], token: CancelToken
    ) -> GenerationResult:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Authorization": "Bearer %s" % api_key,
                "User-Agent": "Volt.py/%s" % __version__,
            },
            method="POST",
        )

        chunks: List[str] = []
        response = None
        try:
            response = urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT)
            token.attach(response.close)
            while True:
                if token.cancelled:
                    return GenerationResult(canceled=True)
                line = response.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if not text.startswith("data:"):
                    continue
                data = text[5:].strip()
                if not data or data == "[DONE]":
                    if data == "[DONE]":
                        break
                    continue
                content = _delta_content(data)
                if content:
                    chunks.append(content)
        except urllib.error.HTTPError as error:
            body = _read_error_body(error)
            if error.code == 400 and "response_format" in body:
                return GenerationResult(error="responseFormatRejected")
            if error.code in (401, 403):
                return GenerationResult(error="authFailed")
            return GenerationResult(error="http%d: %s" % (error.code, body[:300]))
        except urllib.error.URLError as error:
            if token.cancelled:
                return GenerationResult(canceled=True)
            return GenerationResult(error="network: %s" % error.reason)
        except Exception as error:
            if token.cancelled:
                return GenerationResult(canceled=True)
            return GenerationResult(error="stream: %r" % error)
        finally:
            token.detach()
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass

        # Closing the socket from cancel() ends readline() with EOF, so the
        # cancellation flag has to be re-checked before using what we received.
        if token.cancelled:
            return GenerationResult(canceled=True)

        content = "".join(chunks).strip()
        if not content:
            return GenerationResult(error="emptyResponse")
        return GenerationResult(content)

    def _dump(self, name: str, payload: Any) -> None:
        if not DEBUG:
            return
        try:
            paths.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            target = paths.DEBUG_DIR / ("%s.json" % name)
            target.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError:
            pass


def extract_json_object(text: str) -> Dict[str, Any]:
    """Parse a JSON object, tolerating markdown fences and stray prose."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1] if "```" in cleaned[3:] else cleaned[3:]
        if cleaned.lstrip().lower().startswith("json"):
            cleaned = cleaned.lstrip()[4:]
    try:
        parsed = json.loads(cleaned)
    except ValueError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object in response")
        parsed = json.loads(cleaned[start:end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("response is not a JSON object")
    return parsed


def _delta_content(payload: str) -> str:
    try:
        chunk = json.loads(payload)
    except ValueError:
        return ""
    choices = chunk.get("choices") if isinstance(chunk, dict) else None
    if not choices:
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    return content if isinstance(content, str) else ""


def _read_error_body(error: urllib.error.HTTPError) -> str:
    try:
        return error.read().decode("utf-8", errors="replace")
    except Exception:
        return str(error)


def _encode(payload: Any) -> str:
    return json.dumps(payload, indent=4, ensure_ascii=False, default=str)