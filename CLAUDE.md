# Project: Field Check

> **Template Version:** visionary_template_1 v1.2
> **Last Updated:** 2026-03-03
> **Status:** Phase 1 — Package Skeleton

---

## Overview

**What:** A free, open-source CLI tool that scans a document corpus and generates a health report — file inventory, duplicates, corruption, PII risk, language distribution, encoding issues, and more
**Why:** Nobody answers "what's in my documents, and what will go wrong when I process them?" — this fills an uncontested diagnostic gap and builds audience for [Field](https://usefield.co)
**For whom:** ML engineers, data teams, and anyone preparing document corpora for RAG pipelines, embedding, or batch AI processing

---

## Tech Stack

**Language:** Python 3.11+
**Package Manager:** UV (development), pip/pipx (user install)
**CLI Framework:** Click
**Distribution:** PyPI (`pip install field-check`)

**Core Dependencies:**
- click — CLI framework
- rich — Terminal output + progress bars
- blake3 — Content hashing (Rust-backed, fast)
- pdfplumber — PDF text extraction + page count
- python-docx — DOCX text extraction
- charset-normalizer — Encoding detection
- jinja2 — HTML report templates
- filetype — Magic-byte file type detection (pure Python)

**Optional Extras:**
- `field-check[s3]` — boto3 for S3 scanning
- `field-check[gcs]` — google-cloud-storage for GCS scanning
- `field-check[azure]` — azure-storage-blob for Azure scanning
- `field-check[all-cloud]` — All cloud connectors

---

## Development Workflow

### Quick Reference Commands

**Install dependencies:**
```bash
uv sync
```

**Install locally (editable):**
```bash
uv pip install -e .
```

**Run tests:**
```bash
uv run pytest --cov --cov-fail-under=80
```

**Lint & format:**
```bash
uv run ruff check . && uv run ruff format --check .
```

**Run the CLI (dev):**
```bash
uv run field-check scan ./test-corpus/
```

### Standard Workflow

When making changes, follow this sequence:

1. **Make your changes** to the code
2. **Quick validation** - Ruff runs automatically via PostToolUse hooks
3. **Type check** - ty runs automatically via PostToolUse hooks
4. **Invariant check** - Runs automatically via PostToolUse hooks
5. **Run relevant tests** - Test the specific area you changed
6. **Review changes** - Use `/review` command or manual review
7. **Commit** - Use `/commit-push-pr` with conventional commit message

---

## Project Structure

```
field-check/
├── src/field_check/
│   ├── __init__.py           # Package version
│   ├── cli.py                # Click CLI entry point
│   ├── config.py             # .field-check.yaml loader
│   ├── scanner/
│   │   ├── __init__.py
│   │   ├── inventory.py      # File inventory (types, sizes, ages)
│   │   ├── dedup.py          # BLAKE3 exact dedup
│   │   ├── corruption.py     # Corrupt/encrypted/empty detection
│   │   ├── text.py           # Text extraction (pdfplumber, python-docx)
│   │   ├── sampling.py       # Stratified sampling framework
│   │   ├── scanned_pdf.py    # Scanned vs native PDF detection
│   │   ├── pii.py            # PII regex patterns
│   │   ├── language.py       # Language detection (Unicode + stop-words)
│   │   ├── encoding.py       # Encoding detection
│   │   └── simhash.py        # Near-duplicate detection (SimHash)
│   ├── report/
│   │   ├── __init__.py
│   │   ├── terminal.py       # Rich terminal report
│   │   ├── html.py           # Jinja2 HTML report
│   │   ├── json_report.py    # JSON export
│   │   └── csv_report.py     # CSV export
│   ├── cloud/
│   │   ├── __init__.py
│   │   ├── s3.py             # S3 connector (optional)
│   │   ├── gcs.py            # GCS connector (optional)
│   │   └── azure.py          # Azure connector (optional)
│   └── templates/
│       └── report.html       # Jinja2 HTML template
├── tests/
│   ├── __init__.py
│   ├── conftest.py           # Shared fixtures
│   ├── test_cli.py
│   ├── test_inventory.py
│   ├── test_dedup.py
│   └── ...
├── docs/
│   └── SPEC.md               # Technical specification
├── pyproject.toml
├── LICENSE                    # Apache 2.0
└── README.md
```

---

## Project Rules & Preferences

### Core Invariants

| # | Invariant | Meaning |
|---|-----------|---------|
| 1 | **Field Check Never Transmits Data** | All processing is local. Zero network calls unless scanning cloud storage. No telemetry. |
| 2 | **Diagnosis Only — Never Modify** | Never process, transform, fix, delete, or move any user files. Read-only scan. |
| 3 | **PII Content Never in Output** | PII scan shows counts and pattern types only. Never log or display matched content (unless `--show-pii-samples`). |
| 4 | **Sampled Results Show Confidence** | Any analysis based on sampling must display confidence intervals. No bare point estimates. |
| 5 | **Per-File Crash Isolation** | One malformed file must not kill the scan. Process pool isolation with per-file timeouts. |

### Import Restrictions

| Component | Forbidden Imports |
|-----------|------------------|
| `src/field_check/` (core) | boto3, google.cloud, azure.storage (use optional extras) |
| `src/field_check/cloud/s3.py` | google.cloud, azure.storage |
| `src/field_check/cloud/gcs.py` | boto3, azure.storage |
| `src/field_check/cloud/azure.py` | boto3, google.cloud |

### Always Do

- **Follow conventional commits format:**
  - `feat:` for new features
  - `fix:` for bug fixes
  - `docs:` for documentation
  - `refactor:` for code refactoring
  - `test:` for adding/updating tests
  - `chore:` for maintenance tasks

- **Write tests for new functionality** (80% coverage minimum)
- **Use structured logging** — `logging` stdlib with module-level loggers
- **Batch related operations** — 1 message = all related tool calls. Batch all TodoWrite items in one call, all independent file reads in parallel.
- **Keep files under 500 lines** — split large files into focused modules. If a file grows past 500 lines, refactor before adding more.
- **Label PII findings as "risk indicators"** — never "detection" (30-50% FP rate on SSN patterns)
- **Show estimated cost before cloud scans** — require explicit confirmation or `--yes` flag
- **Use process pool for file scanning** — thread pool is not crash-isolated

### Never Do

- **Never transmit user data** — no telemetry, no network calls from core
- **Never modify user files** — read-only scan, diagnosis only
- **Never display PII match content** — counts and types only (unless `--show-pii-samples`)
- **Never commit secrets** — use environment variables
- **Never log file content** — only metadata (path, size, type, hash)
- **Never use bare point estimates** — always include confidence intervals for sampled analyses

### Code Style Preferences

- **Python naming:** snake_case for variables/functions, PascalCase for classes
- **File naming:** snake_case.py
- **Max line length:** 100 characters
- **Indentation:** 4 spaces
- **Docstrings:** Google style
- **Type hints:** Required on all public functions

---

## Workflow Commands

This project uses the Visionary workflow:

### Core Workflow
- **`/init-project`** - Initialize project with vision, requirements, and roadmap
- **`/discuss-phase N`** - Capture implementation decisions for phase N
- **`/plan-phase N`** - Create atomic task plans for phase N
- **`/execute-phase N`** - Execute plans with fresh context and atomic commits
- **`/verify-work N`** - User acceptance testing for phase N

### Supporting Commands
- **`/quick`** - Fast execution for small, ad-hoc tasks
- **`/progress`** - Show current status and next steps
- **`/pause-work`** - Create handoff + document session
- **`/resume-work`** - Restore context from STATE.md + DEVLOG.md
- **`/add-todo`** - Capture ideas for later

### Milestone Management
- **`/complete-milestone`** - Archive milestone and tag release
- **`/new-milestone`** - Start a new version

### Codebase Intelligence
- **`/analyze-codebase`** - Bootstrap intelligence for existing code

### Planning & Execution
- **`/plan-w-team`** - Team-orchestrated planning with builder/validator agents
- **`/build <plan>`** - Deploy builder/validator agents to execute a plan
- **`/cook`** - Launch parallel subagents for concurrent work

### Research & Context
- **`/prime`** - Load project context (read-only)
- **`/question`** - Read-only research mode

### Quality & Review
- **`/commit-push-pr`** - Automated commit, push, and PR creation
- **`/test`** - Smart test runner based on changes
- **`/explain`** - Non-technical code explanations
- **`/review`** - Comprehensive code review
- **`/full-review-pipeline`** - Complete code review pipeline with quality gates
- **`/check-invariants`** - Validate code against project-defined invariants

### Status & Monitoring
- **`/update-status-line`** - Write custom key-value pairs to status line display

---

## Task Management

This project uses persistent, dependency-aware task tracking.

### Environment Setup

Project uses these environment variables (configured in `.claude/settings.json`):
- `CLAUDE_CODE_TASK_LIST_ID=field-check` for persistent tasks
- `CLAUDE_SESSION_TAG=main` for session identification

Tasks persist across sessions in `~/.claude/tasks/field-check/`.

### Task Naming Convention

**Format:**
```
[<Phase>-<Plan>] Step <N>: <Verb> <object>
```

**Examples:**
```
[1-A] Step 1: Create pyproject.toml with click entry point
[2-A] Step 2: Implement BLAKE3 dedup scanner
[BG] pytest full suite
[UAT] Verify terminal report output
```

**Rules:**
1. Always include phase-plan identifier in brackets
2. Steps numbered sequentially starting at 1
3. Use specific file/function names, not vague descriptions
4. Background tasks use prefix: `[BG]`
5. Verification tasks use prefix: `[UAT]`

### Quick Reference

| Action | Command |
|--------|---------|
| View tasks | `/tasks` (built-in) |
| Pause work | `/pause-work` |
| Resume work | `/resume-work` |

### Task Queue Commands (Multi-Session)

| Command | Description |
|---------|-------------|
| `/add-task` | Add a task to the persistent work queue |
| `/list-tasks` | View all tasks in the work queue |
| `/claim-task` | Claim a task for the current session |
| `/complete-task` | Mark a claimed task as complete |
| `/remove-task` | Remove a task from the queue |
| `/tandem` | Launch an additional worker session |

> **Tip:** Use `/tandem` to spawn parallel workers that can claim tasks from the shared queue.

| Status | Meaning |
|--------|---------|
| `[ ]` | Pending |
| `[→]` | In progress |
| `[✓]` | Complete |
| `[!]` | Blocked |

### Multi-Session Coordination

When multiple sessions work on the same task list:

**Task Claiming:**
- Append `(@session-tag)` when marking task `[→]` in_progress
- Only claiming session can mark `[✓]` complete
- Any session can mark `[!]` blocked

**Stale Task Recovery:**
- Tasks claimed >30 min with no activity are stale
- Force unclaim with documentation: `(@main, unclaimed from @worker-2 - stale)`
- Verify no partial changes before continuing

---

## Specialized Agents Available

### Team Agents (used by `/build`)
- **`team/builder`** (opus, cyan) - Implements code with per-edit ruff/ty validation
- **`team/validator`** (opus, yellow) - Reviews code (read-only, cannot Write/Edit)

### Utility Agents
- **`meta-agent`** (sonnet, magenta) - Creates new agents on demand from Anthropic docs
- **`research`** (sonnet, magenta) - Deep web research with multi-source verification
- **`code-simplifier`** - Reviews code and suggests simplifications
- **`verify-app`** - QA testing and verification after changes
- **`debug-helper`** - Systematic debugging assistance

### Session Agents
- **`greeting`** (haiku, green) - Proactive session greeting
- **`work-completion`** (haiku, green) - TTS work summaries

---

## Testing Strategy

**Test Types:**
- Unit tests: `tests/` — per-module tests for each scanner and reporter
- Integration tests: `tests/integration/` — end-to-end scan of test corpora

**Coverage Goals:** 80% minimum

**Running Tests:**
```bash
# All tests
uv run pytest --cov --cov-fail-under=80

# Specific module
uv run pytest tests/test_inventory.py -v

# With output
uv run pytest -s
```

**Test Corpus:**
- `tests/fixtures/` — small set of known test files (PDF, DOCX, TXT, etc.)
- Include: corrupt PDF, encrypted PDF, scanned PDF, empty file, symlink

---

## Lessons Learned

> The AI automatically adds entries when mistakes are corrected or patterns are discovered.

### 2026-03-06
- `importlib.reload()` in mock tests pollutes class identity — use `teardown_method` to restore modules and avoid `isinstance` on reloaded classes
- `patch.dict("sys.modules", ...)` removes entries added during context — pre-import modules in `setup_class` to prevent cleanup
- Don't `import numpy` in tests when it's not installed — build pure Python mock arrays instead

### 2026-03-03
- Project initialized from visionary_template_1 v1.2

---

## Design References

> Search on-demand via Grep/Read. Never modify design docs.

| Reference | Path | When to use |
|-----------|------|-------------|
| Technical spec | `docs/SPEC.md` | Authoritative source for all design decisions |
| Build plan | `.planning/build-plan.md` | Phase plans and task lists |
| Field codebase | (external — FieldV3 repo) | Reusable components (see SPEC.md § Reusable) |

---

## Context Management

> The AI's quality can degrade as conversations get long. Use these practices to maintain peak performance.

### Session Start Checklist
At the start of each session, The AI should read:
1. This file (CLAUDE.md)
2. STATE.md - Current focus, recent decisions, handoff notes
3. DEVLOG.md - Recent sessions, active bugs, progress history
4. `.planning/intel/summary.md` - Codebase patterns (if exists)

### When to Start a Fresh Session
- After completing a major feature or phase
- When the AI starts giving inconsistent responses
- After 30+ back-and-forth messages
- When switching to a completely different area of the codebase

### Best Practices
- **Keep tasks focused:** 2-3 related items per session works best
- **Use STATE.md:** Track progress across sessions
- **Use `/quick`:** For small, isolated changes
- **Use Plan Mode:** For complex features (Shift+Tab twice)

### Signs of Context Degradation
- The AI forgets earlier decisions
- Responses become generic
- Code suggestions contradict established patterns
- The AI asks about things already discussed

### Recovery Steps
1. Update STATE.md and DEVLOG.md with current status (`/pause-work`)
2. Start a new AI session
3. The AI reads fresh context from CLAUDE.md, STATE.md, DEVLOG.md, and intel

---

## Autonomous Learning

> The AI should proactively maintain project knowledge without being asked.

### When to Update CLAUDE.md (Lessons Learned)

The AI MUST add a new entry to "Lessons Learned" when:
1. **User corrects a mistake** - Record what was wrong and the correct approach
2. **A bug is found in The AI's code** - Document the pattern that caused it
3. **User expresses preference** - "I prefer X over Y" → record it
4. **A better pattern is discovered** - During refactoring or review
5. **An assumption proves wrong** - Document the correct understanding

**Format:**
```markdown
### YYYY-MM-DD
- [What happened] - [Correct approach going forward]
```

### When to Update STATE.md

The AI MUST update STATE.md:
1. **After completing any task** - Update "Session Log" with what was done
2. **When making a decision** - Add to "Recent Decisions" table
3. **When hitting a blocker** - Add to "Open Questions / Blockers"
4. **Before any significant code change** - Note current focus
5. **Periodically during long tasks** - Every 3-4 tool uses, checkpoint progress

### Self-Diagnosis: Context Degradation

The AI should **proactively suggest a fresh session** when noticing:
- Repeating suggestions that were already rejected
- Forgetting decisions made earlier in the conversation
- Giving generic responses instead of project-specific ones
- Making errors in code that contradict established patterns

**What to say:**
> "I'm noticing some context degradation. I recommend we save progress with `/pause-work` and start a fresh session. This will help me give you better responses."

---

## Notes for the AI

> Special instructions for the AI assistant working on this project

- Always validate against the 5 core invariants + import restrictions
- Follow existing patterns in the codebase
- Ask when uncertain about requirements — reference the spec (docs/SPEC.md)
- Update STATE.md after completing work
- Reference this file for project conventions
- Phase order is strictly sequential — execute top to bottom
- Within each phase, tasks are in dependency order — execute top to bottom
- This is a CLI tool distributed via PyPI — user experience matters (clear error messages, progress bars, helpful output)
- Target installed size <50MB for core (no cloud extras)

---

*Template: visionary_template_1 v1.2*
*Documentation: See SETUP.md for initialization instructions*
