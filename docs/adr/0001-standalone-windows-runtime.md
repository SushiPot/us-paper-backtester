# ADR 0001: Use a Project-Local Standalone Windows Runtime

## Status

Accepted

## Context

The project is expected to run when Codex is not open. Several Windows launchers previously depended on a Codex-bundled Python path, which made normal double-click usage and scheduled usage fragile.

## Decision

Use a project-local `.venv` as the runtime for Windows launchers. `setup_standalone.cmd` and `scripts/setup_standalone.ps1` create that environment from a standalone Windows Python installation and install `requirements.txt`. Shared launcher helpers resolve `.venv\Scripts\python.exe` before starting project entrypoints.

## Consequences

- The program can run from Windows CMD, PowerShell, double-click launchers, and scheduled tasks without Codex.
- First-time setup is explicit and repeatable.
- Codex's bundled runtime is not part of the normal execution path.
- Dependency installation happens inside the project environment, so launchers are slower only when `.venv` is missing or incomplete.
