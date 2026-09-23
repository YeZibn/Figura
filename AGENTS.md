# Repository Guidelines

## Project Structure & Module Organization

Figura is a chart-analysis workspace. Python source lives in
`src/chartagent/` and is organized by responsibility:

- `agent/` owns the main loop, turns, artifacts, panel routing, measurement
  flow, recovery, and review-gate coordination.
- `measurement/` owns measurement sessions, evidence, scope, lifecycle, and
  quality; `review/` owns generated-chart review models and policy.
- `prompting/` owns the layered Markdown prompt bundle; static policy,
  workflow, evidence, and response rules are separate assets.
- `client/`, `memory/`, `tools/`, and `spec/` provide model access, durable
  sessions, tool integration, and ChartSpec models.
- `gateway/` owns HTTP/SSE transport, persistence, run lifecycle, attachments,
  and read-only evaluation adapters. `evaluation/` owns evaluation bundles,
  readers, timelines, and reports.

Tests are under `tests/`, with image fixtures in `tests/fixtures/` and reusable
chart data in `tests/chart_fixtures.py`. The React/Vite client is in
`frontend/src/`: `api/` contains the stable client façade and Gateway/mock
adapters, `domain/` contains non-React logic, `components/` contains UI,
`types/` contains protocol domains, and `styles/` contains the imported style
layers. `App.tsx` should remain workspace orchestration rather than absorb
transport, event normalization, or large presentation blocks.

Frontend scripts live in `frontend/scripts/`. `src-tauri/` contains the
optional Tauri shell. OpenSpec planning and main specifications live under
`openspec/`; completed changes belong in `openspec/changes/archive/`.

## Architecture & Compatibility Boundaries

- Preserve `ChartAgentClient`, `api/gatewayClient.ts`, and
  `types/protocol.ts` as compatibility façades unless a change explicitly
  migrates every caller.
- Keep frontend dependencies directed from types and pure domain logic toward
  API adapters and components. Components must not call Gateway transport
  directly; Gateway and mock modes must implement the same client contract.
- Keep one owner for run event merging, sequence cursors, history compensation,
  reconnect, and terminal convergence. Do not reintroduce lifecycle closures in
  multiple components.
- Treat attachment, panel, run, attempt, evidence, review, and artifact IDs as
  opaque protocol values. Preserve HTTP/SSE field names and `runId:sequence`
  event identity across refactors.
- Prompt policy belongs in the relevant asset under
  `src/chartagent/prompting/assets/`. Keep `static/agent.md` focused on stable
  responsibilities; put detailed process rules in `static/workflow.md`, and
  keep runtime/tools/artifact facts in the dynamic layers.
- Measurement output is candidate evidence, not automatic truth. The main
  Agent chooses evidence by passing actual refs during assembly or explicitly
  calling a scoped measurement tool; do not add a separate measurement
  decision state or queue. Preserve ChartSpec validation, generated-chart VLM
  review, and publication-state boundaries when changing orchestration.

## Build, Test, and Development Commands

Use the `agent` Conda environment for Python commands:

```bash
conda run -n agent python -m pytest -q
conda run -n agent python -m chartagent --agent
conda run -n agent python -m chartagent.gateway
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
npm run dev:gateway      # Gateway and Vite together
npm run build            # TypeScript check and production build
npm run smoke            # UI and launcher smoke checks
npm run smoke:launcher   # launcher lifecycle and port cleanup checks
```

The Gateway launcher owns its child processes; stop it with Ctrl-C. Do not
start multiple launchers on the same ports. Real evaluation runs use
`conda run -n agent python -m chartagent.evaluation`; follow
`docs/real-chart-diagnostic.md` for managed versus external-Gateway options.

## Coding Style & Naming Conventions

Use four-space indentation for Python and the existing TypeScript style in
`frontend/src` (functional React components and explicit types). Prefer
focused modules, descriptive names, and type annotations. Python
modules and functions use `snake_case`; classes use `PascalCase`; React
components use `PascalCase`. Keep user-facing client text in Simplified
Chinese and preserve technical identifiers such as `run_id` and tool names.
Keep protocol types independent of React and keep reusable domain functions
free of component state. CSS changes should preserve the stable
`styles/global.css` import entry and place rules in the matching style layer.
Run `git diff --check` before submitting changes. No repository-wide formatter
or linter is configured, so match surrounding code manually.

## Testing Guidelines

Add pytest coverage for Python behavior; reuse chart fixtures. Name tests
`test_<behavior>`; run the narrow test file first, then the full suite.
Frontend changes must pass `npm run build` and `npm run smoke`; Gateway
launcher changes must also pass `npm run smoke:launcher`. Gateway changes
should include lifecycle, persistence, HTTP/SSE, or recovery regression
coverage as appropriate. Prompt changes should run `tests/test_prompting.py`
and the relevant Agent/CLI tests. Structure-only refactors should retain or add
compatibility tests instead of relying only on import success.

## Commit & Pull Request Guidelines

Use concise Conventional Commits with a meaningful scope in parentheses. The
scope names the affected capability or subsystem, not a file or generic label;
for example `feat(prompt-assemble): 增加测量证据选择约束`,
`fix(gateway-lifecycle): 释放启动器子进程`, or
`refactor(frontend-workspace): 拆分运行时间线组件`. Keep unrelated changes
separate. Pull requests should explain the behavior change, list validation
commands, note configuration or migration impact, and include screenshots for
visible UI changes. Update relevant OpenSpec files when the behavior contract
changes; pure internal refactors may use `skip_specs` only when requirements do
not change.

## Security & Configuration Tips

Copy `.env.example` to `.env`; never commit API keys or generated
session data. `.chartagent/`, frontend build output, `*.tsbuildinfo`, Python
caches, and generated evaluation artifacts stay local. Keep Gateway services
bound to loopback, use opaque attachment and run IDs, and avoid exposing local
paths, environment values, image bytes, or unrestricted tool payloads in logs,
traces, frontend state, or committed fixtures. Preserve bounded/redacted
evaluation detail resources when exposing tool results to the UI.
