# agy-hist / agy-browse

A fast, zero-dependency cross-platform CLI tool for **Linux**, **macOS**, and **Windows** to browse, search, and resume past Antigravity CLI (and Claude Code) conversations.

---

## The Problem Solved

When working with terminal AI agents like Antigravity (`agy`), closing a terminal or losing track of a conversation ID makes it difficult to resume where you left off. 

`agy-hist` indexes your local transcripts instantly without external dependencies, shows you clean context previews of past prompts, and lets you:
- **Resume immediately** (`agy --conversation <uuid>`) with a single keypress.
- **Copy the resume command** directly to your system clipboard (`wl-copy`, `pbcopy`, `clip.exe`).
- **Fuzzy/keyword search** across all previous prompts and turns.

---

## Quick Start & Installation

### Linux & macOS

1. Make the script executable and link it to your `PATH` (e.g. `~/.local/bin`):
   ```bash
   chmod +x /path/to/agy_hist.py
   ln -s /path/to/agy_hist.py ~/.local/bin/agy-hist
   ln -s /path/to/agy_hist.py ~/.local/bin/agy-browse
   ```

2. Run it:
   ```bash
   agy-hist
   ```

### Windows (Command Prompt or PowerShell)

1. Ensure Python 3 is installed and added to `PATH`.
2. Add the folder containing `agy_hist.py` and `agy-hist.cmd` to your Windows user `PATH` environment variable, or run:
   ```cmd
   python C:\path\to\agy_hist.py
   # Or using the cmd/ps1 wrappers:
   agy-hist
   ```

---

## Features & Usage

### 1. Interactive Browser (Default)

Running `agy-hist` or `agy-browse` without arguments opens the interactive pager:

```bash
agy-hist
```

**Key Commands in Browser**:
- `1` - `10`: Select a conversation by its list index to view details and action menu.
- `/keyword` or `s keyword`: Filter conversation list by keyword.
- `clear`: Reset active search filter.
- `n` / `p`: Next / Previous page.
- `r 1`: Quick resume item #1 directly.
- `c 1`: Quick copy item #1's resume command to clipboard.
- `q`: Quit.

Inside the Conversation View:
- `[r]`: Resume conversation in place (executes `agy --conversation <uuid>`).
- `[c]`: Copy `agy --conversation <uuid>` to system clipboard.
- `[v]`: View all prompts sent in this session.
- `[b]`: Go back to conversation list.
- `[q]`: Quit.

---

### 2. Fast CLI Subcommands

#### Keyword Search
Find conversations mentioning a specific topic (e.g. `scrollless`, `boot`, `python`):
```bash
agy-hist search "scrollless"
```

#### List Recent Sessions
```bash
# List last 10 sessions
agy-hist list -n 10

# Output as JSON for scripting/piping
agy-hist list --json
```

#### Resume a Session Directly
Resume by list index or UUID prefix:
```bash
agy-hist resume 1
agy-hist resume 083b3966
```

#### Copy Resume Command to Clipboard
```bash
agy-hist copy 1
agy-hist copy 083b3966
```

#### Latest Session (`last`)
```bash
# Show details of the most recent session
agy-hist last

# Copy the resume command for the most recent session
agy-hist last --copy

# Resume the most recent session immediately
agy-hist last --resume
```

#### Full Prompt History (`show`)
```bash
agy-hist show 083b3966
```

#### Include Claude Code Sessions (`--all`)
```bash
agy-hist list --all
agy-hist search "flask" --all
```

---

## Platform Support

| OS | Transcript Path | Clipboard Mechanism | Colors |
|---|---|---|---|
| **Linux** | `~/.gemini/*/brain/` | `wl-copy` (Wayland), `xclip` / `xsel` (X11) | Standard ANSI |
| **macOS** | `~/.gemini/*/brain/` | `pbcopy` | Standard ANSI |
| **Windows** | `%USERPROFILE%\.gemini\*\brain\` | `clip.exe`, PowerShell `Set-Clipboard` | Windows VT100 (`os.system("")`) |

---

## Zero Dependencies

Built entirely using Python's standard library (`argparse`, `datetime`, `json`, `pathlib`, `re`, `shutil`, `subprocess`). No `pip install` required.
