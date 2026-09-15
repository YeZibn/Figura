# Repository Guidelines

## Project Structure & Module Organization

Figura is a chart-analysis workspace. Python source lives in
`src/chartagent/`: the Agent loop is in `agent.py`, provider access in
`client/`, sessions in `memory/`, tools in `tools/`, and the HTTP Gateway in
`gateway/`. Tests are under `tests/`, with image fixtures in
`tests/fixtures/` and `tests/chart_fixtures.py`. The React/Vite client is in
`frontend/src/`, with scripts in `frontend/scripts/`. `src-tauri/` contains the
optional Tauri shell. OpenSpec files are under `openspec/`.

## Build, Test, and Development Commands

Use the `agent` Conda environment for Python commands:

```bash
conda run -n agent python -m pytest -q
conda run -n agent python -m chartagent --agent
```

The `agent` environment is the canonical Python runtime for this repository.
It already provides `rapidocr`, which is a required dependency for OCR and
chart-understanding tests. If Python reports `No module named 'rapidocr'`,
first verify the active environment with:

```bash
conda run -n agent python -c "import rapidocr"
```

Do not diagnose this as a missing project dependency or switch to the system
Python interpreter before checking the `agent` environment.

For the frontend:

```bash
cd frontend
npm install
npm run dev              # mock/offline Vite client
npm run dev:gateway     # Gateway and Vite together
npm run build            # TypeScript check and production build
npm run smoke            # UI and launcher smoke checks
```

The Gateway launcher owns its child processes; stop it with Ctrl-C. Do not
start multiple launchers on the same ports.

## Coding Style & Naming Conventions

Use four-space indentation for Python and the existing TypeScript style in
`frontend/src` (functional React components and explicit types). Prefer
focused modules, descriptive names, and type annotations. Python
modules and functions use `snake_case`; classes use `PascalCase`; React
components use `PascalCase`. Keep user-facing client text in Simplified
Chinese and preserve technical identifiers such as `run_id` and tool names.
Run `git diff --check` before submitting changes. No repository-wide formatter
or linter is configured, so match surrounding code manually.

## Testing Guidelines

Add pytest coverage for Python behavior; reuse chart fixtures. Name tests
`test_<behavior>`; run the narrow test file first, then the full suite.
Frontend changes must pass `npm run build` and `npm run smoke`; Gateway
changes should include lifecycle, persistence, or HTTP regression coverage.

## Commit & Pull Request Guidelines

Use concise commits with the established prefixes, for example
`feat: add pie chart sensor`, `fix: release gateway child processes`, or
`refactor: unify run identity`. Keep unrelated changes separate. Pull
requests should explain the behavior change, list validation commands, note
configuration or migration impact, and include screenshots for visible UI
changes. Update relevant OpenSpec files when the behavior contract changes.

## Security & Configuration Tips

Copy `.env.example` to `.env`; never commit API keys or generated
session data. Keep Gateway services bound to loopback, use opaque attachment
and run IDs, and avoid exposing local paths or image bytes in logs, traces, or
committed fixtures.
