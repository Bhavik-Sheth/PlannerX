import os
from pathlib import Path

PLANNER_FILES = [
    "RawIdea.md",
    "Constraints.md",
    "StructuredIdea.md",
    "PRD.md",
    "TRD.md",
    "DesignDecisions.md",
    "AppFlow.md",
    "Schema.md",
    "ImplementationPlan.md",
    "Tracker.md",
    "Rules.md",
    "CLAUDE.md",
]

DIAGRAM_FILES = [
    "SystemDesign.md",
    "SystemArchitecture.md",
    "FolderStructure.md",
    "DataFlow.md",
]

def scaffold_project(base_path: str = ".") -> None:
    """
    Creates the PLANNER/ directory structure and all initial empty files.
    """
    root = Path(base_path)
    planner_dir = root / "PLANNER"
    diagrams_dir = planner_dir / "ARCHITECTURE_DIAGRAMS"
    modules_dir = planner_dir / "MODULES"

    # Create directories
    planner_dir.mkdir(parents=True, exist_ok=True)
    diagrams_dir.mkdir(parents=True, exist_ok=True)
    modules_dir.mkdir(parents=True, exist_ok=True)

    # Create empty files in PLANNER/
    for filename in PLANNER_FILES:
        filepath = planner_dir / filename
        if not filepath.exists():
            filepath.touch()

    # Create empty files in PLANNER/ARCHITECTURE_DIAGRAMS/
    for filename in DIAGRAM_FILES:
        filepath = diagrams_dir / filename
        if not filepath.exists():
            filepath.touch()
