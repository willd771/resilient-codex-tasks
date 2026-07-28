# Resilient Codex Tasks

[![Validate](https://github.com/willd771/resilient-codex-tasks/actions/workflows/validate.yml/badge.svg)](https://github.com/willd771/resilient-codex-tasks/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8%2B-3776AB)](https://www.python.org/)

Keep long-running Codex CLI tasks moving when temporary provider failures interrupt them. This repository provides a Codex skill and a dependency-free Python wrapper that preserves task state and resumes the same Codex thread.

[English](#quick-start) | [简体中文](README.zh-CN.md)

## Highlights

- Retry HTTP `400`, `401`, `403`, `429`, `502`, and `503` with a persisted Codex thread ID.
- Retry connection resets, timeouts, DNS resolution failures, socket hang ups, and other configured transport failures.
- Resume after the wrapper itself exits by reusing the state file.
- Use English by default or pass `--language zh-CN` for Chinese wrapper messages and resume instructions.
- Optionally enable Windows-wide retries for direct `codex exec` commands with one installation step.

## Quick Start

Copy the skill into your Codex skills directory:

```powershell
Copy-Item -Recurse .\skills\resilient-codex-tasks "$env:USERPROFILE\.codex\skills\"
```

Then start a resilient Codex CLI task:

```powershell
python .\skills\resilient-codex-tasks\scripts\codex_retry.py `
  --cwd "D:\work\my-project" `
  --prompt "Implement the requested feature and run the tests."
```

Use Chinese output and resume guidance when needed:

```powershell
python .\skills\resilient-codex-tasks\scripts\codex_retry.py `
  --cwd "D:\work\my-project" `
  --prompt "完成当前任务并运行测试。" `
  --language zh-CN
```

## Global CLI Mode (Windows)

After copying the skill into `~/.codex/skills`, enable global handling for direct `codex exec` tasks:

```powershell
python "$env:USERPROFILE\.codex\skills\resilient-codex-tasks\scripts\install_global.py" install
```

Open a new terminal, then run Codex normally:

```powershell
codex exec "Implement the requested feature and run the tests."
```

The proxy injects Codex JSON events internally, renders completed agent messages as normal terminal output, and saves each task under `$env:USERPROFILE\.codex\resilient-codex-tasks\states`. It only intercepts direct `codex exec` calls. Interactive `codex`, `codex login`, `codex mcp`, and `codex exec resume <thread-id>` continue to use the real CLI unchanged. Codex Desktop conversations are not affected.

Inspect or remove the proxy:

```powershell
python "$env:USERPROFILE\.codex\skills\resilient-codex-tasks\scripts\install_global.py" status
python "$env:USERPROFILE\.codex\skills\resilient-codex-tasks\scripts\install_global.py" uninstall
```

Bypass it for one command with `CODEX_RETRY_BYPASS=1`. Override the installed settings in a terminal with `CODEX_RETRY_DELAYS`, `CODEX_RETRY_CLIENT_DELAYS`, and `CODEX_RETRY_LANGUAGE=zh-CN`.

## Recovery

The wrapper writes `.codex-retry-state.json` in the workspace. To continue after the wrapper process exits:

```powershell
python .\skills\resilient-codex-tasks\scripts\codex_retry.py `
  --cwd "D:\work\my-project" `
  --resume "D:\work\my-project\.codex-retry-state.json"
```

The state file stores the original prompt, selected language, thread ID, retry count, and last error. Treat it as task data.

## Response Policy

| Response | Action |
| --- | --- |
| HTTP `429`, `502`, `503` | Wait using the standard retry budget and resume the saved Codex thread. |
| HTTP `400`, `401`, `403` | Retry and resume the saved Codex thread. Global mode defaults to a separate 5 and 20 second budget for these responses, including quota, balance, permission, and authentication `403` responses. |
| `ECONNRESET`, `ECONNABORTED`, timeouts, DNS resolution failures, `socket hang up`, and network-unreachable errors | Wait using exponential backoff and retry, resuming the saved Codex thread when available. |
| Unmatched or unknown failures | Stop without retrying and preserve state. |

The default retry waits are 15, 30, 60, 120, 240, and 300 seconds.

## Scope

This wrapper recovers Codex CLI calls that it starts. The global proxy is Windows-only and intentionally limits interception to direct `codex exec` commands. It cannot revive a terminated Codex Desktop conversation because an external process cannot resume a model request after the desktop app has lost its execution context.

## Development

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py" -v
python -m py_compile .\skills\resilient-codex-tasks\scripts\codex_retry.py
```

## License

MIT. See [LICENSE](LICENSE).
