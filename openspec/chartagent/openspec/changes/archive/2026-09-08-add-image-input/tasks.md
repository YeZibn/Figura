# Tasks: add-image-input

## 1. Multimodal builder

- [x] 1.1 Create `src/chartagent/multimodal.py` with `build_user_content(text, image_paths)`: text part first, then one `image_url` base64 data-URL part per path; MIME via allowlist (png/jpeg/gif/webp) with extension fallback; `FileNotFoundError` for missing paths, `ValueError` for non-image extensions.
- [x] 1.2 Export `build_user_content` from `chartagent/__init__.py`.
- [x] 1.3 Add `tests/test_multimodal.py`: PNG round-trip (decode payload == file bytes), jpeg MIME, missing file error, non-image error, multiple paths keep order.

## 2. Agent pass-through

- [x] 2.1 Widen `Agent.run` to accept `str | list[dict]` and append it to history unchanged (no content inspection).
- [x] 2.2 Add a test in `tests/test_agent.py`: multimodal content list appears verbatim in the first user history entry and in the fake client's recorded request.

## 3. CLI @path wiring

- [x] 3.1 In `run_agent_repl`, parse `@(\S+)` tokens: strip them from the text, build content via `build_user_content`; zero tokens → send the original string unchanged.
- [x] 3.2 Catch file errors per turn, print `agent> [error] ...`, keep the session alive.
- [x] 3.3 Add tests in `tests/test_cli_agent.py`: single `@path` attaches an image part, plain text path unchanged, nonexistent `@path` prints error and does not call the agent.

## 4. Verification

- [x] 4.1 Full regression suite green in the conda env `agent` (`conda run -n agent python -m pytest`; install the project editable there if not yet done).
- [x] 4.2 Manual smoke against the real endpoint in env `agent`: one `--agent` turn with `@` a small chart PNG, confirm the model describes the image (proves data URLs are accepted).
