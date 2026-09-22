from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from engine import LABEL_OWNER, LABEL_PLATFORM

KEY_ENV = "AGENT_BROKER_KEY"
CONFIG_ENV = "AGENT_CONFIG"
CONFIG_PATH_ENV = "AGENT_CONFIG_PATH"
WRITE_CONFIG = (
    'mkdir -p "$(dirname "$AGENT_CONFIG_PATH")" && '
    'printf "%s" "$AGENT_CONFIG" > "$AGENT_CONFIG_PATH" && exec "$@"'
)


class CapacityError(RuntimeError):
    pass


def agent_name(platform, owner):
    digest = hashlib.sha256(owner.encode()).hexdigest()[:16]
    return f"agent-{platform}-{digest}"


def hermes_config(model, relay_url, key, context):
    lines = [
        "model:",
        f"  default: {json.dumps(model)}",
        "  provider: custom",
        f"  base_url: {json.dumps(relay_url)}",
        f"  api_key: {json.dumps(key)}",
    ]
    if context:
        lines.append(f"  context_length: {context}")
    lines += ["mcp_servers: {}", ""]
    return "\n".join(lines)


def openclaw_config(model, relay_url, key, context):
    entry = {"id": model, "name": model}
    if context:
        entry["contextWindow"] = context
    return json.dumps(
        {
            "gateway": {
                "mode": "local",
                "http": {"endpoints": {"chatCompletions": {"enabled": True}}},
            },
            "agents": {"defaults": {"model": {"primary": f"broker/{model}"}}},
            "models": {
                "providers": {
                    "broker": {
                        "baseUrl": relay_url,
                        "apiKey": key,
                        "api": "openai-completions",
                        "models": [entry],
                    }
                }
            },
        }
    )


CONFIG_RENDERERS = {"hermes": hermes_config, "openclaw": openclaw_config}


def _env_value(env, name):
    prefix = f"{name}="
    return next((item[len(prefix) :] for item in env if item.startswith(prefix)), "")


def _parse_time(value):
    try:
        return datetime.fromisoformat(value[:19] + "+00:00").timestamp()
    except ValueError:
        return 0.0


class Agents:
    """
    Args:
        backend: :class:`engine.ComposeBackend` or :class:`engine.SwarmBackend`.
        engine: the :class:`engine.Engine` behind it.
        platforms: platform name -> spec from ``AGENT_PLATFORMS``.
        self_container: the broker's own container, joined to each agent network.
        broker_alias: name agents resolve the broker by.
        relay_url: base URL agents send model calls to.
        model: model alias every agent asks the relay for.
        context: context window of that model in tokens; 0 leaves it to the agent.
        idle_stop: whether idle agents are stopped.
        idle_seconds: idle time before a stop.
        max_running: bound on concurrently running agents.
        start_timeout: seconds an agent gets to answer its health endpoint.
    """

    def __init__(
        self,
        backend,
        engine,
        platforms,
        self_container,
        broker_alias,
        relay_url,
        model,
        context,
        idle_stop,
        idle_seconds,
        max_running,
        start_timeout,
    ):
        self.backend = backend
        self.engine = engine
        self.platforms = platforms
        self.self_container = self_container
        self.broker_alias = broker_alias
        self.relay_url = relay_url
        self.model = model
        self.context = context
        self.idle_stop = idle_stop
        self.idle_seconds = idle_seconds
        self.max_running = max_running
        self.start_timeout = start_timeout
        self._locks = {}
        self._locks_guard = threading.Lock()
        self._last_used = {}
        self._keys = {}
        self._agent_models = {}

    def _lock_for(self, name):
        with self._locks_guard:
            return self._locks.setdefault(name, threading.Lock())

    def _spec(self, platform, owner, key):
        platform_spec = self.platforms[platform]
        name = agent_name(platform, owner)
        entrypoint, cmd = self.engine.image_config(platform_spec["image"])
        command = list(platform_spec["command"]) or cmd
        config = CONFIG_RENDERERS[platform](
            self.model, self.relay_url, key, self.context
        )
        env = [f"{k}={v}" for k, v in sorted(platform_spec["env"].items())]
        env += [
            f"{platform_spec['key_env']}={key}",
            f"{KEY_ENV}={key}",
            f"{CONFIG_ENV}={config}",
            f"{CONFIG_PATH_ENV}={platform_spec['config_path']}",
        ]
        return {
            "name": name,
            "network": name,
            "volume": name,
            "image": platform_spec["image"],
            "entrypoint": ["/bin/sh", "-c", WRITE_CONFIG, "agent"],
            "cmd": [str(part) for part in entrypoint + command],
            "env": env,
            "labels": {LABEL_PLATFORM: platform, LABEL_OWNER: owner},
            "data": platform_spec["data"],
            "user": platform_spec["user"],
            "nano_cpus": int(float(platform_spec["cpus"]) * 1_000_000_000),
            "memory": int(platform_spec["mem_limit"]),
            "memory_reservation": int(platform_spec["mem_reservation"]),
            "pids": int(platform_spec["pids_limit"]),
        }

    def _running_count(self):
        return sum(
            1
            for detail in self.backend.list_agents()
            if self.backend.is_running(detail)
        )

    def _remember(self, detail):
        labels = self.backend.labels_of(detail)
        key = _env_value(self.backend.env_of(detail), KEY_ENV)
        if key:
            self._keys[key] = (
                labels.get(LABEL_OWNER, ""),
                labels.get(LABEL_PLATFORM, ""),
            )
        return key

    def _wait_healthy(self, platform, name, key):
        spec = self.platforms[platform]
        url = f"http://{name}:{spec['port']}{spec['health']}"
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            request = urllib.request.Request(url)
            request.add_header("Authorization", f"Bearer {key}")
            try:
                with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - http:// URL built from the agent name and port
                    if response.status < 400:
                        return
            except (urllib.error.URLError, OSError):
                pass
            time.sleep(2)
        raise TimeoutError(
            f"{name} did not answer {spec['health']} within {self.start_timeout}s"
        )

    def ensure(self, platform, owner):
        """Return ``(address, key)`` of the caller's running agent.

        Args:
            platform: ``hermes`` or ``openclaw``.
            owner: Open WebUI user id of the caller.
        """
        name = agent_name(platform, owner)
        with self._lock_for(name):
            detail = self.backend.find(name)
            if detail is None:
                if self._running_count() >= self.max_running:
                    raise CapacityError(f"{self.max_running} agents already running")
                key = secrets.token_urlsafe(32)
                network_id = self.engine.ensure_network(
                    name,
                    self.backend.network_driver,
                    {LABEL_PLATFORM: platform, LABEL_OWNER: owner},
                )
                self.engine.connect(network_id, self.self_container, self.broker_alias)
                detail = self.backend.create(
                    self._spec(platform, owner, key), network_id
                )
            else:
                network_id = self.engine.ensure_network(
                    name,
                    self.backend.network_driver,
                    {LABEL_PLATFORM: platform, LABEL_OWNER: owner},
                )
                self.engine.connect(network_id, self.self_container, self.broker_alias)
            key = self._remember(detail)
            if not self.backend.is_running(detail):
                if self._running_count() >= self.max_running:
                    raise CapacityError(f"{self.max_running} agents already running")
                self.backend.start(detail)
            self._wait_healthy(platform, name, key)
            self._last_used[name] = time.monotonic()
            return f"http://{name}:{self.platforms[platform]['port']}", key

    def agent_model(self, platform, address, key):
        if platform in self._agent_models:
            return self._agent_models[platform]
        request = urllib.request.Request(f"{address}/v1/models")  # noqa: S310 - http:// URL built from the agent name and port
        request.add_header("Authorization", f"Bearer {key}")
        model = self.platforms[platform]["request_model"]
        try:
            with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - http:// URL built from the agent name and port
                listed = json.loads(response.read()).get("data") or []
                if listed:
                    model = listed[0]["id"]
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            pass
        self._agent_models[platform] = model
        return model

    def owner_of_key(self, key):
        if key not in self._keys:
            for detail in self.backend.list_agents():
                self._remember(detail)
        return self._keys.get(key)

    def stop_owner(self, platform, owner):
        detail = self.backend.find(agent_name(platform, owner))
        if detail is not None and self.backend.is_running(detail):
            self.backend.stop(detail)

    def reap(self):
        if not self.idle_stop:
            return
        now = time.monotonic()
        wall = time.time()
        for detail in self.backend.list_agents():
            if not self.backend.is_running(detail):
                continue
            name = detail.get("Name", "").lstrip("/") or (detail.get("Spec") or {}).get(
                "Name", ""
            )
            last = self._last_used.get(name)
            idle = (
                now - last
                if last is not None
                else wall - _parse_time(self.backend.started_at(detail))
            )
            if idle >= self.idle_seconds:
                with self._lock_for(name):
                    self.backend.stop(detail)
                    self._last_used.pop(name, None)
