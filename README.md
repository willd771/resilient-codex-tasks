# Resilient Codex Tasks

`resilient-codex-tasks` is a Codex skill and a small Python wrapper for long-running Codex CLI work. It retries transient provider failures, preserves the Codex thread ID, and resumes the same thread after recovery.

## Behavior

| Response | Behavior |
| --- | --- |
| HTTP 429, 502, or 503 | Retry with the saved Codex thread. |
| HTTP 403 with an exhausted balance or quota marker | Stop immediately and preserve state. |
| Other 403, 400, 401, or unknown failures | Stop without retrying. |

The default retry waits are 15, 30, 60, 120, 240, and 300 seconds.

## Install

Copy `skills/resilient-codex-tasks` into your Codex skills directory:

```powershell
Copy-Item -Recurse .\skills\resilient-codex-tasks "$env:USERPROFILE\.codex\skills\"
```

Restart Codex or open a new task so it discovers the new skill.

## Run A Resilient CLI Task

Codex CLI must be installed and authenticated.

```powershell
python .\skills\resilient-codex-tasks\scripts\codex_retry.py `
  --cwd "D:\work\my-project" `
  --prompt "Implement the requested feature and run the tests."
```

The wrapper writes `.codex-retry-state.json` in the workspace. To continue after the wrapper itself exits:

```powershell
python .\skills\resilient-codex-tasks\scripts\codex_retry.py `
  --cwd "D:\work\my-project" `
  --resume "D:\work\my-project\.codex-retry-state.json"
```

Treat the state file as task data because it contains the original prompt and recent error metadata.

## Scope

The wrapper recovers Codex CLI calls that it starts. It cannot revive an already terminated Codex Desktop conversation because no external process can resume a model request after the desktop app has lost its execution context.

## Development

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py" -v
python -m py_compile .\skills\resilient-codex-tasks\scripts\codex_retry.py
```

## License

MIT. See [LICENSE](LICENSE).
