# SecondPick — Agent Guide

SecondPick is a self-hosted second-hand listing monitor and optional AI research workspace, currently focused on Xianyu / Goofish.

## Working on the project

- Inspect the Git root, remotes, branch, and working tree before repository operations. Preserve existing changes and user data.
- Read existing implementations before changing them. Keep changes focused, distinguish implemented features from plans, and report validation limits.
- `src/shopping_agent/` contains the Python backend; `web/src/` contains the React frontend. Keep frontend source and distributed assets in `src/shopping_agent/web/static/` consistent.
- `tests/` and `web/e2e/` contain tests. `skills/` contains runtime research instructions; preserve them along with LICENSE and THIRD_PARTY_NOTICES.md.
- Follow [development instructions](docs/DEVELOPMENT.md) for dependencies, tests and builds. Use isolated data and mocked services; real collection and paid model calls are not default installation tests.

## Operation and evidence boundaries

- Follow the [README](README.md), [user guide](docs/user-guide.md), and [Agent templates](docs/agent-prompts.md) when deploying or operating an existing installation.
- Basic collection needs no Codex CLI. Internal text research uses Codex CLI and authentication; project automatic research requires separate authorization and is off by default. Vision is optional. External Agent access does not configure or authorize internal research.
- Do not overwrite runtime configuration or data, start duplicate instances against one database, or silently expand collection/research scope. Users perform account login themselves.
- Never commit or publish credentials, cookies, browser profiles, local configuration, databases, logs, personal information, or real account screenshots. See [privacy](docs/PRIVACY.md) and [account risks](docs/account-risk.md).
- Keep saved seller claims, AI observations and independent verification distinct. Do not present placeholder platform adapters or synthetic demos as validated integrations or real purchase evidence.

Report bugs and propose changes through issues or pull requests. Architecture is described in [docs/architecture.md](docs/architecture.md); measured checks and unverified areas are recorded in [docs/VALIDATION.md](docs/VALIDATION.md).
