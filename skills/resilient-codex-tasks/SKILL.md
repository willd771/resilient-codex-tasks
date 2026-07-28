---
name: resilient-codex-tasks
description: Use when long or stateful Codex CLI tasks may be interrupted by HTTP 400, 401, 403, 429, 502, or 503 responses, or by connection reset, timeout, DNS, and other configured transport errors that need persisted retries, session resume, or Windows-wide `codex exec` retry setup.
---

# Resilient Codex Tasks

Run non-interactive Codex tasks through `scripts/codex_retry.py` when continuity matters. The wrapper creates a state file in the task directory and resumes the same Codex thread after a transient provider failure.

## Enable Global CLI Mode

On Windows, install the optional global proxy after copying this skill into `~/.codex/skills`:

```powershell
python <skill-dir>/scripts/install_global.py install
```

Open a new terminal after installation. The proxy automatically wraps direct `codex exec <task>` calls, saves each task in its own state file under `~/.codex/resilient-codex-tasks/states`, and uses the real Codex CLI saved during installation.

Pass through without retries for one command with `CODEX_RETRY_BYPASS=1`. `codex`, `codex login`, `codex mcp`, and `codex exec resume <thread-id>` pass through unchanged. Inspect or remove the integration with:

```powershell
python <skill-dir>/scripts/install_global.py status
python <skill-dir>/scripts/install_global.py uninstall
```

Set `CODEX_RETRY_DELAYS`, `CODEX_RETRY_CLIENT_DELAYS`, or `CODEX_RETRY_LANGUAGE=zh-CN` to override the installed configuration for the current terminal.

## Run A Task

```powershell
python <skill-dir>/scripts/codex_retry.py --cwd <workspace> --prompt "<task>"
```

Use the default six retries with waits of 15, 30, 60, 120, 240, and 300 seconds. Pass `--delays` only when the caller needs a different retry budget.

Pass `--language zh-CN` for Chinese wrapper messages and a Chinese resume instruction. The selected language is stored in the state file and reused by `--resume`.

## Error Handling

| Failure | Required action |
| --- | --- |
| HTTP 429, 502, 503 and configured transport errors | Save the session ID, wait using the standard retry budget, then run `codex exec resume` for the same thread. |
| HTTP 400, 401, 403 | Retry. Global mode uses its separate short default budget of 5 and 20 seconds; this includes balance, quota, permission, and authentication responses. |
| ECONNRESET, ECONNABORTED, timeouts, DNS resolution failures, socket hang ups, and network-unreachable errors | Save the state, wait, then retry and resume the same thread when a session ID is available. |
| Unmatched or unknown failures | Do not retry. Report the response and preserve the state file. |

Do not rerun completed state-changing work blindly. On a resumed thread, instruct Codex to inspect the repository and continue only unfinished work.

## Recover The Wrapper

If the wrapper process itself exits, continue from its state file:

```powershell
python <skill-dir>/scripts/codex_retry.py --resume <workspace>/.codex-retry-state.json --cwd <workspace>
```

The wrapper can only resume a session after Codex has emitted a thread ID. If the provider failed before that point, it starts a new invocation with the stored original prompt.

Treat the state file as task data because it contains the original prompt and recent error metadata.
