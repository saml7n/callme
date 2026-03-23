# Story Workflow

## Branch & Commit Convention
- Branch: `feat/DEV-XX-short-description` or `fix/DEV-XX-short-description`
- Commit: `feat: DEV-XX description` or `fix: DEV-XX description`
- One ticket = one branch = one PR
- Include Jira ticket key in PR title and all commit messages

## Story Lifecycle
1. Read story in `docs/stories.md` before any code change
2. Record decisions in story's "Recorded answers" section
3. Implement all acceptance criteria
4. Run full test suite (server + web + build)
5. Run QA verification against live server
6. Update `docs/stories.md`: check off ACs (`- [x]`), add `### Completion` section
7. Create PR targeting main

## PR Requirements
All PRs must include:
1. Summary of changes
2. Files changed with rationale
3. Testing notes with output
4. Risk assessment (Low/Medium/High)
5. Rollback considerations
6. Security impact statement
7. Assumptions made

## Coding Conventions
- Python 3.12+, type hints on all function signatures
- Google-style docstrings on all public functions
- structlog for logging (never print() or stdlib logging)
- Conventional commits: feat:, fix:, test:, refactor:, docs:
- No mutable default arguments
- Use `app.credentials.resolve_credentials()` — never read env vars directly for service keys

## Security Patterns (from Story 26)
- Timing-safe comparisons: `secrets.compare_digest()` for tokens/codes
- Auth dependencies: `require_auth` (any user), `require_admin` (admin only)
- WebSocket auth: validate `token` query param before `ws.accept()`
- Health endpoint: minimal response by default, detail requires auth
- Registration gating: `CALLME_INVITE_CODE` env var
- Password policy: 8+ chars, at least one letter and one digit
