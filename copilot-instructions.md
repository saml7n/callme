# Agent Operating Instructions (Story-Driven)

These instructions apply to any coding agent working in this repository.

## Project context

CallMe is an AI-powered phone receptionist. The architecture is documented in `docs/architecture.md`. Read it for system design context, tech stack decisions, and reference links.

**Tech stack (server):** Python 3.12+, FastAPI, asyncio, SQLAlchemy/SQLModel, Pydantic.
**Tech stack (web):** React, TypeScript, Vite, Tailwind, React Flow (`@xyflow/react`).
**External services:** Twilio (telephony), Deepgram (STT), ElevenLabs (TTS), OpenAI GPT-4o (LLM).

## Non-negotiables

1. **Story-gated work only**
   - Before making any code change, read the relevant story in:
     - `docs/stories.md`
   - You must identify the active story (e.g., "Story 6 — End-to-end voice pipeline").
   - You must confirm that all items under **"Blocked until answered"** for that story have been answered and recorded in `docs/stories.md`.
   - If any prerequisite answer is missing/ambiguous, **stop** and ask the user to provide it, then require the story doc to be updated before proceeding.
   - Do not skip ahead. Stories have an explicit dependency chain — respect it.

2. **One story at a time**
   - Do not begin a new story until the current story meets its acceptance criteria, passes all unit tests, passes QA verification, and is committed.

3. **Two-tier testing is mandatory**
   - Every story defines both **unit tests** and **QA verification**. Both must pass.
   - **Unit tests** (`pytest` for server, `vitest` for web): isolated, mocked dependencies, fast. Run these first.
   - **QA verification**: real runs of the system that prove the feature works end-to-end.
     - For **voice pipeline stories** (2, 3, 5, 6, 8, 12): QA involves real phone calls. Document the manual test script, expected outcome, and actual result.
     - For **web UI stories** (10, 11, 12): QA uses **Playwright** for automated browser testing. Write Playwright test scripts that exercise the steps listed in the story's QA section.
     - For **API stories** (9): QA uses `curl`, `httpx`, or Playwright to hit the running server.
   - If the story's QA section specifies Playwright, write the Playwright test and include it in the commit.
   - Run all tests before finalising the story.

4. **One commit per story**
   - Each story's implementation must be contained in a single commit.
   - Commit message format:
     - `story-<N>: <short title>`
     - Example: `story-6: end-to-end voice pipeline`
   - The commit must include:
     - Code changes.
     - Unit tests for the story.
     - QA test scripts (Playwright or manual test doc) for the story.
     - Story doc updates that mark the story as done (see below).

5. **Update the story doc as part of completion**
   - When a story is complete, update `docs/stories.md`:
     - Check off acceptance criteria (`- [x]`).
     - Record what tests were run and the result (pass/fail, test count).
     - Record QA verification outcome (for manual QA: what happened on the call; for Playwright: test pass/fail).
     - Record the commit hash.

## Working method (repeat for every story)

### A) Pre-flight (no code yet)
- Read the story section in `docs/stories.md`.
- Read relevant sections of `docs/architecture.md` for design context.
- Restate the acceptance criteria as a checklist.
- Verify all "Blocked until answered" items have recorded answers.
- If any are blank or say "_unanswered_": **stop and ask the user**. Do not guess. Do not start implementation.

### B) Implement (minimal surface area)
- Make the smallest set of changes required to satisfy acceptance criteria.
- Follow the project structure laid out in `docs/architecture.md` section 6.
- Keep changes localised; avoid refactors unless required by the story.
- Use clear names and straightforward control flow.

### C) Unit test
- Write and run unit tests as specified in the story's "Unit tests" section.
- All tests must pass: `pytest server/tests/` for server, `npm test` (vitest) for web.

### D) QA verify
- Execute the QA verification steps listed in the story.
- For Playwright QA: write a test file under `web/tests/e2e/` and run it.
- **Note:** Vite must be started with `--host 0.0.0.0` for Playwright to reach it (default IPv6-only binding is not reachable). Use `npx vite --host 0.0.0.0` or set `server.host: true` in `vite.config.ts`.
- For phone call QA: document the test (what you said, what the AI said, timestamps) in the commit or story doc.
- For API QA: run the documented `curl`/`httpx` commands and record the results.

### E) Commit
- Ensure working tree is clean except for intended changes.
- Create exactly one commit for the story.
- **Always commit at the end of every completed story** — do not leave uncommitted work.
- Commit message: `story-<N>: <short title>` (e.g. `story-7: workflow engine with conversation nodes`).
- The commit must include all code, tests, story doc updates, and any config changes.
- After committing, verify the commit with `git log --oneline -1`.

### F) Close out
- Update `docs/stories.md` with completion evidence, test results, and commit hash.
- **Always print a "How to use the system" summary** after each completed story. This should include:
  1. How to start the server and web app.
  2. What env vars are required.
  3. How to log in (if auth is enabled).
  4. What features are now available and how to access them.
  5. Any new URLs, credentials, or configuration the user needs to know about.
  - This is mandatory — the user should never have to ask "how do I run this?".

## Coding style

### Python (server)
- **Package manager: `uv`**. Use `uv init`, `uv add`, `uv run`, `uv pip` — never raw `pip install`.
- **Minimalistic, readable, neat**: prefer simple functions and explicit logic.
- Use type hints everywhere. Pydantic models for all data boundaries.
- `async def` for anything that touches I/O (WebSockets, HTTP calls, DB).
- Avoid clever abstractions, metaprogramming, and premature generalisation.
- Keep modules small; keep functions focused.
- Use consistent naming (`snake_case`); avoid one-letter variables.
- Prefer standard library solutions where reasonable.
- Prefer deterministic behavior (idempotent updates, stable schemas).
- Handle errors explicitly — no bare `except:`, no silent swallowing.

### TypeScript / React (web)
- Functional components with hooks. No class components.
- Props typed with interfaces or type aliases, not `any`.
- Tailwind for styling; no CSS-in-JS.
- React Flow nodes are custom React components — keep them small and focused.
- Use `fetch` or a thin wrapper for API calls; no heavy client libraries unless justified.

## Key reference docs

When you need to look up an API or library, check the reference table in `docs/architecture.md` section 7 first. Key ones:

- **Twilio Media Streams:** bidirectional WebSocket protocol, message formats, `<Connect><Stream>` TwiML.
- **Deepgram streaming:** WebSocket API, endpointing, `speech_final` vs `is_final`.
- **ElevenLabs TTS:** `ulaw_8000` output format, latency optimisation, streaming endpoint.
- **OpenAI:** chat completions, tool/function calling, streaming, structured outputs.
- **React Flow:** custom nodes, custom edges, serialisation.
- **FastAPI:** WebSocket endpoints, dependency injection, Pydantic integration.

## Safety defaults

- Never commit API keys, tokens, or secrets. Use environment variables via `app/config.py`.
- Validate the Twilio `X-Twilio-Signature` header on incoming webhooks.
- Sanitise expression-based edge conditions in the workflow engine (no arbitrary code execution).
- Phone numbers in call logs must be masked in the UI (Story 11).
