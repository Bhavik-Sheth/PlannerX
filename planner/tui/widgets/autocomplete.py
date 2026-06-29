"""
planner/tui/widgets/autocomplete.py

AutocompleteList — handles filtering and displaying slash commands and project files.
"""

import re
from pathlib import Path
from textual.widgets import OptionList
from textual.widgets.option_list import Option
from rich.text import Text


class AutocompleteList(OptionList):
    """Dropdown list for autocompleting slash commands and files."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.show_type = None  # "command" or "file"
        self.current_options = []
        self.all_commands = {
            "/init": "Initialize PLANNER/ directory structure",
            "/describe": "Append raw idea and structure it",
            "/run": "Run the planning pipeline to generate drafts",
            "/status": "Show planning tracker/status",
            "/approve": "Approve a planning document",
            "/reset": "Clear and regenerate a planning document",
            "/module": "Add/list code module specs",
            "/update": "Request a mid-session plan/requirement change",
            "/consistency": "Run documentation consistency audit",
            "/finalize": "Compile CLAUDE.md and exit planning",
            "/config": "Configure LLM provider, model, and API keys",
            "/help": "Show help message",
            "/abort": "Abort pending confirmation/prompt",
        }
        self.cached_files = []

    def refresh_file_cache(self, project_path: Path) -> None:
        """Scan the project path recursively for files to autocomplete."""
        files = []
        skip_dirs = {
            ".git",
            ".venv",
            "__pycache__",
            ".pytest_cache",
            "planboard.egg-info",
            "plannerx.egg-info",
        }
        try:
            for p in project_path.rglob("*"):
                if p.is_file():
                    try:
                        relative = p.relative_to(project_path)
                        # Check if any parent part of p is in skip_dirs or starts with .
                        parts = relative.parts
                        if any(part in skip_dirs or part.startswith(".") for part in parts):
                            continue
                        files.append(str(relative))
                    except ValueError:
                        continue
        except Exception:
            pass
        self.cached_files = sorted(files)

    def update_suggestions(self, text: str, project_path: Path) -> bool:
        """
        Updates the suggestions based on current input text.
        Returns True if suggestions are shown, False if hidden.
        """
        if not text:
            self.hide()
            return False

        # 1. Check for Slash Commands (text starts with / and has no spaces)
        if text.startswith("/") and " " not in text:
            query = text.lower()
            matches = {k: v for k, v in self.all_commands.items() if k.startswith(query)}
            if matches:
                self.show_type = "command"
                self.clear_options()
                self.current_options = list(matches.keys())
                for cmd, desc in matches.items():
                    label = Text()
                    label.append(f"{cmd:<14}", style="bold cyan")
                    label.append(f" {desc}", style="dim")
                    self.add_option(Option(label, id=cmd))
                self.show()
                return True
            else:
                self.hide()
                return False

        # 2. Check for File tagging (typing @ followed by text, or text ends with @word)
        file_match = re.search(r"@([^\s]*)$", text)
        if file_match:
            query = file_match.group(1).lower()
            if not self.cached_files:
                self.refresh_file_cache(project_path)

            matches = [f for f in self.cached_files if query in f.lower()]
            if matches:
                self.show_type = "file"
                self.clear_options()
                # Limit to top 20 files
                self.current_options = matches[:20]
                for file_path in self.current_options:
                    label = Text()
                    label.append("@", style="bold yellow")
                    label.append(file_path, style="green")
                    self.add_option(Option(label, id=file_path))
                self.show()
                return True
            else:
                self.hide()
                return False

        self.hide()
        return False

    def show(self) -> None:
        self.styles.display = "block"

    def hide(self) -> None:
        self.styles.display = "none"
        self.show_type = None
        self.current_options = []
