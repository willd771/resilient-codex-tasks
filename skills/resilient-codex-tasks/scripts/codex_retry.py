#!/usr/bin/env python3
"""Run a Codex CLI task with persisted retries for transient provider failures."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_DELAYS = "15,30,60,120,240,300"
RESUME_PROMPT = (
    "The previous invocation ended after a transient provider error. Continue the same task "
    "from the existing repository and session. Inspect the current state first and do not "
    "repeat completed state-changing work."
)


class FailureKind(Enum):
    TRANSIENT = "transient"
    QUOTA_EXHAUSTED = "quota_exhausted"
    NON_RETRYABLE = "non_retryable"


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    detail: str


def classify_failure(output: str) -> Failure:
    """Classify only documented provider failures as retryable."""
    normalized = output.lower()
    has_403 = bool(re.search(r"\b403\b", normalized))
    quota_markers = (
        "insufficient_quota",
        "insufficient quota",
        "quota exhausted",
        "quota exceeded",
        "balance exhausted",
        "balance insufficient",
        "billing_hard_limit_reached",
        "余额不足",
        "额度不足",
        "配额不足",
    )
    if has_403 and any(marker in normalized for marker in quota_markers):
        return Failure(FailureKind.QUOTA_EXHAUSTED, "Codex balance or quota is exhausted.")

    transient_markers = (
        "429",
        "502",
        "503",
        "too many requests",
        "rate limit",
        "bad gateway",
        "service unavailable",
    )
    if any(marker in normalized for marker in transient_markers):
        return Failure(FailureKind.TRANSIENT, "Transient Codex provider failure.")
    return Failure(FailureKind.NON_RETRYABLE, "Codex returned a non-retryable failure.")


def extract_thread_id(jsonl_output: str) -> Optional[str]:
    """Extract the thread ID emitted by `codex exec --json`."""
    for line in jsonl_output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") not in {"thread.started", "session.started"}:
            continue
        for key in ("thread_id", "session_id"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        thread = event.get("thread")
        if isinstance(thread, dict):
            for key in ("id", "thread_id", "session_id"):
                value = thread.get(key)
                if isinstance(value, str) and value:
                    return value
    return None


def parse_delays(raw_delays: str) -> List[float]:
    try:
        delays = [float(value.strip()) for value in raw_delays.split(",") if value.strip()]
    except ValueError as error:
        raise ValueError("--delays must be a comma-separated list of seconds") from error
    if not delays or any(delay < 0 for delay in delays):
        raise ValueError("--delays must contain one or more non-negative seconds")
    return delays


def split_command(command: str) -> List[str]:
    parts = shlex.split(command, posix=os.name != "nt")
    if not parts:
        raise ValueError("--codex-command cannot be empty")
    return parts


def read_state(state_file: Path) -> Dict[str, Any]:
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError(f"State file does not exist: {state_file}") from error
    except json.JSONDecodeError as error:
        raise ValueError(f"State file is not valid JSON: {state_file}") from error
    if not isinstance(state, dict):
        raise ValueError(f"State file must contain an object: {state_file}")
    return state


def write_state(state_file: Path, state: Dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    temporary_file = state_file.with_name(f"{state_file.name}.tmp")
    temporary_file.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_file.replace(state_file)


def build_command(
    codex_command: Iterable[str], prompt: str, thread_id: Optional[str]
) -> List[str]:
    command = list(codex_command)
    if thread_id:
        return command + [
            "exec",
            "resume",
            thread_id,
            "--json",
            "--skip-git-repo-check",
            RESUME_PROMPT,
        ]
    return command + ["exec", "--json", "--skip-git-repo-check", prompt]


def run_codex(command: List[str], cwd: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, check=False)
    except OSError as error:
        return subprocess.CompletedProcess(command, 127, "", str(error))


def print_output(result: subprocess.CompletedProcess) -> None:
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prompt", help="Initial Codex task prompt")
    mode.add_argument("--resume", type=Path, help="Resume from a persisted retry-state JSON file")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Codex working directory")
    parser.add_argument("--state-file", type=Path, help="State file path for a new task")
    parser.add_argument("--delays", default=DEFAULT_DELAYS, help="Retry delays in seconds")
    parser.add_argument("--codex-command", default="codex", help="Codex executable or command")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        delays = parse_delays(args.delays)
        cwd = args.cwd.resolve()
        codex_command = split_command(args.codex_command)
        if args.resume:
            state_file = args.resume.resolve()
            state = read_state(state_file)
            prompt = state.get("prompt")
            if not isinstance(prompt, str) or not prompt:
                raise ValueError("State file does not contain the original prompt")
        else:
            state_file = (args.state_file or cwd / ".codex-retry-state.json").resolve()
            prompt = args.prompt
            state = {"status": "running", "prompt": prompt, "thread_id": None, "attempt": 0}
    except ValueError as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 64

    retry_count = int(state.get("retry_count", 0))
    while True:
        state["attempt"] = int(state.get("attempt", 0)) + 1
        state["status"] = "running"
        write_state(state_file, state)

        result = run_codex(build_command(codex_command, prompt, state.get("thread_id")), cwd)
        print_output(result)
        discovered_thread_id = extract_thread_id(result.stdout or "")
        if discovered_thread_id:
            state["thread_id"] = discovered_thread_id

        if result.returncode == 0:
            state["status"] = "completed"
            state.pop("last_error", None)
            write_state(state_file, state)
            print(f"Codex task completed. State: {state_file}")
            return 0

        failure = classify_failure(f"{result.stdout}\n{result.stderr}")
        state["last_error"] = {
            "kind": failure.kind.value,
            "message": failure.detail,
            "exit_code": result.returncode,
        }
        if failure.kind is FailureKind.QUOTA_EXHAUSTED:
            state["status"] = "quota_exhausted"
            write_state(state_file, state)
            print(f"Codex quota is exhausted. State preserved at: {state_file}", file=sys.stderr)
            return 2
        if failure.kind is FailureKind.NON_RETRYABLE:
            state["status"] = "failed"
            write_state(state_file, state)
            print(f"Codex did not return a retryable failure. State preserved at: {state_file}", file=sys.stderr)
            return result.returncode or 1
        if retry_count >= len(delays):
            state["status"] = "retry_exhausted"
            write_state(state_file, state)
            print(f"Retry budget exhausted. State preserved at: {state_file}", file=sys.stderr)
            return result.returncode or 1

        delay = delays[retry_count]
        retry_count += 1
        state["status"] = "retrying"
        state["retry_count"] = retry_count
        write_state(state_file, state)
        print(f"Transient failure. Retrying in {delay:g} seconds ({retry_count}/{len(delays)}).", file=sys.stderr)
        time.sleep(delay)


if __name__ == "__main__":
    raise SystemExit(main())
