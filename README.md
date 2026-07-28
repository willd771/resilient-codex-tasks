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
| HTTP `400`, `401`, `403`, `429`, `502`, `503` | Wait using exponential backoff and resume the saved Codex thread. This includes quota, balance, permission, and authentication `403` responses. |
| `ECONNRESET`, `ECONNABORTED`, timeouts, DNS resolution failures, `socket hang up`, and network-unreachable errors | Wait using exponential backoff and retry, resuming the saved Codex thread when available. |
| Unmatched or unknown failures | Stop without retrying and preserve state. |

The default retry waits are 15, 30, 60, 120, 240, and 300 seconds.

## Scope

This wrapper recovers Codex CLI calls that it starts. It cannot revive a terminated Codex Desktop conversation because an external process cannot resume a model request after the desktop app has lost its execution context.

## Development

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py" -v
python -m py_compile .\skills\resilient-codex-tasks\scripts\codex_retry.py
```

## License

MIT. See [LICENSE](LICENSE).
