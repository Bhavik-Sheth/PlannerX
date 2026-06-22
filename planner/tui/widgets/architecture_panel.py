"""
planner/tui/widgets/architecture_panel.py

ArchitecturePanel — top-right panel that renders the active .mmd diagram
using Rich's Syntax highlighter (mermaid lexer).

Provides refresh_diagram(path) so Phase 7 can update it live.
"""

from pathlib import Path

from rich.text import Text
from textual.widgets import Static


_PLACEHOLDER = Text.assemble(
    ("⬡  Architecture Diagram Panel\n", "bold green"),
    ("─" * 42 + "\n", "dim green"),
    ("No diagrams yet. Run ", "dim"),
    ("/diagram", "bold cyan"),
    (" or ", "dim"),
    ("/run", "bold cyan"),
    (" to generate them.", "dim"),
)


class ArchitecturePanel(Static):
    """Top-right panel — renders the active Mermaid architecture diagram."""

    def __init__(self, planner_path: Path, **kwargs) -> None:
        super().__init__(**kwargs)
        self.planner_path = planner_path

    def on_mount(self) -> None:
        self.refresh_diagram()

    def refresh_diagram(self, path: Path | None = None) -> None:
        """
        Load and display a Mermaid diagram from *path*.
        Falls back to SystemArchitecture.mmd, then SystemDesign.mmd.
        Shows a placeholder when no diagram content is available.
        """
        candidates = (
            [path] if path else [
                self.planner_path / "ARCHITECTURE_DIAGRAMS" / "SystemArchitecture.md",
                self.planner_path / "ARCHITECTURE_DIAGRAMS" / "SystemDesign.md",
            ]
        )

        for candidate in candidates:
            if candidate and candidate.exists():
                content = candidate.read_text(encoding="utf-8").strip()
                if content:
                    from rich.markdown import Markdown
                    self.update(Markdown(content))
                    return

        self.update(_PLACEHOLDER)
