"""
planner/tui/widgets/chat_input.py

ChatInput — bottom-right panel that takes user commands and chat messages.
Extends Input and posts a custom CommandSubmitted message when the user hits Enter.
Supports autocomplete for slash commands and project files.
"""

import re
from textual.message import Message
from textual.widgets import Input


class ChatInput(Input):
    """Input panel for typing commands and messages."""

    class CommandSubmitted(Message):
        """Custom message posted when a command is submitted."""
        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle default Input submission and post custom CommandSubmitted message."""
        command = event.value.strip()
        if command:
            self.post_message(self.CommandSubmitted(command))
        self.value = ""

    async def _on_key(self, event) -> None:
        """Intercept keys to navigate and complete autocomplete suggestions if open."""
        try:
            autocomplete = self.app.query_one("#autocomplete-list")
        except Exception:
            await super()._on_key(event)
            return

        if autocomplete and autocomplete.styles.display == "block":
            if event.key == "up":
                event.prevent_default()
                event.stop()
                idx = autocomplete.highlighted
                if idx is not None and idx > 0:
                    autocomplete.highlighted = idx - 1
                elif idx is None and autocomplete.current_options:
                    autocomplete.highlighted = len(autocomplete.current_options) - 1
                return
            elif event.key == "down":
                event.prevent_default()
                event.stop()
                idx = autocomplete.highlighted
                if idx is not None and idx < len(autocomplete.current_options) - 1:
                    autocomplete.highlighted = idx + 1
                elif idx is None and autocomplete.current_options:
                    autocomplete.highlighted = 0
                return
            elif event.key in ("enter", "tab"):
                idx = autocomplete.highlighted
                if idx is not None and 0 <= idx < len(autocomplete.current_options):
                    event.prevent_default()
                    event.stop()
                    self.complete_option(autocomplete, autocomplete.current_options[idx])
                    return
            elif event.key == "escape":
                event.prevent_default()
                event.stop()
                autocomplete.hide()
                return

        await super()._on_key(event)

    def complete_option(self, autocomplete, option: str) -> None:
        """Complete the input value with the selected autocomplete option."""
        if autocomplete.show_type == "command":
            self.value = option + " "
            self.cursor_position = len(self.value)
        elif autocomplete.show_type == "file":
            text = self.value
            new_text = re.sub(r"@([^\s]*)$", f"@{option}", text)
            self.value = new_text
            self.cursor_position = len(self.value)
        autocomplete.hide()

    def watch_value(self, value: str) -> None:
        """Watch value changes to update the suggestions dropdown."""
        try:
            autocomplete = self.app.query_one("#autocomplete-list")
        except Exception:
            return

        if autocomplete:
            # Pass app's project_path or fallback to workspace root
            project_path = getattr(self.app, "planner_path", None)
            if project_path:
                project_path = project_path.parent
            autocomplete.update_suggestions(value, project_path)
