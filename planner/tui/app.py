"""
planner/tui/app.py

PlannerApp — the main Textual App class that ties the panels together,
defines keyboard bindings, and routes events to the backend agents/commands.
"""

import builtins
import contextlib
import queue
import sys
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DirectoryTree

from planner.tui.widgets.architecture_panel import ArchitecturePanel
from planner.tui.widgets.chat_input import ChatInput
from planner.tui.widgets.file_tree import PlannerFileTree
from planner.tui.widgets.viewer_panel import ViewerPanel


class PlannerApp(App):
    """The main TUI Application for PlannerX."""

    CSS_PATH = "planner.css"
    TITLE = "PlannerX"
    SUB_TITLE = "AI-driven project planner"

    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
        ("escape", "focus_chat", "Focus Chat"),
    ]

    def __init__(self, planner_path: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.planner_path = planner_path or (Path.cwd() / "PLANNER")
        self.input_queue = queue.Queue()
        self.waiting_for_input = False
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
        self.query_one("#viewer-panel").border_title = "RESPONSE / VIEWER PANEL"
        self.query_one("#chat-input").border_title = "CHAT INPUT"

        # Auto-focus the chat input on launch
        self.query_one("#chat-input").focus()

        # Print welcome/warning messages in ViewerPanel
        viewer = self.query_one("#viewer-panel")
        if not self.planner_path.exists():
            viewer.write_output("[yellow]Warning: PLANNER/ directory not found.[/yellow]")
            viewer.write_output("Please initialize with [bold cyan]/init[/bold cyan] or [bold cyan]planner init[/bold cyan].")
            viewer.write_output("Displaying current working directory in the File Tree instead.")
        else:
            viewer.write_output("[green]PlannerX TUI Shell initialized successfully.[/green]")
            viewer.write_output("Use [bold cyan]/help[/bold cyan] to see available commands.")

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
                self.waiting_for_input = True

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
                    self.waiting_for_input = False

        self.run_worker(worker, thread=True)

    def action_focus_chat(self) -> None:
        """Focus the Chat Input panel."""
        self.query_one("#chat-input").focus()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        """Handle file selection from the file tree, opening the file in the Viewer Panel."""
        self.current_selected_file = event.path
        viewer = self.query_one("#viewer-panel")
        viewer.show_file(event.path)

    def on_chat_input_command_submitted(self, event: ChatInput.CommandSubmitted) -> None:
        """Process chat input submissions (either slash commands or text change requests)."""
        cmd = event.command.strip()
        if not cmd:
            return

        # 1. If we are waiting for grilling/confirmation input
        if self.waiting_for_input:
            self.waiting_for_input = False
            viewer = self.query_one("#viewer-panel")
            viewer.write_output(f"[bold cyan]Answer: {cmd}[/bold cyan]")
            self.input_queue.put(cmd)
            return

        # 2. Normal command processing
        viewer = self.query_one("#viewer-panel")

        if cmd.startswith("/"):
            # Slash commands
            parts = cmd.split(maxsplit=1)
            name = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""

            if name == "/help":
                self._cmd_help()
            elif name == "/init":
                self._cmd_init()
            elif name == "/describe":
                self._cmd_describe(arg)
            elif name == "/run":
                self._cmd_run()
            elif name == "/status":
                self._cmd_status()
            elif name == "/approve":
                self._cmd_approve(arg)
            elif name == "/reset":
                self._cmd_reset(arg)
            elif name == "/module":
                self._cmd_module(arg)
            elif name == "/consistency":
                self._cmd_consistency()
            elif name == "/finalize":
                self._cmd_finalize()
            elif name == "/config":
                self._cmd_config(arg)
            elif name == "/abort":
                viewer.write_output("[yellow]No active prompt to abort.[/yellow]")
            else:
                viewer.write_output(f"[red]Unknown command: {name}. Type /help for a list of commands.[/red]")
        else:
            # Plain text iteration change requests
            self._handle_change_request(cmd)

    def _cmd_help(self) -> None:
        """Display helper instructions inside the viewer panel."""
        viewer = self.query_one("#viewer-panel")
        viewer.write_output("[bold green]Available Commands:[/bold green]")
        viewer.write_output("  [bold cyan]/init[/bold cyan]                    - Initialize PLANNER/ directory structure")
        viewer.write_output("  [bold cyan]/describe <text>[/bold cyan]         - Append raw idea and structure it")
        viewer.write_output("  [bold cyan]/run[/bold cyan]                    - Run the planning pipeline to generate drafts")
        viewer.write_output("  [bold cyan]/status[/bold cyan]                 - Show planning tracker/status")
        viewer.write_output("  [bold cyan]/approve <file>[/bold cyan]         - Approve a planning document")
        viewer.write_output("  [bold cyan]/reset <file>[/bold cyan]           - Clear and regenerate a planning document")
        viewer.write_output("  [bold cyan]/module add <name>[/bold cyan]      - Add a new code module spec")
        viewer.write_output("  [bold cyan]/module list[/bold cyan]            - List existing module specs")
        viewer.write_output("  [bold cyan]/consistency[/bold cyan]             - Run documentation consistency audit")
        viewer.write_output("  [bold cyan]/config[/bold cyan]                  - Configure LLM provider, model, and API keys")
        viewer.write_output("  [bold cyan]/finalize[/bold cyan]                - Compile CLAUDE.md and exit planning")
        viewer.write_output("  [bold cyan]/help[/bold cyan]                    - Show this help message")
        viewer.write_output("  [bold cyan]/abort[/bold cyan]                   - Abort a pending confirmation or question prompt")
        viewer.write_output("\n[dim]To request changes, click a file in the tree to select it and type your change request message directly.[/dim]")

    def _cmd_init(self) -> None:
        """Scaffold the planning project."""
        from planner.files.scaffold import scaffold_project

        def worker():
            scaffold_project()
            print("✅ PLANNER/ initialized successfully.")
            # Set path reactive property to PLANNER/ so file tree loads it
            def update_ui():
                file_tree = self.query_one("#file-tree")
                file_tree.path = self.planner_path
            self.call_from_thread(update_ui)

        self.run_in_background(worker)

    def _cmd_describe(self, text: str) -> None:
        """Add project description and run structuring agent."""
        if not text:
            self.query_one("#viewer-panel").write_output("[red]Usage: /describe <your project idea text>[/red]")
            return

        if not self.planner_path.exists():
            self.query_one("#viewer-panel").write_output("[red]Error: PLANNER/ directory not found. Run `/init` first.[/red]")
            return

        def worker():
            from planner.agents.structuring_agent import structuring_agent
            from planner.files.writer import write_planner_file
            from planner.state import PlannerState

            # 1. Append to RawIdea.md
            write_planner_file(self.planner_path / "RawIdea.md", text)
            print(f"✅ Appended to RawIdea.md ({len(text)} chars).")

            # 2. Run structuring agent
            print("⏳ Structuring idea via LLM...")
            state = PlannerState(project_path=str(self.planner_path))
            result = structuring_agent(state)
            if result.status == "needs_input":
                print(f"[INFO] {result.pending_questions[0]}")
            else:
                print("✅ StructuredIdea.md updated.")

        self.run_in_background(worker)

    def _cmd_run(self) -> None:
        """Run the full LangGraph planning orchestrator."""
        if not self.planner_path.exists():
            self.query_one("#viewer-panel").write_output("[red]Error: PLANNER/ directory not found. Run `/init` first.[/red]")
            return

        def worker():
            from planner.graph import run_graph
            print("🚀 Starting planner run...\n")
            final_state = run_graph(str(self.planner_path))
            if final_state.status == "done":
                print("\n✅ Planning run complete. Run `/status` or select a file to review.")
            elif final_state.status == "error":
                print(f"\n[ERROR] Run stopped: {final_state.error_message}")
            elif final_state.status == "needs_input":
                print(f"\n[INFO] Run paused, needs user input:")
                for q in final_state.pending_questions:
                    print(f" - {q}")

        self.run_in_background(worker)

    def _cmd_status(self) -> None:
        """Show the current status by displaying Tracker.md."""
        tracker_path = self.planner_path / "Tracker.md"
        if not tracker_path.exists():
            self.query_one("#viewer-panel").write_output("[yellow]Tracker.md not found. Run `/run` first.[/yellow]")
            return
        self.query_one("#viewer-panel").show_file(tracker_path)

    def _cmd_approve(self, file_arg: str) -> None:
        """Mark a documentation file as approved in Tracker.md."""
        filename = file_arg.strip()
        if not filename:
            filename = self.get_selected_relative_path()
            if not filename:
                self.query_one("#viewer-panel").write_output("[red]Please specify a file to approve, e.g. `/approve PRD.md`[/red]")
                return

        target_path = self.planner_path / filename
        if not target_path.exists():
            self.query_one("#viewer-panel").write_output(f"[red]Error: {filename} not found in PLANNER/.[/red]")
            return

        def worker():
            from planner.agents.tracker_agent import tracker_agent
            from planner.state import PlannerState

            state = PlannerState(project_path=str(self.planner_path))
            tracker_path = self.planner_path / "Tracker.md"
            approved = []
            if tracker_path.exists():
                for line in tracker_path.read_text(encoding="utf-8").splitlines():
                    if "✅" in line and ".md" in line:
                        parts = [p.strip() for p in line.split("|") if p.strip()]
                        if parts and parts[-1] == "✅":
                            approved.append(parts[0])

            if filename not in approved:
                approved.append(filename)

            state.approved_files = approved
            print(f"⏳ Updating Tracker.md for approval of {filename}...")
            tracker_agent(state)
            print(f"✅ {filename} marked as approved in Tracker.md.")

        self.run_in_background(worker)

    def _cmd_reset(self, file_arg: str) -> None:
        """Clear a planning file and re-run its agent after confirmation."""
        filename = file_arg.strip()
        if not filename:
            filename = self.get_selected_relative_path()
            if not filename:
                self.query_one("#viewer-panel").write_output("[red]Please specify a file to reset, e.g. `/reset PRD.md`[/red]")
                return

        target_path = self.planner_path / filename
        if not target_path.exists():
            self.query_one("#viewer-panel").write_output(f"[red]Error: {filename} not found in PLANNER/.[/red]")
            return

        def run_reset():
            try:
                choice = input(f"Are you sure you want to clear {filename} and re-run its agent? [y/N]: ").strip().lower()
            except Exception:
                choice = "n"
            if choice != "y":
                print("Reset aborted.")
                return

            print(f"🗑 Clearing {filename}...")
            target_path.write_text("", encoding="utf-8")

            _AGENT_MAP = {
                "StructuredIdea.md":  "structuring",
                "PRD.md":             "prd",
                "TRD.md":             "trd",
                "Schema.md":          "schema",
                "DesignDecisions.md": "design",
                "AppFlow.md":         "appflow",
                "Rules.md":           "rules",
                "ImplementationPlan.md": "implementation",
                "Tracker.md":         "tracker",
            }
            agent_name = None
            if filename.startswith("MODULES/"):
                agent_name = "modules"
            elif filename.startswith("ARCHITECTURE_DIAGRAMS/"):
                agent_name = "diagram"
            else:
                agent_name = _AGENT_MAP.get(filename)

            if not agent_name:
                print(f"No agent associated with {filename}. File cleared.")
                return

            print(f"⏳ Re-running {agent_name} agent...")
            from planner.main import _run_single_agent
            _run_single_agent(str(self.planner_path), agent_name, filename)
            print(f"✅ {filename} regenerated.")

            # Refresh viewer if this file was select-focused
            def reload_view():
                if self.current_selected_file == target_path:
                    self.query_one("#viewer-panel").show_file(target_path)
            self.call_from_thread(reload_view)

        self.run_in_background(run_reset)

    def _cmd_module(self, arg: str) -> None:
        """Add or list modules."""
        arg = arg.strip()
        parts = arg.split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""
        subarg = parts[1].strip() if len(parts) > 1 else ""

        if subcmd == "add":
            if not subarg:
                self.query_one("#viewer-panel").write_output("[red]Usage: /module add <name>[/red]")
                return

            if not self.planner_path.exists():
                self.query_one("#viewer-panel").write_output("[red]Error: PLANNER/ directory not found. Run `/init` first.[/red]")
                return

            def worker():
                from planner.agents.module_planner_agent import module_planner_agent
                from planner.files.reader import read_planner_file
                from planner.state import PlannerState

                si_path = self.planner_path / "StructuredIdea.md"
                structured_idea = read_planner_file(si_path, use_cache=False).strip() if si_path.exists() else ""

                state = PlannerState(
                    project_path=str(self.planner_path),
                    structured_idea=structured_idea,
                    context_files={"__module_name__": subarg},
                )
                print(f"⏳ Generating spec for module '{subarg}'...")
                module_planner_agent(state)
                print(f"✅ MODULES/{subarg}.md created.")

            self.run_in_background(worker)

        elif subcmd == "list" or not subcmd:
            modules_dir = self.planner_path / "MODULES"
            viewer = self.query_one("#viewer-panel")
            if not modules_dir.exists():
                viewer.write_output("[yellow]No MODULES/ directory found.[/yellow]")
                return
            files = sorted(modules_dir.glob("*.md"))
            if not files:
                viewer.write_output("[yellow]No modules defined yet. Use `/module add <name>`.[/yellow]")
                return
            viewer.write_output("[bold green]Modules List:[/bold green]")
            for f in files:
                size = f.stat().st_size
                status = "✅" if size > 0 else "⬜"
                viewer.write_output(f"  {status}  {f.name}")
        else:
            self.query_one("#viewer-panel").write_output(f"[red]Unknown module subcommand: {subcmd}. Use `/module add` or `/module list`[/red]")

    def _cmd_consistency(self) -> None:
        """Run read-only consistency checks across planning docs."""
        if not self.planner_path.exists():
            self.query_one("#viewer-panel").write_output("[red]Error: PLANNER/ directory not found. Run `/init` first.[/red]")
            return

        def worker():
            from planner.agents.orchestrator import run_consistency_check
            from planner.state import PlannerState

            state = PlannerState(project_path=str(self.planner_path))
            print("🔍 Running consistency check...\n")
            report = run_consistency_check(state)
            print(report)

        self.run_in_background(worker)

    def _cmd_finalize(self) -> None:
        """Compile final CLAUDE.md execution environment document."""
        if not self.planner_path.exists():
            self.query_one("#viewer-panel").write_output("[red]Error: PLANNER/ directory not found. Run `/init` first.[/red]")
            return

        def worker():
            try:
                choice = input("This will compile CLAUDE.md and signal that planning is complete. Continue? [y/N]: ").strip().lower()
            except Exception:
                choice = "n"
            if choice != "y":
                print("Finalize aborted.")
                return

            print("⏳ Compiling CLAUDE.md...")
            from planner.main import _compile_claude_md
            _compile_claude_md(str(self.planner_path))
            print("✅ CLAUDE.md written to project root. Planning phase complete.")

        self.run_in_background(worker)

    def _cmd_config(self, arg: str) -> None:
        """Handle LLM provider, model, and api key configuration via TUI."""
        arg = arg.strip()
        viewer = self.query_one("#viewer-panel")
        
        from planner.llm import (
            get_active_provider,
            get_active_model,
            set_active_provider,
            set_active_model,
            set_api_key,
            get_api_key_status,
            list_providers
        )

        if not arg:
            # 1. Print the current configuration
            provider = get_active_provider()
            model = get_active_model()
            keys_status = get_api_key_status()
            
            viewer.write_output("[bold green]Current LLM Configuration:[/bold green]")
            viewer.write_output(f"  Active Provider: [bold cyan]{provider or 'None'}[/bold cyan]")
            viewer.write_output(f"  Active Model:    [bold cyan]{model or 'None'}[/bold cyan]")
            viewer.write_output("\n[bold green]API Keys Status:[/bold green]")
            for p, is_set in keys_status.items():
                status_icon = "[green][✅] set[/green]" if is_set else "[red][⬜] missing[/red]"
                viewer.write_output(f"  {p:<12}: {status_icon}")
            
            viewer.write_output("\n[dim]Usage:[/dim]")
            viewer.write_output("  [bold cyan]/config provider <name>[/bold cyan]   - Set the active LLM provider")
            viewer.write_output("  [bold cyan]/config model <name>[/bold cyan]      - Set the active LLM model")
            viewer.write_output("  [bold cyan]/config apikey <provider> <key>[/bold cyan] - Set the API key for a provider")
            return

        parts = arg.split(maxsplit=2)
        subcmd = parts[0].lower()
        subarg1 = parts[1].strip() if len(parts) > 1 else ""
        subarg2 = parts[2].strip() if len(parts) > 2 else ""

        providers = list_providers()

        if subcmd == "provider":
            if not subarg1:
                viewer.write_output(f"[red]Usage: /config provider <{'|'.join(providers)}>[/red]")
                return
            if subarg1 not in providers:
                viewer.write_output(f"[red]Unknown provider '{subarg1}'. Must be one of: {', '.join(providers)}[/red]")
                return

            # Pre-flight package check
            from planner.llm import PROVIDER_REGISTRY
            import importlib
            entry = PROVIDER_REGISTRY[subarg1]
            try:
                importlib.import_module(entry["import_path"])
            except ImportError:
                package_name = entry["import_path"].replace('_', '-')
                viewer.write_output(f"[yellow]⚠️ Warning: Provider '{subarg1}' requires the '{entry['import_path']}' package.[/yellow]")
                viewer.write_output(f"[yellow]Run: [bold]uv add {package_name}[/bold] in your terminal to install it.[/yellow]")

            set_active_provider(subarg1)
            viewer.write_output(f"[green]✅ Active provider set to: {subarg1}[/green]")

        elif subcmd == "model":
            if not subarg1:
                viewer.write_output("[red]Usage: /config model <model_name>[/red]")
                return
            model_name = subarg1
            if subarg2:
                model_name = f"{subarg1} {subarg2}"
            set_active_model(model_name)
            viewer.write_output(f"[green]✅ Active model set to: {model_name}[/green]")

        elif subcmd == "apikey" or subcmd == "key":
            if not subarg1 or not subarg2:
                viewer.write_output("[red]Usage: /config apikey <provider> <key_value>[/red]")
                return
            if subarg1 not in providers:
                viewer.write_output(f"[red]Unknown provider '{subarg1}'. Must be one of: {', '.join(providers)}[/red]")
                return
            try:
                set_api_key(subarg1, subarg2)
                viewer.write_output(f"[green]✅ API key for provider '{subarg1}' successfully saved to .env[/green]")
            except Exception as e:
                viewer.write_output(f"[red]Error saving API key: {e}[/red]")
        else:
            viewer.write_output(f"[red]Unknown config subcommand: {subcmd}. Use provider, model, or apikey.[/red]")

    def _handle_change_request(self, text: str) -> None:
        """Handle plain text entries by sending them to ChatOrchestrator as conversational brain messages."""
        def run_orchestrator():
            from planner.agents.chat_orchestrator import chat_orchestrator
            import os
            from pathlib import Path

            # 1. Gather files and active file context
            existing = []
            if self.planner_path.exists():
                existing = [f.name for f in self.planner_path.glob("*.md")]
                modules_dir = self.planner_path / "MODULES"
                if modules_dir.exists():
                    existing.extend([f"MODULES/{f.name}" for f in modules_dir.glob("*.md")])
                diagrams_dir = self.planner_path / "ARCHITECTURE_DIAGRAMS"
                if diagrams_dir.exists():
                    existing.extend([f"ARCHITECTURE_DIAGRAMS/{f.name}" for f in diagrams_dir.glob("*.md")])
            
            active_file = self.get_selected_relative_path()

            # 2. Invoke conversational brain
            print("⏳ Chat Orchestrator is thinking...")
            try:
                chat_action = chat_orchestrator(
                    user_message=text,
                    chat_history=self.chat_history,
                    existing_files=existing,
                    active_file=active_file,
                )
            except Exception as e:
                print(f"[red]Failed to invoke Chat Orchestrator: {e}[/red]")
                return

            # Print Orchestrator response message
            print(f"\n[bold green]Orchestrator:[/bold green] {chat_action.response_message}\n")

            # Store in chat history
            self.chat_history.append({"role": "user", "content": text})
            self.chat_history.append({"role": "assistant", "content": chat_action.response_message})
            if len(self.chat_history) > 30:
                self.chat_history = self.chat_history[-30:]

            # 3. Dispatch structured action
            action = chat_action.action
            target = chat_action.target_file or ""
            module = chat_action.module_name or ""
            text_content = chat_action.text_content or ""

            if action == "chat":
                pass
            elif action == "init":
                print("▶ Dispatching action: initialize project")
                from planner.files.scaffold import scaffold_project
                scaffold_project()
                print("✅ PLANNER/ initialized successfully.")
                def update_ui():
                    self.query_one("#file-tree").path = self.planner_path
                self.call_from_thread(update_ui)

            elif action == "describe":
                print(f"▶ Dispatching action: describe project idea")
                from planner.files.writer import write_planner_file
                from planner.agents.structuring_agent import structuring_agent
                from planner.state import PlannerState
                
                if not self.planner_path.exists():
                    from planner.files.scaffold import scaffold_project
                    scaffold_project()
                    def update_ui():
                        self.query_one("#file-tree").path = self.planner_path
                    self.call_from_thread(update_ui)
                
                write_planner_file(self.planner_path / "RawIdea.md", text_content)
                print(f"✅ Appended to RawIdea.md.")
                print("⏳ Structuring idea via LLM...")
                state = PlannerState(project_path=str(self.planner_path))
                result = structuring_agent(state)
                if result.status == "needs_input":
                    print(f"[INFO] {result.pending_questions[0]}")
                else:
                    print("✅ StructuredIdea.md updated.")

            elif action == "run":
                print("▶ Dispatching action: run planning pipeline")
                from planner.graph import run_graph
                final_state = run_graph(str(self.planner_path))
                if final_state.status == "done":
                    print("\n✅ Planning run complete. Select a file or check Tracker.md to review.")
                elif final_state.status == "error":
                    print(f"\n[ERROR] Run stopped: {final_state.error_message}")
                elif final_state.status == "needs_input":
                    print(f"\n[INFO] Run paused, needs user input:")
                    for q in final_state.pending_questions:
                        print(f" - {q}")

            elif action == "status":
                print("▶ Dispatching action: show status")
                tracker_path = self.planner_path / "Tracker.md"
                if tracker_path.exists():
                    def show_tracker():
                        self.query_one("#viewer-panel").show_file(tracker_path)
                    self.call_from_thread(show_tracker)
                else:
                    print("[yellow]Tracker.md not found. Start planning first.[/yellow]")

            elif action == "approve":
                print(f"▶ Dispatching action: approve {target}")
                if not target:
                    print("[red]No target file resolved to approve.[/red]")
                    return
                target_path = self.planner_path / target
                if not target_path.exists():
                    print(f"[red]Error: {target} not found in PLANNER/.[/red]")
                    return
                
                from planner.agents.tracker_agent import tracker_agent
                from planner.state import PlannerState

                state = PlannerState(project_path=str(self.planner_path))
                tracker_path = self.planner_path / "Tracker.md"
                approved = []
                if tracker_path.exists():
                    for line in tracker_path.read_text(encoding="utf-8").splitlines():
                        if "✅" in line and ".md" in line:
                            parts = [p.strip() for p in line.split("|") if p.strip()]
                            if parts and parts[-1] == "✅":
                                approved.append(parts[0])

                if target not in approved:
                    approved.append(target)

                state.approved_files = approved
                print(f"⏳ Updating Tracker.md for approval of {target}...")
                tracker_agent(state)
                print(f"✅ {target} marked as approved in Tracker.md.")

            elif action == "reset":
                print(f"▶ Dispatching action: reset {target}")
                if not target:
                    print("[red]No target file resolved to reset.[/red]")
                    return
                target_path = self.planner_path / target
                if not target_path.exists():
                    print(f"[red]Error: {target} not found in PLANNER/.[/red]")
                    return

                try:
                    choice = input(f"Are you sure you want to clear {target} and re-run its agent? [y/N]: ").strip().lower()
                except Exception:
                    choice = "n"
                if choice != "y":
                    print("Reset aborted.")
                    return

                print(f"🗑 Clearing {target}...")
                target_path.write_text("", encoding="utf-8")

                _AGENT_MAP = {
                    "StructuredIdea.md":  "structuring",
                    "PRD.md":             "prd",
                    "TRD.md":             "trd",
                    "Schema.md":          "schema",
                    "DesignDecisions.md": "design",
                    "AppFlow.md":         "appflow",
                    "Rules.md":           "rules",
                    "ImplementationPlan.md": "implementation",
                    "Tracker.md":         "tracker",
                }
                agent_name = _AGENT_MAP.get(target)
                if not agent_name:
                    print(f"No agent associated with {target}. File cleared.")
                    return

                print(f"⏳ Re-running {agent_name} agent...")
                from planner.main import _run_single_agent
                _run_single_agent(str(self.planner_path), agent_name)
                print(f"✅ {target} regenerated.")

                def reload_view():
                    if self.current_selected_file == target_path:
                        self.query_one("#viewer-panel").show_file(target_path)
                self.call_from_thread(reload_view)

            elif action == "module_add":
                print(f"▶ Dispatching action: add module '{module}'")
                if not module:
                    print("[red]No module name resolved to add.[/red]")
                    return
                from planner.agents.module_planner_agent import module_planner_agent
                from planner.files.reader import read_planner_file
                from planner.state import PlannerState

                si_path = self.planner_path / "StructuredIdea.md"
                structured_idea = read_planner_file(si_path, use_cache=False).strip() if si_path.exists() else ""

                state = PlannerState(
                    project_path=str(self.planner_path),
                    structured_idea=structured_idea,
                    context_files={"__module_name__": module},
                )
                print(f"⏳ Generating spec for module '{module}'...")
                module_planner_agent(state)
                print(f"✅ MODULES/{module}.md created.")

            elif action == "module_list":
                print("▶ Dispatching action: list modules")
                modules_dir = self.planner_path / "MODULES"
                if not modules_dir.exists():
                    print("[yellow]No MODULES/ directory found.[/yellow]")
                    return
                files = sorted(modules_dir.glob("*.md"))
                if not files:
                    print("[yellow]No modules defined yet.[/yellow]")
                    return
                print("[bold green]Modules List:[/bold green]")
                for f in files:
                    size = f.stat().st_size
                    status = "✅" if size > 0 else "⬜"
                    print(f"  {status}  {f.name}")

            elif action == "consistency":
                print("▶ Dispatching action: run consistency check")
                from planner.agents.orchestrator import run_consistency_check
                from planner.state import PlannerState

                state = PlannerState(project_path=str(self.planner_path))
                print("🔍 Running consistency check...\n")
                report = run_consistency_check(state)
                print(report)

            elif action == "finalize":
                print("▶ Dispatching action: finalize planning")
                try:
                    choice = input("This will compile CLAUDE.md and signal that planning is complete. Continue? [y/N]: ").strip().lower()
                except Exception:
                    choice = "n"
                if choice != "y":
                    print("Finalize aborted.")
                    return

                print("⏳ Compiling CLAUDE.md...")
                from planner.main import _compile_claude_md
                _compile_claude_md(str(self.planner_path))
                print("✅ CLAUDE.md written to project root. Planning phase complete.")

            elif action == "change_request":
                print(f"▶ Dispatching action: apply feedback/change request to {target}")
                if not target:
                    print("[red]No target file resolved for change request.[/red]")
                    return
                target_path = self.planner_path / target
                if not target_path.exists():
                    print(f"[red]Error: {target} not found in PLANNER/.[/red]")
                    return
                
                import importlib
                from planner.files.reader import read_planner_file
                from planner.state import PlannerState

                si_path = self.planner_path / "StructuredIdea.md"
                structured_idea = read_planner_file(si_path, use_cache=False).strip() if si_path.exists() else ""

                state = PlannerState(
                    project_path=str(self.planner_path),
                    structured_idea=structured_idea,
                    current_file=target,
                )
                state.grill_answers[f"Change request for {target}"] = text_content

                print(f"⏳ Sending change request to agent...")
                print(f"  ▶ Feedback: {text_content}")

                _AGENT_MAP = {
                    "StructuredIdea.md":  "structuring",
                    "PRD.md":             "prd",
                    "TRD.md":             "trd",
                    "Schema.md":          "schema",
                    "DesignDecisions.md": "design",
                    "AppFlow.md":         "appflow",
                    "Rules.md":           "rules",
                    "ImplementationPlan.md": "implementation",
                    "Tracker.md":         "tracker",
                }
                agent_name = None
                if target.startswith("MODULES/"):
                    agent_name = "modules"
                elif target.startswith("ARCHITECTURE_DIAGRAMS/"):
                    agent_name = "diagram"
                else:
                    agent_name = _AGENT_MAP.get(target)

                if not agent_name:
                    print(f"No agent associated with {target}. Feedback cannot be processed.")
                    return

                if agent_name == "diagram":
                    from planner.agents.architecture_diagram_agent import generate_diagrams
                    generate_diagrams(str(self.planner_path))
                    print(f"✅ {target} updated with your changes.")
                else:
                    if agent_name == "modules":
                        module_name = target.split("/")[-1].replace(".md", "")
                        state.context_files["__module_name__"] = module_name

                    agents = {
                        "structuring": "planner.agents.structuring_agent.structuring_agent",
                        "prd":         "planner.agents.prd_agent.prd_agent",
                        "trd":         "planner.agents.trd_agent.trd_agent",
                        "schema":      "planner.agents.schema_agent.schema_agent",
                        "design":      "planner.agents.design_agent.design_agent",
                        "appflow":     "planner.agents.appflow_agent.appflow_agent",
                        "rules":       "planner.agents.rules_agent.rules_agent",
                        "implementation": "planner.agents.implementation_agent.implementation_agent",
                        "tracker":     "planner.agents.tracker_agent.tracker_agent",
                        "modules":     "planner.agents.module_planner_agent.module_planner_agent",
                    }
                    dotted = agents[agent_name]
                    module_path, fn_name = dotted.rsplit(".", 1)
                    module_obj = importlib.import_module(module_path)
                    fn = getattr(module_obj, fn_name)

                    fn(state)
                    print(f"✅ {target} updated with your changes.")

                def reload_view():
                    if self.current_selected_file:
                        self.query_one("#viewer-panel").show_file(self.current_selected_file)
                self.call_from_thread(reload_view)

        self.run_in_background(run_orchestrator)
