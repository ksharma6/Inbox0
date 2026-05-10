# Changelog

All notable changes to Inbox0 are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.2.1] — 2026-05-09

### Fixed
- Preserved Gmail `threadId` when creating, saving, and sending draft replies so workflow-generated responses stay attached to the original Gmail conversation.

### Maintenance
- Added focused Gmail writer, workflow handoff, and tool schema tests for threaded draft/reply behavior.

---

## [0.2.0] — 2026-05-08

### Breaking Changed
- Workflow state is now persisted and resumed by `workflow_run_id` instead of Slack `user_id`, so `/resume_workflow` callers must provide the `workflow_run_id` returned by `/start_workflow`.
- Slack draft approval buttons now carry `workflow_run_id` so approval actions resume the specific workflow run they belong to rather than the latest saved run for a user.

### Fixed
- Prevented concurrent workflow runs for the same Slack user from overwriting each other in persisted state.

### Maintenance
- Clarified workflow state naming by using `workflow_run_id` for app workflow runs, keeping `thread_id` reserved for Gmail conversation threads.
- Expanded focused test coverage around workflow state persistence, Slack resume routing, and workflow-run ID validation.

---

## [0.1.1] — 2026-04-25

### Added
- Fail-fast Pydantic validation at external boundaries: Flask workflow requests, Slack action payloads, Gmail message parsing, and `AgentSchema` API-key configuration ([#71](https://github.com/ksharma6/Inbox0/pull/71))
- Retry logic for transient OpenAI/OpenRouter-compatible LLM failures and Gmail read API failures using exponential backoff.
- Focused tests for schema validation, environment-variable fallback behavior, Gmail malformed-response handling, and retry behavior.

### Changed
- Aligned environment loading and workflow construction with `AgentSchema`, including support for either `OPENROUTER_API_KEY` or `OPENAI_API_KEY` ([#71](https://github.com/ksharma6/Inbox0/pull/71))
- Updated `src/workflows/factory.py` to construct the workflow through `Agent`/`AgentSchema` instead of a raw `OpenRouter` client ([#71](https://github.com/ksharma6/Inbox0/pull/71))

### Maintenance
- Updated CI to use `actions/checkout@v5` and `codecov/codecov-action@v5` for both coverage and test-result uploads ([#71](https://github.com/ksharma6/Inbox0/pull/71))
- Updated `pip-audit` CI behavior to ignore the currently unactionable `pip` CVE while preserving audit enforcement for other vulnerabilities ([#71](https://github.com/ksharma6/Inbox0/pull/71))

### Dependencies
- Bumped `langsmith` 0.7.30 → 0.7.36 ([#71](https://github.com/ksharma6/Inbox0/pull/71))
- Added `tenacity` as a direct dependency for retry handling.

---

## [0.1.0] — 2026-04-10

### Added
- LangSmith tracing support and `load_env` required variable validation ([#57](https://github.com/ksharma6/Inbox0/pull/57))
- Fixture and email dataset generation for testing ([#49](https://github.com/ksharma6/Inbox0/pull/49))
- GitHub CI pipeline ([#38](https://github.com/ksharma6/Inbox0/pull/38))
- Timing and token counting logger ([#37](https://github.com/ksharma6/Inbox0/pull/37))
- OpenRouter implementation and refactor — any OpenAI SDK-compatible provider supported ([#16](https://github.com/ksharma6/Inbox0/pull/16))
- Logging module ([#14](https://github.com/ksharma6/Inbox0/pull/14))
- End-to-end email triage and drafting workflow ([#6](https://github.com/ksharma6/Inbox0/pull/6))
- Gmail Reader refactor ([#5](https://github.com/ksharma6/Inbox0/pull/5))
- Gmail Reader functionality integrated into agent ([#4](https://github.com/ksharma6/Inbox0/pull/4))
- OpenAI agent base class for reading and writing Gmail ([#3](https://github.com/ksharma6/Inbox0/pull/3))
- Agent can send emails ([#2](https://github.com/ksharma6/Inbox0/pull/2))
- GmailWriter class ([#1](https://github.com/ksharma6/Inbox0/pull/1))

### Documentation
- Updated README badges and links for Inbox0 rename ([#55](https://github.com/ksharma6/Inbox0/pull/55))
- Architecture Decision Record: classification dataset ([#48](https://github.com/ksharma6/Inbox0/pull/48))
- Architecture Decision Record: email cache and parallelization strategy ([#35](https://github.com/ksharma6/Inbox0/pull/35))
- Updated README banner ([#32](https://github.com/ksharma6/Inbox0/pull/32))
- Added Contributor Covenant Code of Conduct ([#22](https://github.com/ksharma6/Inbox0/pull/22))
- Open-source hygiene: issue templates, contributing guide, and repo metadata ([#23](https://github.com/ksharma6/Inbox0/pull/23))

### Maintenance
- Added Codecov test results upload and ignored generated report files ([#54](https://github.com/ksharma6/Inbox0/pull/54))
- Fixed Codecov unknown status — upgraded action to v5 and added `codecov.yml` ([#53](https://github.com/ksharma6/Inbox0/pull/53))
- GitHub and CI maintenance ([#52](https://github.com/ksharma6/Inbox0/pull/52))
- Updated pre-commit configuration and CI workflow to target Python 3.11 ([#40](https://github.com/ksharma6/Inbox0/pull/40))
- Removed stale `Inbox0` dependency from `requirements.txt` ([#39](https://github.com/ksharma6/Inbox0/pull/39))

### Dependencies
- Bumped `openai` 2.17.0 → 2.30.0 ([#46](https://github.com/ksharma6/Inbox0/pull/46))
- Bumped `pydantic-core` 2.41.5 → 2.45.0 ([#45](https://github.com/ksharma6/Inbox0/pull/45))
- Bumped `slack-bolt` 1.27.0 → 1.28.0 ([#44](https://github.com/ksharma6/Inbox0/pull/44))
- Bumped `langchain` 1.2.9 → 1.2.15 ([#43](https://github.com/ksharma6/Inbox0/pull/43))
- Bumped `tiktoken` 0.9.0 → 0.12.0 ([#42](https://github.com/ksharma6/Inbox0/pull/42))
- Bumped `google-api-python-client` 2.189.0 → 2.193.0 ([#28](https://github.com/ksharma6/Inbox0/pull/28))
- Bumped `google-auth-oauthlib` 1.2.4 → 1.3.1 ([#27](https://github.com/ksharma6/Inbox0/pull/27))
- Bumped `openrouter` 0.6.0 → 0.8.1 ([#26](https://github.com/ksharma6/Inbox0/pull/26))
- Bumped `werkzeug` 3.1.5 → 3.1.8 ([#25](https://github.com/ksharma6/Inbox0/pull/25))
- Bumped `uuid-utils` 0.14.0 → 0.14.1 ([#24](https://github.com/ksharma6/Inbox0/pull/24))
- Bumped `flask` 3.1.2 → 3.1.3 ([#21](https://github.com/ksharma6/Inbox0/pull/21))
- Bumped `pygments` 2.19.2 → 2.20.0 ([#20](https://github.com/ksharma6/Inbox0/pull/20))

---

[Unreleased]: https://github.com/ksharma6/Inbox0/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ksharma6/Inbox0/releases/tag/v0.1.0
