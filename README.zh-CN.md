# Resilient Codex Tasks

[![Validate](https://github.com/willd771/resilient-codex-tasks/actions/workflows/validate.yml/badge.svg)](https://github.com/willd771/resilient-codex-tasks/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

让长时间运行的 Codex CLI 任务在遇到临时服务故障后自动续做。此仓库包含一个 Codex Skill 和一个零第三方依赖的 Python 包装器，用于保存任务状态并恢复原 Codex 线程。

[English](README.md) | [简体中文](#快速开始)

## 核心能力

- 自动重试 HTTP `400`、`401`、`403`、`429`、`502`、`503`，并恢复已保存的 Codex 线程。
- 自动重试连接重置、超时、DNS 解析失败、`socket hang up` 等已配置的传输层错误。
- 包装器进程意外结束后，可以从状态文件继续。
- 默认英文；传入 `--language zh-CN` 后，包装器提示和续做指令均使用中文。
- Windows 可选一键启用全局 `codex exec` 自动重试。

## 快速开始

将 Skill 复制到 Codex 的 skills 目录：

```powershell
Copy-Item -Recurse .\skills\resilient-codex-tasks "$env:USERPROFILE\.codex\skills\"
```

运行带自动续做能力的 Codex CLI 任务：

```powershell
python .\skills\resilient-codex-tasks\scripts\codex_retry.py `
  --cwd "D:\work\my-project" `
  --prompt "完成当前任务并运行测试。" `
  --language zh-CN
```

## 全局 CLI 模式（Windows）

将 Skill 复制到 `~/.codex/skills` 后，执行一次安装：

```powershell
python "$env:USERPROFILE\.codex\skills\resilient-codex-tasks\scripts\install_global.py" install
```

重新打开终端后，直接照常运行：

```powershell
codex exec "完成当前任务并运行测试。"
```

代理会在内部启用 Codex JSON 事件流、将完成消息渲染为普通终端输出，并把每个任务的状态单独保存在 `$env:USERPROFILE\.codex\resilient-codex-tasks\states`。它只接管直接执行的 `codex exec`；交互式 `codex`、`codex login`、`codex mcp`、`codex exec resume <线程 ID>` 会直接调用真实 CLI。Codex Desktop 对话不受影响。

查看状态或卸载：

```powershell
python "$env:USERPROFILE\.codex\skills\resilient-codex-tasks\scripts\install_global.py" status
python "$env:USERPROFILE\.codex\skills\resilient-codex-tasks\scripts\install_global.py" uninstall
```

设置 `CODEX_RETRY_BYPASS=1` 可让当前命令绕过代理。`CODEX_RETRY_DELAYS`、`CODEX_RETRY_CLIENT_DELAYS`、`CODEX_RETRY_LANGUAGE=zh-CN` 可覆盖当前终端的安装配置。

## 从状态文件恢复

包装器会在工作目录写入 `.codex-retry-state.json`。如果包装器进程本身退出，使用下面的命令恢复：

```powershell
python .\skills\resilient-codex-tasks\scripts\codex_retry.py `
  --cwd "D:\work\my-project" `
  --resume "D:\work\my-project\.codex-retry-state.json"
```

状态文件会保存原始提示、语言设置、线程 ID、重试次数和最后错误信息，应按任务数据妥善保管。

## 错误处理策略

| 响应 | 行为 |
| --- | --- |
| HTTP `429`、`502`、`503` | 使用标准重试预算等待，然后恢复已保存的 Codex 线程。 |
| HTTP `400`、`401`、`403` | 重试并恢复已保存的 Codex 线程。全局模式对此类响应默认使用独立的 5 秒、20 秒短预算，包括余额、配额、权限和认证类 `403`。 |
| `ECONNRESET`、`ECONNABORTED`、超时、DNS 解析失败、`socket hang up`、网络不可达 | 按退避时间等待后重试；已有线程 ID 时恢复该 Codex 线程。 |
| 未匹配或未知错误 | 不重试，保留状态后退出。 |

默认等待时间依次为 15、30、60、120、240、300 秒。

## 适用边界

该包装器只能恢复它自身启动的 Codex CLI 调用。全局代理目前仅支持 Windows，并且刻意只接管直接执行的 `codex exec`。桌面版 Codex 会话一旦被终止，外部进程无法恢复已经丢失的模型请求上下文。

## 开发验证

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py" -v
python -m py_compile .\skills\resilient-codex-tasks\scripts\codex_retry.py
```

## 许可证

MIT，见 [LICENSE](LICENSE)。
