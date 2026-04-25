# A6s for Sublime Text

Intelligent multi-agent orchestration inside Sublime Text 3 and 4. Invoke
agents, stream RIGOR phase updates, and apply generated refactors — all
through the local `a6s` daemon.

## Requirements

- Sublime Text 3 (build 3211+) or Sublime Text 4
- The A6s CLI daemon running locally:

  ```bash
  brew install autonoma/tap/a6s
  a6s daemon
  ```

  The daemon listens on `ws://localhost:9876/ws` by default. Change the port in
  **Preferences → Package Settings → A6s → Settings** if needed.

## Install

### Via Package Control (recommended, after listing)

1. `Tools → Command Palette → Package Control: Install Package`
2. Search for **A6s** and install.

### Manual install

```bash
cd "$(subl --command 'sublime.packages_path()' 2>/dev/null || echo ~/Library/Application\ Support/Sublime\ Text/Packages)"
git clone https://github.com/The-Autonoma/autonoma-sublime.git A6s
```

Restart Sublime Text.

## Default key bindings

| Action | Shortcut |
|---|---|
| Invoke agent | `ctrl+alt+a` |
| Explain selection | `ctrl+alt+e` |
| Refactor selection | `ctrl+alt+r` |
| Review selection | `ctrl+alt+v` |
| Generate tests for selection | `ctrl+alt+t` |
| List background tasks | `ctrl+alt+l` |

All commands are also available from **Tools → A6s** and the command palette
(prefix every command with `A6s:`).

## Commands

| Command | Purpose |
|---|---|
| `A6s: Connect to Daemon` / `Disconnect from Daemon` | Manage the WebSocket connection |
| `A6s: Invoke Agent…` | Pick an agent and submit a free-form task |
| `A6s: Explain Selection` | Plain-language explanation of selected code |
| `A6s: Refactor Selection` | Refactor with optional instructions; preview before apply |
| `A6s: Review Selection` | Issue list with severity, message, and suggestion |
| `A6s: Generate Tests for Selection` | Generate test artifacts for the current selection |
| `A6s: List Agents` / `Execution Status` | Inspect daemon state |
| `A6s: Launch Background Task` / `Task Output` / `List Background Tasks` / `Cancel Background Task…` | Long-running task management |
| `A6s: Preview Pending Artifacts` / `Apply Pending Artifacts` | Review and apply generated changes |

## Settings

Open **Preferences → Package Settings → A6s → Settings**. The defaults are:

```json
{
  "daemon_url": "ws://localhost:9876/ws",
  "auto_connect": true,
  "default_agent": "coder-ai",
  "preview_before_apply": true,
  "show_rigor_progress": true
}
```

## Protocol

This package is a thin client over the local A6s daemon. All traffic flows
over `ws://localhost:9876/ws` using the Autonoma Daemon Protocol v1.0 — JSON
envelopes of the form `{id, method, params}` for requests and `{type, data}`
for events. Full spec and bootstrap guide:
<https://www.theautonoma.io/docs/build/cli/daemon>.

Implements all 13 daemon methods: `agents.list`, `agents.invoke`,
`execution.status`, `background.{list,launch,cancel,output}`,
`artifacts.{preview,apply}`, `code.{explain,refactor,generateTests,review}`.

## Development

```bash
git clone https://github.com/The-Autonoma/autonoma-sublime.git
cd autonoma-sublime
./run_tests.sh        # runs UnitTesting (ST4) under tests/
```

The package follows the standard Sublime Text plugin layout — `.py` files at
the package root are auto-loaded by ST. No build step.

## License

Apache-2.0 — see `LICENSE`.
