#!/usr/bin/env python3
"""
agy-hist / agy-browse
A cross-platform CLI tool for Linux, macOS, and Windows to browse, search,
and resume past AI conversations (Antigravity CLI and Claude Code).
"""

import argparse
import datetime
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Dict, Any

# Enable ANSI colors on Windows 10+
if sys.platform.startswith("win"):
    os.system("")

# -----------------------------------------------------------------------------
# Color & Formatting Utilities
# -----------------------------------------------------------------------------
USE_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

def color(text: str, code: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def bold(text: str) -> str: return color(text, "1")
def dim(text: str) -> str: return color(text, "2")
def cyan(text: str) -> str: return color(text, "36")
def green(text: str) -> str: return color(text, "32")
def yellow(text: str) -> str: return color(text, "33")
def magenta(text: str) -> str: return color(text, "35")
def red(text: str) -> str: return color(text, "31")

def relative_time(timestamp_epoch: float) -> str:
    now = datetime.datetime.now().timestamp()
    diff = max(0, int(now - timestamp_epoch))
    if diff < 60:
        return f"{diff}s ago"
    minutes = diff // 60
    if minutes < 60:
        return f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    days = hours // 24
    if days < 30:
        return f"{days}d ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"

def format_timestamp(timestamp_epoch: float) -> str:
    dt = datetime.datetime.fromtimestamp(timestamp_epoch)
    return dt.strftime("%Y-%m-%d %H:%M")

def clean_request_text(raw_text: str) -> str:
    """Extract clean user request from raw prompt XML/metadata wrapper."""
    if not raw_text:
        return ""
    m = re.search(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", raw_text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    else:
        text = raw_text.strip()
    # Strip any remaining XML-like tags
    text = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", text, flags=re.DOTALL)
    text = re.sub(r"<USER_SETTINGS_CHANGE>.*?</USER_SETTINGS_CHANGE>", "", text, flags=re.DOTALL)
    text = re.sub(r"<RULE\[.*?\]>.*?</RULE\[.*?\]>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse multiple whitespaces
    return " ".join(text.split()).strip()

# -----------------------------------------------------------------------------
# Cross-Platform Clipboard
# -----------------------------------------------------------------------------
def copy_to_clipboard(text: str) -> bool:
    """Copy text to system clipboard on Linux, macOS, and Windows."""
    # 1. macOS pbcopy
    if sys.platform == "darwin":
        try:
            p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            return p.returncode == 0
        except Exception:
            pass

    # 2. Windows clip.exe or PowerShell
    elif sys.platform.startswith("win"):
        try:
            p = subprocess.Popen(["clip"], stdin=subprocess.PIPE, shell=True)
            p.communicate(input=text.encode("utf-16le"))
            if p.returncode == 0:
                return True
        except Exception:
            pass
        try:
            cmd = ["powershell", "-NoProfile", "-Command", "Set-Clipboard", "-Value", text]
            p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if p.returncode == 0:
                return True
        except Exception:
            pass

    # 3. Linux / BSD: wl-copy, xclip, xsel
    else:
        # Wayland wl-copy (passing text directly forks or serves reliably)
        try:
            p = subprocess.run(["wl-copy", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if p.returncode == 0:
                return True
        except Exception:
            pass
        # Fallback to stdin for wl-copy if argument fails
        try:
            p = subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            if p.returncode == 0:
                return True
        except Exception:
            pass
        # X11 xclip
        try:
            p = subprocess.Popen(["xclip", "-selection", "clipboard"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            if p.returncode == 0:
                return True
        except Exception:
            pass
        # X11 xsel
        try:
            p = subprocess.Popen(["xsel", "--clipboard", "--input"], stdin=subprocess.PIPE)
            p.communicate(input=text.encode("utf-8"))
            if p.returncode == 0:
                return True
        except Exception:
            pass

    # 4. Fallback tkinter
    try:
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        pass

    return False

# -----------------------------------------------------------------------------
# Conversation Data Model
# -----------------------------------------------------------------------------
class Conversation:
    def __init__(
        self,
        conv_id: str,
        provider: str,
        created_at: float,
        updated_at: float,
        title: str,
        all_prompts: List[str],
        step_count: int,
        resume_cmd: str,
        workspace: Optional[str] = None
    ):
        self.id = conv_id
        self.provider = provider
        self.created_at = created_at
        self.updated_at = updated_at
        self.title = title
        self.all_prompts = all_prompts
        self.step_count = step_count
        self.resume_cmd = resume_cmd
        self.workspace = workspace

    @property
    def turns_count(self) -> int:
        return len(self.all_prompts)

    def matches(self, query: str) -> bool:
        q = query.lower()
        if q in self.id.lower():
            return True
        if q in self.title.lower():
            return True
        for p in self.all_prompts:
            if q in p.lower():
                return True
        if self.workspace and q in self.workspace.lower():
            return True
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "created_at": datetime.datetime.fromtimestamp(self.created_at).isoformat(),
            "updated_at": datetime.datetime.fromtimestamp(self.updated_at).isoformat(),
            "turns_count": self.turns_count,
            "step_count": self.step_count,
            "title": self.title,
            "prompts": self.all_prompts,
            "resume_cmd": self.resume_cmd,
            "workspace": self.workspace,
        }

# -----------------------------------------------------------------------------
# Conversation Scanners
# -----------------------------------------------------------------------------
def scan_antigravity_conversations() -> List[Conversation]:
    """Scan ~/.gemini/*/brain/ for Antigravity conversations."""
    conversations: List[Conversation] = []
    gemini_dir = Path.home() / ".gemini"
    if not gemini_dir.is_dir():
        return conversations

    # Find brain directories
    brain_dirs: List[Path] = []
    try:
        for entry in gemini_dir.iterdir():
            b = entry / "brain"
            if b.is_dir():
                brain_dirs.append(b)
        root_brain = gemini_dir / "brain"
        if root_brain.is_dir() and root_brain not in brain_dirs:
            brain_dirs.append(root_brain)
    except Exception:
        pass

    for brain in brain_dirs:
        try:
            conv_dirs = [d for d in brain.iterdir() if d.is_dir()]
        except Exception:
            continue

        for cdir in conv_dirs:
            conv_id = cdir.name
            transcript_path = cdir / ".system_generated" / "logs" / "transcript.jsonl"
            if not transcript_path.is_file():
                continue

            try:
                mtime = transcript_path.stat().st_mtime
                ctime = transcript_path.stat().st_ctime
            except Exception:
                mtime = ctime = 0.0

            user_prompts: List[str] = []
            created_epoch = ctime
            step_count = 0
            workspace = None

            try:
                with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        step_count += 1
                        # Fast check before parsing JSON
                        if '"USER_INPUT"' in line:
                            try:
                                data = json.loads(line)
                                if data.get("type") == "USER_INPUT":
                                    cnt = data.get("content", "")
                                    cleaned = clean_request_text(cnt)
                                    if cleaned:
                                        user_prompts.append(cleaned)
                                    if "created_at" in data and not created_epoch:
                                        # Parse ISO timestamp
                                        iso_str = data["created_at"].replace("Z", "+00:00")
                                        dt = datetime.datetime.fromisoformat(iso_str)
                                        created_epoch = dt.timestamp()
                            except Exception:
                                pass
                        elif "Command Working Directory:" in line or "Active Workspaces:" in line:
                            try:
                                data = json.loads(line)
                                cnt = str(data.get("content", ""))
                                for cl in cnt.splitlines():
                                    if cl.startswith("Command Working Directory:"):
                                        workspace = cl.split(":", 1)[1].strip()
                            except Exception:
                                pass
            except Exception:
                continue

            title = user_prompts[0] if user_prompts else "(No prompt recorded)"
            conversations.append(
                Conversation(
                    conv_id=conv_id,
                    provider="antigravity",
                    created_at=created_epoch or mtime,
                    updated_at=mtime,
                    title=title,
                    all_prompts=user_prompts,
                    step_count=step_count,
                    resume_cmd=f"agy --conversation {conv_id}",
                    workspace=workspace
                )
            )

    return conversations

def scan_claude_conversations() -> List[Conversation]:
    """Scan ~/.claude/history.jsonl for Claude Code conversations."""
    conversations: List[Conversation] = []
    history_file = Path.home() / ".claude" / "history.jsonl"
    if not history_file.is_file():
        return conversations

    sessions: Dict[str, Dict[str, Any]] = {}
    try:
        with open(history_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    session_id = data.get("sessionId")
                    display = data.get("display", "").strip()
                    ts = data.get("timestamp", 0) / 1000.0
                    proj = data.get("project")
                    if not session_id or not display or display.startswith("/"):
                        continue
                    if session_id not in sessions:
                        sessions[session_id] = {
                            "id": session_id,
                            "prompts": [],
                            "first_ts": ts,
                            "last_ts": ts,
                            "project": proj,
                        }
                    s = sessions[session_id]
                    s["prompts"].append(display)
                    s["last_ts"] = max(s["last_ts"], ts)
                    if proj and not s["project"]:
                        s["project"] = proj
                except Exception:
                    pass
    except Exception:
        pass

    for sid, s in sessions.items():
        title = s["prompts"][0] if s["prompts"] else "(No prompt)"
        conversations.append(
            Conversation(
                conv_id=sid,
                provider="claude",
                created_at=s["first_ts"],
                updated_at=s["last_ts"],
                title=title,
                all_prompts=s["prompts"],
                step_count=len(s["prompts"]),
                resume_cmd=f"claude --resume {sid}",
                workspace=s["project"]
            )
        )

    return conversations

def get_all_conversations(include_claude: bool = False) -> List[Conversation]:
    """Retrieve all conversations, sorted newest first."""
    convs = scan_antigravity_conversations()
    if include_claude:
        convs.extend(scan_claude_conversations())
    convs.sort(key=lambda c: c.updated_at, reverse=True)
    return convs

# -----------------------------------------------------------------------------
# Resume Execution
# -----------------------------------------------------------------------------
def execute_resume(conv: Conversation) -> None:
    """Launch the resume command in place."""
    print(f"\n{bold(green('⚡ Resuming session:'))} {cyan(conv.id)}")
    print(f"{dim('Command:')} {bold(conv.resume_cmd)}\n")
    args = conv.resume_cmd.split()
    try:
        if sys.platform.startswith("win"):
            subprocess.call(args)
        else:
            os.execvp(args[0], args)
    except FileNotFoundError:
        print(red(f"Error: Command '{args[0]}' not found in PATH."))
        print(f"To resume manually run: {bold(conv.resume_cmd)}")
    except Exception as e:
        print(red(f"Failed to resume session: {e}"))

# -----------------------------------------------------------------------------
# Detailed Conversation View
# -----------------------------------------------------------------------------
def display_conversation_detail(conv: Conversation) -> None:
    term_width = min(shutil.get_terminal_size((80, 24)).columns, 100)
    print("\n" + "=" * term_width)
    print(f"{bold('Conversation Details')}  [{cyan(conv.provider.upper())}]")
    print("=" * term_width)
    print(f"{bold('ID:')}          {cyan(conv.id)}")
    print(f"{bold('Updated:')}     {format_timestamp(conv.updated_at)} ({relative_time(conv.updated_at)})")
    print(f"{bold('Created:')}     {format_timestamp(conv.created_at)}")
    print(f"{bold('User Turns:')}  {yellow(str(conv.turns_count))} ({conv.step_count} total steps)")
    if conv.workspace:
        print(f"{bold('Workspace:')}   {conv.workspace}")
    print(f"{bold('Resume Cmd:')}  {bold(green(conv.resume_cmd))}")
    print("-" * term_width)
    print(bold("Prompt History:"))
    for i, p in enumerate(conv.all_prompts, 1):
        num_str = f"[{i}]"
        print(f"  {yellow(num_str)} {p}")
        if i >= 10 and len(conv.all_prompts) > 12 and i < len(conv.all_prompts):
            remaining = len(conv.all_prompts) - i
            print(dim(f"  ... ({remaining} more prompts omitted) ..."))
            break
    print("=" * term_width)

# -----------------------------------------------------------------------------
# Interactive Browser Loop
# -----------------------------------------------------------------------------
def run_interactive_browser(include_claude: bool = False, initial_query: str = "") -> None:
    all_convs = get_all_conversations(include_claude=include_claude)
    if not all_convs:
        print(yellow("No conversations found."))
        return

    query = initial_query
    page_size = 10
    page = 0

    while True:
        # Filter conversations
        filtered = [c for c in all_convs if c.matches(query)] if query else all_convs
        total_items = len(filtered)
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = max(0, min(page, total_pages - 1))
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, total_items)
        page_items = filtered[start_idx:end_idx]

        term_width = min(shutil.get_terminal_size((80, 24)).columns, 110)

        # Header
        print("\n" + "=" * term_width)
        title_hdr = f"🚀 Antigravity Conversation Browser ({total_items} sessions)"
        if query:
            title_hdr += f" [Filter: '{query}']"
        print(bold(title_hdr))
        print("=" * term_width)

        if not page_items:
            print(yellow(f"\n  No conversations match query: '{query}'\n"))
        else:
            # Table Header
            print(f" {bold('#'):<4} {bold('Time'):<10} {bold('ID'):<10} {bold('Turns'):<7} {bold('Context Preview')}")
            print(" " + "-" * (term_width - 2))

            for idx, conv in enumerate(page_items, start=start_idx + 1):
                time_str = relative_time(conv.updated_at)
                short_id = conv.id[:8]
                turns_str = f"{conv.turns_count}t"

                # Calculate available width for preview
                fixed_len = 4 + 10 + 10 + 7 + 4
                avail = max(20, term_width - fixed_len)
                preview = conv.title.replace("\n", " ")
                if len(preview) > avail:
                    preview = preview[:avail - 3] + "..."

                # Provider tag if claude
                prov_tag = f"[{conv.provider[0].upper()}] " if include_claude else ""
                print(f" {cyan(str(idx)):<4} {dim(time_str):<10} {dim(short_id):<10} {yellow(turns_str):<7} {prov_tag}{preview}")

        print("-" * term_width)
        nav_info = f"Page {page + 1}/{total_pages} (Items {start_idx + 1}-{end_idx} of {total_items})"
        print(dim(nav_info))
        print(f"{bold('Actions:')} [1-{end_idx}] Select | [/query] Search | [n]ext | [p]rev | [r #] Resume | [c #] Copy | [q]uit")

        try:
            choice = input(bold("Choice: ")).strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break

        if not choice:
            continue

        c_lower = choice.lower()

        if c_lower in ("q", "quit", "exit"):
            break
        elif c_lower in ("n", "next"):
            if page + 1 < total_pages:
                page += 1
            else:
                print(dim("Already at last page."))
        elif c_lower in ("p", "prev", "previous"):
            if page > 0:
                page -= 1
            else:
                print(dim("Already at first page."))
        elif choice.startswith("/"):
            query = choice[1:].strip()
            page = 0
        elif c_lower.startswith("s "):
            # Search syntax 's keyword'
            query = choice[2:].strip()
            page = 0
        elif c_lower == "clear":
            query = ""
            page = 0
        elif c_lower.startswith("r "):
            # Quick resume 'r 3'
            arg = choice[2:].strip()
            target = resolve_target(arg, filtered)
            if target:
                execute_resume(target)
                break
        elif c_lower.startswith("c "):
            # Quick copy 'c 3'
            arg = choice[2:].strip()
            target = resolve_target(arg, filtered)
            if target:
                if copy_to_clipboard(target.resume_cmd):
                    print(green(f"\n✔ Copied to clipboard: {bold(target.resume_cmd)}"))
                else:
                    print(yellow(f"\nCommand: {bold(target.resume_cmd)}"))
        else:
            # Check if user typed an index directly
            target = resolve_target(choice, filtered)
            if target:
                handle_conversation_selection(target)
                # After action, if user resumed, we exit
            else:
                # Treat unadorned text as search query
                query = choice
                page = 0

def resolve_target(arg: str, items: List[Conversation]) -> Optional[Conversation]:
    """Resolve an item either by 1-based index or by UUID/ID prefix."""
    if not arg:
        return None
    if arg.isdigit():
        idx = int(arg) - 1
        if 0 <= idx < len(items):
            return items[idx]
        print(red(f"Invalid index: {arg} (out of range)"))
        return None
    # Match by ID prefix
    for c in items:
        if c.id.lower().startswith(arg.lower()):
            return c
    print(red(f"No conversation matching '{arg}'"))
    return None

def handle_conversation_selection(conv: Conversation) -> None:
    """Sub-menu for a selected conversation."""
    display_conversation_detail(conv)
    while True:
        prompt_txt = (
            f"\n{bold('Select action:')} "
            f"[{green('r')}]esume | "
            f"[{cyan('c')}]opy command | "
            f"[{yellow('v')}]iew prompts | "
            f"[{bold('b')}]ack | "
            f"[{red('q')}]uit: "
        )
        try:
            action = input(prompt_txt).strip().lower()
        except (KeyboardInterrupt, EOFError):
            print()
            return

        if action in ("r", "resume"):
            execute_resume(conv)
            sys.exit(0)
        elif action in ("c", "copy"):
            if copy_to_clipboard(conv.resume_cmd):
                print(green(f"\n✔ Copied to clipboard: {bold(conv.resume_cmd)}"))
            else:
                print(yellow(f"\nCould not access system clipboard.\nCommand: {bold(conv.resume_cmd)}"))
        elif action in ("v", "view"):
            print("\n" + bold("All User Prompts in Session:"))
            for i, p in enumerate(conv.all_prompts, 1):
                print(f"  {yellow(f'[{i}]')} {p}")
        elif action in ("b", "back"):
            break
        elif action in ("q", "quit", "exit"):
            sys.exit(0)

# -----------------------------------------------------------------------------
# CLI Subcommand Handlers
# -----------------------------------------------------------------------------
def cmd_list(args: argparse.Namespace) -> None:
    convs = get_all_conversations(include_claude=args.all)
    if args.query:
        convs = [c for c in convs if c.matches(args.query)]

    limit = args.limit if args.limit > 0 else len(convs)
    slice_items = convs[:limit]

    if args.json:
        data = [c.to_dict() for c in slice_items]
        print(json.dumps(data, indent=2))
        return

    if not slice_items:
        print(yellow("No conversations found."))
        return

    term_width = min(shutil.get_terminal_size((80, 24)).columns, 110)
    print(f"\n{bold('Recent Conversations')} ({len(slice_items)} shown of {len(convs)}):")
    print(f" {bold('#'):<4} {bold('Time'):<10} {bold('ID'):<10} {bold('Turns'):<7} {bold('Context Preview')}")
    print(" " + "-" * (term_width - 2))

    for idx, c in enumerate(slice_items, 1):
        time_str = relative_time(c.updated_at)
        short_id = c.id[:8]
        turns_str = f"{c.turns_count}t"
        avail = max(20, term_width - 35)
        preview = c.title.replace("\n", " ")
        if len(preview) > avail:
            preview = preview[:avail - 3] + "..."
        prov = f"[{c.provider[0].upper()}] " if args.all else ""
        print(f" {cyan(str(idx)):<4} {dim(time_str):<10} {dim(short_id):<10} {yellow(turns_str):<7} {prov}{preview}")
    print()

def cmd_search(args: argparse.Namespace) -> None:
    convs = get_all_conversations(include_claude=args.all)
    results = [c for c in convs if c.matches(args.query)]

    if args.json:
        data = [c.to_dict() for c in results]
        print(json.dumps(data, indent=2))
        return

    if not results:
        print(yellow(f"No conversations found matching '{args.query}'."))
        return

    term_width = min(shutil.get_terminal_size((80, 24)).columns, 110)
    print(f"\n{bold('Search Results')} for '{cyan(args.query)}' ({len(results)} matches):")
    print(f" {bold('#'):<4} {bold('Time'):<10} {bold('ID'):<10} {bold('Turns'):<7} {bold('Context Preview')}")
    print(" " + "-" * (term_width - 2))

    limit = args.limit if args.limit > 0 else len(results)
    for idx, c in enumerate(results[:limit], 1):
        time_str = relative_time(c.updated_at)
        short_id = c.id[:8]
        turns_str = f"{c.turns_count}t"
        avail = max(20, term_width - 35)
        preview = c.title.replace("\n", " ")
        if len(preview) > avail:
            preview = preview[:avail - 3] + "..."
        prov = f"[{c.provider[0].upper()}] " if args.all else ""
        print(f" {cyan(str(idx)):<4} {dim(time_str):<10} {dim(short_id):<10} {yellow(turns_str):<7} {prov}{preview}")

    print(f"\n{dim('To resume:')} {bold('agy-hist resume <id>')}")
    print(f"{dim('To copy:')}   {bold('agy-hist copy <id>')}\n")

def cmd_show(args: argparse.Namespace) -> None:
    convs = get_all_conversations(include_claude=args.all)
    target = resolve_target(args.target, convs)
    if not target:
        sys.exit(1)
    display_conversation_detail(target)

def cmd_copy(args: argparse.Namespace) -> None:
    convs = get_all_conversations(include_claude=args.all)
    target = resolve_target(args.target, convs)
    if not target:
        sys.exit(1)
    if copy_to_clipboard(target.resume_cmd):
        print(green(f"✔ Copied resume command to clipboard:\n  {bold(target.resume_cmd)}"))
    else:
        print(yellow(f"Could not access clipboard. Command is:\n  {bold(target.resume_cmd)}"))

def cmd_resume(args: argparse.Namespace) -> None:
    convs = get_all_conversations(include_claude=args.all)
    target = resolve_target(args.target, convs)
    if not target:
        sys.exit(1)
    execute_resume(target)

def cmd_last(args: argparse.Namespace) -> None:
    convs = get_all_conversations(include_claude=args.all)
    if not convs:
        print(yellow("No conversations found."))
        sys.exit(1)
    last_conv = convs[0]

    if args.resume:
        execute_resume(last_conv)
    elif args.copy:
        if copy_to_clipboard(last_conv.resume_cmd):
            print(green(f"✔ Copied latest session command to clipboard:\n  {bold(last_conv.resume_cmd)}"))
        else:
            print(last_conv.resume_cmd)
    else:
        display_conversation_detail(last_conv)

# -----------------------------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        prog="agy-hist",
        description="Browse, search, and resume past Antigravity and AI agent conversations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  agy-hist                    Launch interactive browser
  agy-hist search scrollless  Find conversations mentioning 'scrollless'
  agy-hist list --limit 5     List 5 most recent conversations
  agy-hist last --copy        Copy resume command for latest conversation
  agy-hist resume 1           Resume conversation #1 directly
  agy-hist copy 083b3966      Copy resume command for conversation by UUID
        """
    )
    parser.add_argument("--all", action="store_true", help="Include other assistants (e.g., Claude Code)")

    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to run")

    # list
    p_list = subparsers.add_parser("list", help="List recent conversations")
    p_list.add_argument("-n", "--limit", type=int, default=15, help="Number of items to show (default: 15)")
    p_list.add_argument("-q", "--query", type=str, default="", help="Filter query")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")
    p_list.add_argument("--all", action="store_true", help="Include other assistants")

    # search
    p_search = subparsers.add_parser("search", help="Search conversation context")
    p_search.add_argument("query", type=str, help="Search keywords")
    p_search.add_argument("-n", "--limit", type=int, default=20, help="Maximum results (default: 20)")
    p_search.add_argument("--json", action="store_true", help="Output as JSON")
    p_search.add_argument("--all", action="store_true", help="Include other assistants")

    # show
    p_show = subparsers.add_parser("show", help="Show full details for a conversation")
    p_show.add_argument("target", type=str, help="Index (e.g., 1) or conversation UUID")
    p_show.add_argument("--all", action="store_true", help="Include other assistants")

    # copy
    p_copy = subparsers.add_parser("copy", help="Copy the resume command to clipboard")
    p_copy.add_argument("target", type=str, help="Index (e.g., 1) or conversation UUID")
    p_copy.add_argument("--all", action="store_true", help="Include other assistants")

    # resume
    p_resume = subparsers.add_parser("resume", help="Resume a conversation directly")
    p_resume.add_argument("target", type=str, help="Index (e.g., 1) or conversation UUID")
    p_resume.add_argument("--all", action="store_true", help="Include other assistants")

    # last
    p_last = subparsers.add_parser("last", help="Inspect or resume the most recent conversation")
    p_last.add_argument("-c", "--copy", action="store_true", help="Copy resume command to clipboard")
    p_last.add_argument("-r", "--resume", action="store_true", help="Resume latest conversation directly")
    p_last.add_argument("--all", action="store_true", help="Include other assistants")

    args = parser.parse_args()

    if args.subcommand == "list":
        cmd_list(args)
    elif args.subcommand == "search":
        cmd_search(args)
    elif args.subcommand == "show":
        cmd_show(args)
    elif args.subcommand == "copy":
        cmd_copy(args)
    elif args.subcommand == "resume":
        cmd_resume(args)
    elif args.subcommand == "last":
        cmd_last(args)
    else:
        # Default: launch interactive browser
        run_interactive_browser(include_claude=getattr(args, "all", False))

if __name__ == "__main__":
    main()
