from __future__ import annotations

import collections
import hashlib
import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime

from engine import LABEL_OWNER, LABEL_PLATFORM

QUEUE_POLL_SECONDS = 5
KEYS_REFRESH_SECONDS = 30
PROFILE_PREFIX = "agent/"
KEY_ENV = "AGENT_BROKER_KEY"
CONFIG_ENV = "AGENT_CONFIG"
CONFIG_PATH_ENV = "AGENT_CONFIG_PATH"
WRITE_CONFIG = (
    'mkdir -p "$(dirname "$AGENT_CONFIG_PATH")" && '
    'printf "%s" "$AGENT_CONFIG" > "$AGENT_CONFIG_PATH" && exec "$@"'
)
RELAY_PATHS = ("/v1/chat/completions", "/v1/models")


class CapacityError(RuntimeError):
    pass


def pick(requested, allowed):
    """Return the entry of ``allowed`` equal to ``requested``, or None.

    Args:
        requested: value a request asks for.
        allowed: server-side names or paths a request may select.
    """
    return next((entry for entry in allowed if entry == requested), None)


def profile_catalog(roles):
    """Return model name ``agent/<role>`` -> the role's runtime.

    Args:
        roles: agent role of ``agents/roles/`` -> the runtime it runs on.
    """
    return {f"{PROFILE_PREFIX}{role}": runtime for role, runtime in roles.items()}


def resolve(requested, platforms, profiles):
    """Return ``(platform, instance)`` for a requested model: a platform name
    selects that platform's agent, ``agent/<role>`` the role's runtime and an
    agent of its own per role. ``instance`` is None for an unknown model and
    ``platform`` is None for a profile whose runtime this broker does not offer.

    Args:
        requested: the ``model`` of the request.
        platforms: platform name -> spec the broker offers.
        profiles: the result of ``profile_catalog``.
    """
    platform = pick(requested, platforms)
    if platform is not None:
        return platform, platform
    profile = pick(requested, profiles)
    if profile is None:
        return None, None
    runtime = profiles[profile]
    instance = f"{runtime}-{profile[len(PROFILE_PREFIX) :]}"
    return pick(runtime, platforms), instance


def model_list(platforms, profiles):
    """Return the OpenAI ``/v1/models`` entries: every platform, then every
    profile of the catalog.

    Args:
        platforms: platform name -> spec the broker offers.
        profiles: the result of ``profile_catalog``.
    """
    return [
        {"id": name, "object": "model", "owned_by": "agent-broker"}
        for name in [*sorted(platforms), *sorted(profiles)]
    ]


def agent_name(platform, owner):
    digest = hashlib.sha256(owner.encode()).hexdigest()[:16]
    return f"agent-{platform}-{digest}"


_DROP = object()


def _subst(node, subs):
    """Return ``node`` with its ``${name}`` placeholders replaced from ``subs``.

    A string that is exactly ``${context}`` becomes the context value, or
    ``_DROP`` when the context is falsy so the key is left out. Any other
    string has every ``${name}`` interpolated. Dicts and lists recurse, and a
    ``_DROP`` value removes its key or list item.
    """
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            rendered = _subst(value, subs)
            if rendered is not _DROP:
                out[key] = rendered
        return out
    if isinstance(node, list):
        return [r for r in (_subst(v, subs) for v in node) if r is not _DROP]
    if isinstance(node, str):
        if node == "${context}":
            return subs["context"] or _DROP
        result = node
        for name, value in subs.items():
            result = result.replace("${" + name + "}", str(value))
        return result
    return node


def render_config(platform_spec, model, relay_url, key, context):
    """Render a runtime's agent config from the runtime's own declaration.

    The broker holds no runtime list: every runtime declares ``config_render``,
    the agent config as data with ``${model}``, ``${relay_url}``, ``${key}``
    and ``${context}`` placeholders, in its platform spec. The result is JSON,
    which both a JSON runtime and a YAML runtime parse, so the broker needs no
    serializer beyond the standard library.

    Args:
        platform_spec: the runtime's entry from ``AGENT_PLATFORMS``.
        model: the model alias the agent asks the relay for.
        relay_url: the base URL the agent sends model calls to.
        key: the agent's broker key.
        context: the model's context window in tokens, 0 to leave it unset.
    """
    data = _subst(
        platform_spec["config_render"],
        {
            "model": model,
            "relay_url": relay_url,
            "key": key,
            "context": context,
        },
    )
    return json.dumps(data)


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
        queue_timeout: seconds a start waits in the queue for a free slot.
        log: ``log(event, **fields)`` writing one broker log line.
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
        queue_timeout,
        log,
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
        self.queue_timeout = queue_timeout
        self.log = log
        self._slots = threading.Condition()
        self._queue = collections.deque()
        self._starting = 0
        self._locks = {}
        self._locks_guard = threading.Lock()
        self._busy = {}
        self._last_used = {}
        self._keys = {}
        self._keys_guard = threading.Lock()
        self._keys_refreshed = float("-inf")
        self._agent_models = {}

    def _lock_for(self, name):
        with self._locks_guard:
            return self._locks.setdefault(name, threading.Lock())

    def _spec(self, platform, owner, key, instance=None):
        platform_spec = self.platforms[platform]
        name = agent_name(instance or platform, owner)
        entrypoint, cmd = self.engine.image_config(platform_spec["image"])
        command = list(platform_spec["command"]) or cmd
        config = render_config(
            platform_spec, self.model, self.relay_url, key, self.context
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
        last_error = None
        while time.monotonic() < deadline:
            request = urllib.request.Request(url)
            request.add_header("Authorization", f"Bearer {key}")
            try:
                with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 - http:// URL built from the agent name and port
                    if response.status < 400:
                        return
            except (urllib.error.URLError, OSError) as error:
                last_error = error
            time.sleep(2)
        raise TimeoutError(
            f"{name} did not answer {spec['health']} within {self.start_timeout}s"
            f" (last error: {last_error})"
        )

    def _acquire_slot(self, name):
        """Wait in the FIFO start queue until ``name`` is first and a slot is free.

        Args:
            name: the agent waiting for a slot, named in the refusal.
        """
        ticket = object()
        deadline = time.monotonic() + self.queue_timeout
        with self._slots:
            self._queue.append(ticket)
            try:
                while (
                    self._queue[0] is not ticket
                    or self._running_count() + self._starting >= self.max_running
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise CapacityError(
                            f"{self.max_running} agents already running; {name}"
                            f" waited {self.queue_timeout}s in the start queue"
                        )
                    self._slots.wait(min(remaining, QUEUE_POLL_SECONDS))
                self._starting += 1
            finally:
                self._queue.remove(ticket)
                self._slots.notify_all()

    def _release_slot(self):
        with self._slots:
            self._starting -= 1
            self._slots.notify_all()

    def _slot_freed(self):
        with self._slots:
            self._slots.notify_all()

    def ensure(self, platform, owner, instance=None):
        """Return ``(address, key)`` of the caller's running agent; a start
        beyond ``max_running`` waits in the queue in arrival order.

        Args:
            platform: a key of ``platforms``.
            owner: Open WebUI user id of the caller.
            instance: the agent name part from ``resolve``; the platform when None.
        """
        name = agent_name(instance or platform, owner)
        labels = {LABEL_PLATFORM: platform, LABEL_OWNER: owner}
        with self._lock_for(name):
            detail = self.backend.find(name)
            if detail is not None and self.backend.is_running(detail):
                self.backend.network_for(
                    name, labels, self.self_container, self.broker_alias
                )
                key = self._remember(detail)
            else:
                self._acquire_slot(name)
                try:
                    network_id = self.backend.network_for(
                        name, labels, self.self_container, self.broker_alias
                    )
                    if detail is None:
                        detail = self.backend.create(
                            self._spec(
                                platform, owner, secrets.token_urlsafe(32), instance
                            ),
                            network_id,
                        )
                    key = self._remember(detail)
                    if not self.backend.is_running(detail):
                        self.backend.start(detail, network_id)
                finally:
                    self._release_slot()
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
        except (urllib.error.URLError, OSError, ValueError, KeyError) as error:
            self.log(
                "agent_model_fallback", platform=platform, model=model, error=str(error)
            )
        self._agent_models[platform] = model
        return model

    def owner_of_key(self, key):
        """Return ``(owner, platform)`` of the agent holding ``key``, None for
        an unknown key; a miss re-reads the agents at most once per
        ``KEYS_REFRESH_SECONDS``, so unknown keys cannot flood the engine.

        Args:
            key: the bearer key an agent presented to the relay.
        """
        if key not in self._keys:
            with self._keys_guard:
                now = time.monotonic()
                if (
                    key not in self._keys
                    and now - self._keys_refreshed >= KEYS_REFRESH_SECONDS
                ):
                    for detail in self.backend.list_agents():
                        self._remember(detail)
                    self._keys_refreshed = now
        return self._keys.get(key)

    def begin(self, platform, owner):
        name = agent_name(platform, owner)
        with self._locks_guard:
            self._busy[name] = self._busy.get(name, 0) + 1
        return name

    def end(self, name):
        with self._locks_guard:
            self._busy[name] = max(self._busy.get(name, 1) - 1, 0)
            self._last_used[name] = time.monotonic()

    def stop_owner(self, platform, owner):
        detail = self.backend.find(agent_name(platform, owner))
        if detail is not None and self.backend.is_running(detail):
            self.backend.stop(detail)
            self._slot_freed()

    def _idle_seconds_of(self, name, detail):
        last = self._last_used.get(name)
        if last is not None:
            return time.monotonic() - last
        return time.time() - _parse_time(self.backend.started_at(detail))

    def reap(self):
        if not self.idle_stop:
            return
        for detail in self.backend.list_agents():
            if not self.backend.is_running(detail):
                continue
            name = detail.get("Name", "").lstrip("/") or (detail.get("Spec") or {}).get(
                "Name", ""
            )
            if (
                self._busy.get(name)
                or self._idle_seconds_of(name, detail) < self.idle_seconds
            ):
                continue
            with self._lock_for(name):
                current = self.backend.find(name)
                if current is None or not self.backend.is_running(current):
                    continue
                if (
                    self._busy.get(name)
                    or self._idle_seconds_of(name, current) < self.idle_seconds
                ):
                    continue
                self.backend.stop(current)
                self._last_used.pop(name, None)
            self._slot_freed()
