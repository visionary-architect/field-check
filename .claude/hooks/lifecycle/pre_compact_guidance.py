#!/usr/bin/env python3
"""
PreCompact guidance hook — inject project context reminders before compaction.

Fires on: PreCompact (trigger: manual/auto)
Sync: YES — output is shown to the AI before context is compressed.

What it does:
Reads CLAUDE.md and extracts critical project context (invariants, import
restrictions, key conventions) and outputs them as a reminder. This helps
the AI maintain quality after context compaction by re-surfacing rules
that might otherwise be lost in compression.
"""
import json
import re
from pathlib import Path


def find_project_root() -> Path:
    """Walk up from CWD to find project root."""
    markers = ['CLAUDE.md', 'pyproject.toml', 'package.json', '.git']
    current = Path.cwd()
    for parent in [current, *list(current.parents)]:
        if any((parent / m).exists() for m in markers):
            return parent
    return current


def extract_section(
    content: str, heading: str, level: int = 3,
) -> str | None:
    """Extract a markdown section by heading."""
    prefix = "#" * level
    pattern = rf"^{prefix}\s+{re.escape(heading)}\s*$"
    match = re.search(pattern, content, re.MULTILINE)
    if not match:
        return None

    start = match.end()
    # Find next heading at same or higher level
    next_heading = re.search(
        rf"^{'#' * level}\s+", content[start:], re.MULTILINE,
    )
    end = start + next_heading.start() if next_heading else len(content)
    return content[start:end].strip()


def build_guidance(project_root: Path) -> str:
    """Build context guidance from CLAUDE.md."""
    claude_md = project_root / "CLAUDE.md"
    if not claude_md.exists():
        return ""

    try:
        content = claude_md.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    sections: list[str] = []

    # Extract project overview
    overview = extract_section(content, "Overview", level=2)
    if overview:
        # Take first 3 lines only
        lines = overview.strip().splitlines()[:3]
        sections.append("PROJECT: " + " | ".join(
            line.strip().removeprefix("**").split("**")[0].strip()
            for line in lines if line.strip()
        ))

    # Extract core invariants table
    if "Core Invariants" in content:
        inv_section = extract_section(
            content, "Core Invariants", level=3,
        )
        if inv_section:
            # Extract table rows (skip header + separator)
            rows = [
                line.strip()
                for line in inv_section.splitlines()
                if line.strip().startswith("|")
                and not line.strip().startswith("|---")
                and not line.strip().startswith("| #")
            ]
            if rows:
                sections.append(
                    "INVARIANTS (must preserve):\n"
                    + "\n".join(f"  {r}" for r in rows[:10])
                )

    # Extract import restrictions table
    if "Import Restrictions" in content:
        imp_section = extract_section(
            content, "Import Restrictions", level=3,
        )
        if imp_section:
            rows = [
                line.strip()
                for line in imp_section.splitlines()
                if line.strip().startswith("|")
                and not line.strip().startswith("|---")
                and not line.strip().startswith("| Component")
            ]
            if rows:
                sections.append(
                    "IMPORT RESTRICTIONS:\n"
                    + "\n".join(f"  {r}" for r in rows[:10])
                )

    # Extract "Never Do" rules
    if "Never Do" in content:
        never_section = extract_section(
            content, "Never Do", level=3,
        )
        if never_section:
            rules = [
                line.strip()
                for line in never_section.splitlines()
                if line.strip().startswith("- **Never")
                or line.strip().startswith("- **No ")
            ]
            if rules:
                sections.append(
                    "NEVER DO:\n"
                    + "\n".join(f"  {r}" for r in rules[:10])
                )

    # Extract current phase from STATE.md
    state_md = project_root / "STATE.md"
    if state_md.exists():
        try:
            state = state_md.read_text(
                encoding="utf-8", errors="replace",
            )
            phase_match = re.search(
                r"\*\*Phase:\*\*\s*(.+)", state,
            )
            status_match = re.search(
                r"\*\*Status:\*\*\s*(.+)", state,
            )
            if phase_match or status_match:
                phase_info = []
                if status_match:
                    phase_info.append(
                        f"Status: {status_match.group(1).strip()}",
                    )
                if phase_match:
                    phase_info.append(
                        f"Phase: {phase_match.group(1).strip()}",
                    )
                sections.append(
                    "CURRENT STATE: " + " | ".join(phase_info),
                )
        except OSError:
            pass

    if not sections:
        return ""

    return (
        "CONTEXT PRESERVATION REMINDER "
        "(project rules to maintain after compaction):\n\n"
        + "\n\n".join(sections)
    )


def main() -> None:
    project_root = find_project_root()
    guidance = build_guidance(project_root)

    if guidance:
        # Output as hook result — Claude Code shows this to the AI
        print(json.dumps({
            "decision": "approve",
            "reason": guidance,
        }))
    else:
        print(json.dumps({
            "decision": "approve",
            "reason": "No project context to inject.",
        }))


if __name__ == "__main__":
    main()
