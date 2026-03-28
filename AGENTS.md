# Repository Guidelines

## Project Structure & Module Organization
Source code lives in `hackathon/`. Keep runtime modules there, for example `hackathon/turn_detector.py` for interruption logic and `hackathon/config.py` for settings. Project metadata and dependencies are defined in `pyproject.toml`; the pinned lockfile is `uv.lock`. `README.md` is currently minimal. There is no `tests/` directory yet; add one at the repo root when automated tests are introduced.

## Build, Test, and Development Commands
- `uv sync`: create/update the local environment from `pyproject.toml` and `uv.lock`.
- `uv run ruff check hackathon`: run linting and import/style checks.
- `uv run python -m compileall hackathon`: quick syntax smoke check for the package.
- `uv lock`: refresh `uv.lock` after dependency changes.

There is no application entrypoint yet, so contributors should validate changes by importing modules directly or running small targeted scripts with `uv run python -c "..."`

## Coding Style & Naming Conventions
Use Python 3.12+, 4-space indentation, and explicit type hints on public APIs. Follow Ruff settings in `pyproject.toml`: line length is `120`, import sorting is enforced, and Google-style docstrings are preferred. Use `snake_case` for functions and modules, `CapWords` for classes, and keep dataclass-based contracts small and explicit. Avoid unnecessary dependencies and keep modules source-agnostic where possible.

## Testing Guidelines
There is currently no committed automated test suite and no coverage gate. For now, validate changes with focused manual checks and lightweight commands such as `uv run ruff check hackathon` and `uv run python -m compileall hackathon`. If you add tests later, place them under `tests/`, name files `test_<feature>.py`, and keep them narrow and behavior-focused.

## Commit & Pull Request Guidelines
Recent history uses short subject lines such as `Add turn detector.` and `Initial commit`. Follow the same pattern: one concise imperative summary per commit, optionally with a trailing period. Pull requests should state the purpose, call out any API or dependency changes, and include the manual verification steps you ran. If config or environment expectations change, update `.env.example` or this guide in the same PR.

## Security & Configuration Tips
Do not commit secrets or local environment files. Keep real settings in local `.env` files and preserve `.env.example` as the public template.
