---
name: resilient-codex-tasks
description: Use when long or stateful Codex CLI tasks may be interrupted by HTTP 400, 401, 403, 429, 502, or 503 responses, or by connection reset, timeout, DNS, and other configured transport errors that need persisted retries and session resume.
---

# Resilient Codex Tasks

Run non-interactive Codex tasks through `scripts/codex_retry.py` when continuity matters. The wrapper creates a state file in the task directory and resumes the same Codex thread after a transient provider failure.

## Run A Task

```powershell
python <skill-dir>/scripts/codex_retry.py --cwd <workspace> --prompt "<task>"
```

Use the default six retries with waits of 15, 30, 60, 120, 240, and 300 seconds. Pass `--delays` only when the caller needs a different retry budget.

Pass `--language zh-CN` for Chinese wrapper messages and a Chinese resume instruction. The selected language is stored in the state file and reused by `--resume`.

## Error Handling

| Failure | Required action |
| --- | --- |
| HTTP 400, 401, 403, 429, 502, 503 | Save the session ID, wait, then run `codex exec resume` for the same thread. This includes 403 balance, quota, permission, and authentication responses. |
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
