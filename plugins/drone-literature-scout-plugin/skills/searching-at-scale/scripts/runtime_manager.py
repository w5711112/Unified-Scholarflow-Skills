"""Exact-ownership lifecycle manager for an optional temporary SearXNG runtime."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


CommandRunner = Callable[..., object]
UrlProbe = Callable[[str], bool]

DOMESTIC_ENGINE_PROFILE = (
    "360search",
    "baidu",
    "sogou",
    "quark",
    "bing",
    "brave",
)
_DOMESTIC_ENGINE_NAMES = frozenset(DOMESTIC_ENGINE_PROFILE)


def render_searxng_settings(secret_key: str, engines: Sequence[str]) -> str:
    """Render a closed engine allowlist using upstream SearXNG names."""
    if (
        not isinstance(secret_key, str)
        or not secret_key
        or "\n" in secret_key
        or "\r" in secret_key
    ):
        raise ValueError("secret_key must be one non-empty line")
    if isinstance(engines, (str, bytes)) or not isinstance(engines, Sequence):
        raise ValueError("engines must be a non-empty sequence")
    normalized = tuple(engines)
    if not normalized or len(set(normalized)) != len(normalized):
        raise ValueError("engines must be non-empty and unique")
    if any(
        not isinstance(engine, str)
        or engine not in _DOMESTIC_ENGINE_NAMES
        or "\n" in engine
        or "\r" in engine
        for engine in normalized
    ):
        raise ValueError("engines contains an unsupported SearXNG name")
    lines = [
        "use_default_settings:",
        "  engines:",
        "    keep_only:",
    ]
    lines.extend(f"      - {engine}" for engine in normalized)
    lines.extend(
        (
            "server:",
            f'  secret_key: "{secret_key}"',
            '  bind_address: "0.0.0.0"',
            "  port: 8080",
            "search:",
            "  formats:",
            "    - html",
            "    - json",
            "engines:",
        )
    )
    for engine in normalized:
        lines.extend((f"  - name: {engine}", "    disabled: false"))
    lines.append("")
    return "\n".join(lines)


@dataclass(frozen=True)
class ManagedSearxng:
    available: bool
    reason: str | None
    container_id: str | None
    base_url: str | None
    port: int | None
    task_temp_dir: Path


@dataclass(frozen=True)
class CleanupReport:
    container_stopped: bool
    container_absent: bool
    temp_dir_removed: bool
    failures: tuple[str, ...]


def probe_url(base_url: str) -> bool:
    try:
        request = Request(base_url, headers={"User-Agent": "searching-at-scale/1.0"})
        with urlopen(request, timeout=1.0) as response:
            return 200 <= int(response.status) < 500
    except (OSError, URLError, ValueError):
        return False


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class RuntimeManager:
    def __init__(
        self,
        *,
        run_id: str,
        temp_parent: Path | str,
        command_runner: CommandRunner = subprocess.run,
        url_probe: UrlProbe = probe_url,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", run_id):
            raise ValueError("run_id contains unsupported characters")
        self.run_id = run_id
        self.temp_parent = Path(temp_parent).resolve()
        self.temp_parent.mkdir(parents=True, exist_ok=True)
        self._task_temp_dir = Path(
            tempfile.mkdtemp(
                prefix=f"searching-at-scale-{run_id}-", dir=self.temp_parent
            )
        ).resolve()
        self._owned_task_temp_dir = self._task_temp_dir
        self.command_runner = command_runner
        self.url_probe = url_probe
        self.sleep = sleep
        self._container_id: str | None = None
        self._last_cleanup = CleanupReport(True, True, False, ())
        self._cleanup_complete = False

    @property
    def task_temp_dir(self) -> Path:
        return self._task_temp_dir

    def _run(self, arguments: Sequence[str]) -> object:
        return self.command_runner(
            list(arguments),
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )

    @staticmethod
    def _returncode(result: object) -> int:
        value = getattr(result, "returncode", None)
        return int(value) if isinstance(value, int) else 1

    def _managed(
        self,
        *,
        available: bool,
        reason: str | None,
        container_id: str | None = None,
        base_url: str | None = None,
        port: int | None = None,
    ) -> ManagedSearxng:
        return ManagedSearxng(
            available,
            reason,
            container_id,
            base_url,
            port,
            self._task_temp_dir,
        )

    @contextmanager
    def searxng(
        self,
        *,
        image: str = "searxng/searxng:latest",
        engines: Sequence[str] = DOMESTIC_ENGINE_PROFILE,
    ) -> Iterator[ManagedSearxng]:
        if not isinstance(image, str) or not image.strip():
            raise ValueError("image must be non-empty")
        try:
            try:
                docker = self._run(["docker", "version"])
            except OSError:
                docker = None
            if docker is None or self._returncode(docker) != 0:
                yield self._managed(available=False, reason="docker_unavailable")
                return

            image_result = self._run(["docker", "image", "inspect", image])
            if self._returncode(image_result) != 0:
                yield self._managed(available=False, reason="image_unavailable")
                return

            settings_dir = self._task_temp_dir / "settings"
            settings_dir.mkdir(parents=True, exist_ok=False)
            <REDACTED_SECRET>(32)
            (settings_dir / "settings.yml").write_text(
                render_searxng_settings(secret, engines),
                encoding="utf-8",
            )
            port = _free_loopback_port()
            arguments = [
                "docker",
                "run",
                "--rm",
                "--detach",
                "--memory",
                "768m",
                "--cpus",
                "2",
                "--label",
                f"io.openai.searching-at-scale.run-id={self.run_id}",
                "--publish",
                f"127.0.0.1:{port}:8080",
                "--mount",
                f"type=bind,src={settings_dir},dst=/etc/searxng,readonly",
                image,
            ]
            started = self._run(arguments)
            if self._returncode(started) != 0:
                yield self._managed(available=False, reason="container_start_failed")
                return
            container_id = str(getattr(started, "stdout", "")).strip()
            if not re.fullmatch(r"[a-fA-F0-9]{12,64}", container_id):
                yield self._managed(available=False, reason="invalid_container_id")
                return
            self._container_id = container_id
            base_url = f"http://127.0.0.1:{port}"
            healthy = False
            for _ in range(20):
                try:
                    healthy = bool(self.url_probe(base_url))
                except Exception:
                    healthy = False
                if healthy:
                    break
                self.sleep(0.25)
            if not healthy:
                self.cleanup()
                yield self._managed(available=False, reason="healthcheck_failed")
                return
            yield self._managed(
                available=True,
                reason=None,
                container_id=container_id,
                base_url=base_url,
                port=port,
            )
        finally:
            self.cleanup()

    def cleanup(self) -> CleanupReport:
        if self._cleanup_complete:
            return self._last_cleanup
        failures: list[str] = []
        container_stopped = self._container_id is None
        container_absent = self._container_id is None
        if self._container_id is not None:
            container_id = self._container_id
            try:
                stopped = self._run(["docker", "stop", container_id])
                container_stopped = self._returncode(stopped) == 0
                if not container_stopped:
                    failures.append("container_stop_failed")
                inspected = self._run(["docker", "inspect", container_id])
                container_absent = self._returncode(inspected) != 0
                if not container_absent:
                    failures.append("container_still_present")
            except OSError:
                failures.append("container_cleanup_command_failed")
            if container_absent:
                self._container_id = None

        candidate = self._task_temp_dir.resolve()
        owned = self._owned_task_temp_dir.resolve()
        safe = (
            candidate == owned
            and candidate.parent == self.temp_parent
            and candidate.name.startswith(f"searching-at-scale-{self.run_id}-")
        )
        temp_dir_removed = not candidate.exists()
        if candidate.exists() and safe:
            try:
                shutil.rmtree(candidate)
            except OSError:
                failures.append("temp_dir_remove_failed")
            temp_dir_removed = not candidate.exists()
        elif candidate.exists() and not safe:
            failures.append("temp_dir_not_owned")
            temp_dir_removed = False

        report = CleanupReport(
            container_stopped,
            container_absent,
            temp_dir_removed,
            tuple(failures),
        )
        self._last_cleanup = report
        self._cleanup_complete = container_absent and temp_dir_removed
        return report
