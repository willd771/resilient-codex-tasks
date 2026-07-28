---
name: resilient-codex-tasks
description: Use when long or stateful Codex CLI tasks may be interrupted by transient HTTP 429, 502, or 503 provider errors, or when a 403 balance or quota response must stop retries.
---

# Resilient Codex Tasks

Run non-interactive Codex tasks through `scripts/codex_retry.py` when continuity matters. The wrapper creates a state file in the task directory and resumes the same Codex thread after a transient provider failure.

## Run A Task

```powershell
python <skill-dir>/scripts/codex_retry.py --cwd <workspace> --prompt "<task>"
```

Use the default six retries with waits of 15, 30, 60, 120, 240, and 300 seconds. Pass `--delays` only when the caller needs a different retry budget.

## Error Handling

| Failure | Required action |
| --- | --- |
| 429, 502, 503 | Save the session ID, wait, then run `codex exec resume` for the same thread. |
| 403 plus an exhausted-balance or quota marker | Stop immediately and report the saved state file. |
| Other 403, 400, 401, or unknown failures | Do not retry. Report the response and preserve the state file. |

Do not rerun completed state-changing work blindly. On a resumed thread, instruct Codex to inspect the repository and continue only unfinished work.

## Recover The Wrapper

If the wrapper process itself exits, continue from its state file:

```powershell
python <skill-dir>/scripts/codex_retry.py --resume <workspace>/.codex-retry-state.json --cwd <workspace>
```

The wrapper can only resume a session after Codex has emitted a thread ID. If the provider failed before that point, it starts a new invocation with the stored original prompt.

Treat the state file as task data because it contains the original prompt and recent error metadata.
