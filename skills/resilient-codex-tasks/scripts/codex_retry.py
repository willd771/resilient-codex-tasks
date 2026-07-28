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
MESSAGES = {
    "en": {
        "resume_prompt": (
            "The previous invocation ended after a transient provider error. Continue the same task "
            "from the existing repository and session. Inspect the current state first and do not "
            "repeat completed state-changing work."
        ),
        "configuration_error": "Configuration error: {error}",
        "completed": "Codex task completed. State: {state_file}",
        "non_retryable": "Codex did not return a retryable failure. State preserved at: {state_file}",
        "retry_exhausted": "Retry budget exhausted. State preserved at: {state_file}",
        "retrying": "Transient failure. Retrying in {delay:g} seconds ({retry_count}/{retry_limit}).",
    },
    "zh-CN": {
        "resume_prompt": (
            "上一次调用因临时服务错误而中断。请从现有仓库和会话继续同一任务。先检查当前状态，"
            "不要重复已经完成的会改变状态的操作。"
        ),
        "configuration_error": "配置错误：{error}",
        "completed": "Codex 任务已完成。状态文件：{state_file}",
        "non_retryable": "Codex 返回了不可重试的错误。状态已保留在：{state_file}",
        "retry_exhausted": "重试次数已耗尽。状态已保留在：{state_file}",
        "retrying": "检测到临时错误，将在 {delay:g} 秒后重试（{retry_count}/{retry_limit}）。",
    },
}


class FailureKind(Enum):
    TRANSIENT = "transient"
    NON_RETRYABLE = "non_retryable"


@dataclass(frozen=True)
class Failure:
    kind: FailureKind
    detail: str


def classify_failure(output: str) -> Failure:
    """Classify configured Codex HTTP and transport failures as retryable."""
    normalized = output.lower()
    transient_markers = (
        "too many requests",
        "rate limit",
        "bad gateway",
        "service unavailable",
        "econnreset",
        "econnaborted",
        "etimedout",
        "getaddrinfo",
        "enotfound",
        "socket hang up",
        "connection reset",
        "connection timed out",
        "connection timeout",
        "timed out",
        "timeout",
        "dns",
        "could not resolve host",
        "temporary failure in name resolution",
        "name or service not known",
        "network is unreachable",
    )
    if re.search(r"\b(?:400|401|403|429|502|503)\b", normalized) or any(
        marker in normalized for marker in transient_markers
    ):
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


def parse_command_json(raw_command: str) -> List[str]:
    try:
        command = json.loads(raw_command)
    except json.JSONDecodeError as error:
        raise ValueError("--command-json must contain a JSON array of command arguments") from error
    if not isinstance(command, list) or not command or any(
        not isinstance(value, str) or not value for value in command
    ):
        raise ValueError("--command-json must contain one or more non-empty string arguments")
    return command


def read_command(value: Any, field_name: str) -> Optional[List[str]]:
    if value is None:
        return None
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise ValueError(f"State file has invalid {field_name}")
    return value


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
    codex_command: Iterable[str],
    prompt: Optional[str],
    thread_id: Optional[str],
    language: str = "en",
    initial_command: Optional[Iterable[str]] = None,
) -> List[str]:
    command = list(codex_command)
    if thread_id:
        return command + [
            "exec",
            "resume",
            thread_id,
            "--json",
            "--skip-git-repo-check",
            MESSAGES[language]["resume_prompt"],
        ]
    if initial_command is not None:
        return list(initial_command)
    if not prompt:
        raise ValueError("A prompt is required when no initial command is stored")
    return command + ["exec", "--json", "--skip-git-repo-check", prompt]


def run_codex(command: List[str], cwd: Path) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, cwd=str(cwd), text=True, capture_output=True, check=False)
    except OSError as error:
        return subprocess.CompletedProcess(command, 127, "", str(error))


def render_jsonl_output(output: str) -> str:
    rendered_lines = []
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            rendered_lines.append(line)
            continue
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            rendered_lines.append(text)
    return "\n".join(rendered_lines)


def print_output(result: subprocess.CompletedProcess, render_json_output: bool = False) -> None:
    stdout = render_jsonl_output(result.stdout) if render_json_output and result.stdout else result.stdout
    if stdout:
        print(stdout, end="" if stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prompt", help="Initial Codex task prompt")
    mode.add_argument("--resume", type=Path, help="Resume from a persisted retry-state JSON file")
    mode.add_argument("--command-json", help="Initial Codex command as a JSON argument array")
    parser.add_argument("--cwd", type=Path, default=Path.cwd(), help="Codex working directory")
    parser.add_argument("--state-file", type=Path, help="State file path for a new task")
    parser.add_argument("--delays", default=DEFAULT_DELAYS, help="Retry delays in seconds")
    parser.add_argument(
        "--client-delays",
        help="Optional retry delays for HTTP 400, 401, and 403 responses",
    )
    parser.add_argument("--codex-command", help="Codex executable or command")
    parser.add_argument(
        "--language",
        choices=sorted(MESSAGES),
        help="Wrapper message language. Defaults to English and persists in the state file.",
    )
    parser.add_argument(
        "--render-json-output",
        action="store_true",
        help="Render completed Codex agent messages instead of printing JSON event lines.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    language = args.language or "en"
    messages = MESSAGES[language]
    try:
        delays = parse_delays(args.delays)
        client_delays = parse_delays(args.client_delays) if args.client_delays else None
        cwd = args.cwd.resolve()
        provided_codex_command = split_command(args.codex_command) if args.codex_command else None
        if args.resume:
            state_file = args.resume.resolve()
            state = read_state(state_file)
            if args.language is None:
                language = state.get("language", language)
            if language not in MESSAGES:
                raise ValueError(f"State file has unsupported language: {language}")
            messages = MESSAGES[language]
            prompt = state.get("prompt")
            initial_command = read_command(state.get("initial_command"), "initial_command")
            if initial_command is None and (not isinstance(prompt, str) or not prompt):
                raise ValueError("State file does not contain the original prompt or command")
            saved_codex_command = read_command(state.get("codex_command"), "codex_command")
            codex_command = provided_codex_command or saved_codex_command
            if codex_command is None:
                codex_command = [initial_command[0]] if initial_command else ["codex"]
        else:
            state_file = (args.state_file or cwd / ".codex-retry-state.json").resolve()
            initial_command = parse_command_json(args.command_json) if args.command_json else None
            prompt = args.prompt
            codex_command = provided_codex_command
            if codex_command is None:
                codex_command = [initial_command[0]] if initial_command else ["codex"]
            state = {
                "status": "running",
                "prompt": prompt,
                "thread_id": None,
                "attempt": 0,
                "language": language,
                "codex_command": codex_command,
            }
            if initial_command is not None:
                state["initial_command"] = initial_command
    except ValueError as error:
        print(messages["configuration_error"].format(error=error), file=sys.stderr)
        return 64

    while True:
        state["attempt"] = int(state.get("attempt", 0)) + 1
        state["status"] = "running"
        write_state(state_file, state)

        result = run_codex(
            build_command(
                codex_command,
                prompt,
                state.get("thread_id"),
                language,
                initial_command,
            ),
            cwd,
        )
        print_output(result, render_json_output=args.render_json_output)
        discovered_thread_id = extract_thread_id(result.stdout or "")
        if discovered_thread_id:
            state["thread_id"] = discovered_thread_id

        if result.returncode == 0:
            state["status"] = "completed"
            state.pop("last_error", None)
            write_state(state_file, state)
            print(messages["completed"].format(state_file=state_file))
            return 0

        failure = classify_failure(f"{result.stdout}\n{result.stderr}")
        state["last_error"] = {
            "kind": failure.kind.value,
            "message": failure.detail,
            "exit_code": result.returncode,
        }
        if failure.kind is FailureKind.NON_RETRYABLE:
            state["status"] = "failed"
            write_state(state_file, state)
            print(messages["non_retryable"].format(state_file=state_file), file=sys.stderr)
            return result.returncode or 1
        error_output = f"{result.stdout}\n{result.stderr}"
        retry_key = "client" if client_delays and re.search(r"\b(?:400|401|403)\b", error_output) else "default"
        retry_delays = client_delays if retry_key == "client" else delays
        retry_counts = state.get("retry_counts")
        if not isinstance(retry_counts, dict):
            retry_counts = {}
        retry_count = int(retry_counts.get(retry_key, state.get("retry_count", 0) if retry_key == "default" else 0))
        if retry_count >= len(retry_delays):
            state["status"] = "retry_exhausted"
            write_state(state_file, state)
            print(messages["retry_exhausted"].format(state_file=state_file), file=sys.stderr)
            return result.returncode or 1

        delay = retry_delays[retry_count]
        retry_count += 1
        state["status"] = "retrying"
        retry_counts[retry_key] = retry_count
        state["retry_counts"] = retry_counts
        state["retry_count"] = sum(int(count) for count in retry_counts.values())
        write_state(state_file, state)
        print(
            messages["retrying"].format(
                delay=delay, retry_count=retry_count, retry_limit=len(retry_delays)
            ),
            file=sys.stderr,
        )
        time.sleep(delay)


if __name__ == "__main__":
    raise SystemExit(main())
