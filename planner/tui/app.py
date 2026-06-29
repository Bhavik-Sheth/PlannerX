"""
planner/tui/app.py

PlannerApp — the main Textual App class that ties the panels together,
defines keyboard bindings, and routes events to the backend agents/commands.
"""

import builtins
import contextlib
import queue
import sys
import threading
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DirectoryTree

from planner.tui.widgets.architecture_panel import ArchitecturePanel
from planner.tui.widgets.chat_input import ChatInput
from planner.tui.widgets.file_tree import PlannerFileTree
from planner.tui.widgets.viewer_panel import ViewerPanel


from planner.utils import resolve_relative_path, resolve_agent


class PlannerApp(App):
    """The main TUI Application for PlannerX."""

    CSS_PATH = "planner.css"
    TITLE = "PlannerX"
    SUB_TITLE = "AI-driven project planner"

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
        ("escape", "focus_chat", "Focus Chat"),
        ("ctrl+e", "toggle_architecture", "Expand/Collapse Architecture"),
        ("f2", "toggle_architecture", "Expand/Collapse Architecture"),
    ]

    def __init__(self, planner_path: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.planner_path = planner_path or (Path.cwd() / "PLANNER")
        self.input_queue = queue.Queue()
        # Fix 10: use threading.Event instead of a plain bool for thread-safe
        # cross-thread signaling between the Textual main thread and worker threads.
        self._input_event = threading.Event()
        self.current_selected_file = None
        self.chat_history = []

    def get_selected_relative_path(self) -> str:
        """Return the selected file path relative to the planner directory."""
        if not self.current_selected_file:
            return ""
        try:
            return str(self.current_selected_file.relative_to(self.planner_path))
        except ValueError:
            return self.current_selected_file.name

    def compose(self) -> ComposeResult:
        # Determine the directory path to display.
        # If the planner_path doesn't exist, show current directory as fallback.
        tree_path = self.planner_path if self.planner_path.exists() else Path.cwd()

        with Horizontal():
            yield PlannerFileTree(tree_path, id="file-tree")
            with Vertical(id="right-pane"):
                yield ArchitecturePanel(self.planner_path, id="architecture-panel")
                yield ViewerPanel(id="viewer-panel")
                yield ChatInput(id="chat-input", placeholder="Type /command or chat message...")

    def on_mount(self) -> None:
        # Set panel titles
        self.query_one("#file-tree").border_title = "FILE VIEW"
        self.query_one("#architecture-panel").border_title = "ARCHITECTURE PANEL"
        self.query_one("#architecture-panel").border_subtitle = "Ctrl+E or F2 to Maximize"
        self.query_one("#viewer-panel").border_title = "RESPONSE / VIEWER PANEL"
        self.query_one("#chat-input").border_title = "CHAT INPUT"

        # Auto-focus the chat input on launch
        self.query_one("#chat-input").focus()

        # Instantiate ExecutiveAgent
        from planner.agents.executive_agent import ExecutiveAgent
        from planner.state import load_state
        self.state = load_state(str(self.planner_path))
        self.executive = ExecutiveAgent(self.state)

        # Print welcome/warning messages in ViewerPanel and run startup flow
        viewer = self.query_one("#viewer-panel")
        
        def startup_worker():
            rendered = self.executive.handle_startup()
            self.call_from_thread(viewer.write_output, rendered)

        self.run_in_background(startup_worker)

        # Start directory/architecture watcher
        self.start_watcher()

    def start_watcher(self) -> None:
        """Spawn a background thread to watch for file system changes and refresh UI."""
        from watchfiles import watch
        import threading

        def watch_loop():
            try:
                # Watch the parent directory (project root) to handle non-existence of PLANNER/
                for changes in watch(self.planner_path.parent):
                    if not self.is_running:
                        break

                    # Check for updates in PLANNER/
                    has_planner_change = any(
                        Path(path).is_relative_to(self.planner_path)
                        for _, path in changes
                    )

                    if has_planner_change:
                        # Reload the file tree
                        self.call_from_thread(self.query_one("#file-tree").reload)

                        # If architecture diagrams changed, refresh architecture panel
                        has_arch_change = any(
                            Path(path).is_relative_to(self.planner_path / "ARCHITECTURE_DIAGRAMS")
                            for _, path in changes
                        )
                        if has_arch_change:
                            self.call_from_thread(self.query_one("#architecture-panel").refresh_diagram)
            except Exception:
                pass

        t = threading.Thread(target=watch_loop, daemon=True)
        t.start()

    def run_in_background(self, func, *args, **kwargs) -> None:
        """Run a function in a background worker thread, redirecting stdout/stderr to TUI."""
        def worker():
            viewer = self.query_one("#viewer-panel")

            # Helper to write to viewer thread-safely
            def write_to_viewer(text: str):
                self.call_from_thread(viewer.write_output, text)

            class ThreadSafeStream:
                def __init__(self, callback):
                    self.callback = callback
                    self.buffer = ""

                def write(self, data):
                    self.buffer += data
                    while "\n" in self.buffer:
                        line, self.buffer = self.buffer.split("\n", 1)
                        self.callback(line)
                    return len(data)

                def flush(self):
                    if self.buffer:
                        self.callback(self.buffer)
                        self.buffer = ""

            # Save original input and patch
            original_input = builtins.input

            def tui_input(prompt=""):
                if prompt:
                    sys.stdout.write(prompt)
                    sys.stdout.flush()

                # Signal that we are waiting for user input
                self._input_event.set()

                # Retrieve from queue (blocks until user submits response)
                ans = self.input_queue.get()

                if ans == "/abort":
                    raise KeyboardInterrupt("Action aborted by user.")
                return ans

            builtins.input = tui_input
            stream = ThreadSafeStream(write_to_viewer)

            with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
                try:
                    func(*args, **kwargs)
                except KeyboardInterrupt:
                    write_to_viewer("[yellow]⚠️ Operation cancelled/aborted.[/yellow]")
                except Exception as e:
                    write_to_viewer(f"[red]Error: {e}[/red]")
                finally:
                    builtins.input = original_input
                    self._input_event.clear()

        self.run_worker(worker, thread=True)

    def action_focus_chat(self) -> None:
        """Focus the Chat Input panel."""
        self.query_one("#chat-input").focus()

    def action_toggle_architecture(self) -> None:
        """Toggle the architecture panel expansion."""
        arch_panel = self.query_one("#architecture-panel")
        viewer_panel = self.query_one("#viewer-panel")
        chat_input = self.query_one("#chat-input")
        
        is_expanding = not arch_panel.has_class("expanded")
        
        arch_panel.toggle_class("expanded")
        viewer_panel.toggle_class("collapsed")
        chat_input.toggle_class("collapsed")
        
        if is_expanding:
            arch_panel.border_title = "ARCHITECTURE PANEL (MAXIMIZED)"
            arch_panel.border_subtitle = "Ctrl+E or F2 to Minimize"
            arch_panel.focus()
        else:
            arch_panel.border_title = "ARCHITECTURE PANEL"
            arch_panel.border_subtitle = "Ctrl+E or F2 to Maximize"
            chat_input.focus()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Handle file selection from the file tree, opening the file in the Viewer Panel."""
        self.current_selected_file = event.path
        viewer = self.query_one("#viewer-panel")
        viewer.show_file(event.path)

    def on_chat_input_command_submitted(self, event: ChatInput.CommandSubmitted) -> None:
        """Process chat input submissions via ExecutiveAgent."""
        cmd = event.command.strip()
        if not cmd:
            return

        # 1. If we are waiting for grilling/confirmation input (legacy/fallback)
        if self._input_event.is_set():
            self._input_event.clear()
            viewer = self.query_one("#viewer-panel")
            viewer.write_output(f"[bold cyan]Answer: {cmd}[/bold cyan]")
            self.input_queue.put(cmd)
            return

        # 2. Process using ExecutiveAgent in a background thread
        def run_cmd():
            parsed_cmd, rendered_output = self.executive.process(cmd)
            
            # Print output thread-safely to viewer
            self.call_from_thread(self.query_one("#viewer-panel").write_output, rendered_output)
            
            # If the command changed active workspace files, reload UI tree/diagram
            if parsed_cmd:
                cmd_type = parsed_cmd.get("command")
                if cmd_type in ("init", "reset", "reset_confirmed", "edit", "approve"):
                    self.call_from_thread(self.query_one("#file-tree").reload)
                if cmd_type in ("diagram",):
                    self.call_from_thread(self.query_one("#architecture-panel").refresh_diagram)

        self.run_in_background(run_cmd)
