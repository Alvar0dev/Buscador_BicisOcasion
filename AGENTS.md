# Buscador BiciOcasion - Agent Guidelines

Guidelines and protocols for AI agents working on this workspace.

## Memory Protocol (Engram)

1. **Check Engram First**:
   - Before designing, refactoring, or taking architectural decisions, consult Engram tools.
   - Project name: `buscador biciocasion`.
   - Tool priority: `mem_current_project` -> `mem_context` -> `mem_search` / `mem_get_observation`.

2. **Respect Saved Decisions**:
   - Do not propose architectures or flows that contradict past decisions registered in Engram without technical justification and user discussion.

3. **Record Key Decisions**:
   - Register architectural milestones, bug fixes, and discoveries using `mem_save`.

## Workspace Details

- **Directory**: `G:\Proyectos OpenCode\Buscador BiciOcasion`
- **Remote**: `https://github.com/Alvar0dev/Buscador_BicisOcasion.git`
- **Tests**: `python test_buscador.py`
- **Architecture**:
  - Scrapers: `scraper_base.py`, `scrapers/bike_ocasion.py`, `scrapers/buhobike.py`, `scrapers/upway.py`, `scrapers/mammoth.py`
  - Scoring & Evaluation: `evaluator.py`, `gemini_classifier.py`
  - Orchestration: `main.py`
  - Notifications: `notifier.py` (Telegram bot credentials in `.env`)
