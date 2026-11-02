# ADR-001: Modular monolith with ports and adapters (OOP)

## Status
Accepted (2026-11-01, DESIGN wave, overland-route-planner-mvp)

## Context
- One user plus household viewers, home LAN, Raspberry Pi 5. One implementer (nw-software-crafter). Paradigm confirmed: OOP.
- The top quality attributes are invariant correctness (HC-1..HC-5), offline testability (NFR-8), Pi performance and modifiability: routing provider and geocoder must swap by configuration; a CLI (Phase 2) must reuse the core.
- NFR-2 requires one `docker compose up -d`. NFR-5 requires idle RAM < 300 MB.

## Decision
One application container built as a modular monolith with dependency inversion (ports and adapters), with four layers: `domain` (pure), `application` (use cases + port Protocols), `adapters`, `bootstrap` (composition root). Modules: `catalog`, `routing`, `planning`, `export`, `platform`. Layer and module rules are enforced by import-linter (brief §11). A self-hosted routing engine, when used (Phase 3), is a separate optional compose service.

## Alternatives considered
- **Plain layered FastAPI app (routers -> services -> ORM models)**: the simplest option. Rejected: ORM and HTTP concerns leak into the optimizer and cache logic; the mock provider becomes a test-only patch rather than a configured adapter; there is no clean entry point for the CLI.
- **Script + static HTML (no persistent backend model)**: rejected. It cannot provide persistent projects, an incremental cache, run history or LAN multi-device access.
- **Microservices (import, routing, optimizer, export services)**: rejected. One implementer and one user give no team boundaries to follow, there is no independent-deployment need, and it adds RAM and operational cost on the Pi.
- **Separate worker container + broker (Celery/Redis) for plan runs**: rejected. One user means at most one job per project; an in-process job registry with a child process for the solver (ADR-008, ADR-012) is enough.

## Consequences
- Positive: the core is testable offline; adapters swap by config; the CLI reuses the application services; one image, one volume.
- Positive: architecture rules are machine-checked (import-linter + mypy + AST probe hook).
- Negative: a single process is a single point of failure. That is acceptable for a home tool; Docker restarts it (`restart: unless-stopped`).
- Negative: there is some boilerplate (Protocols, mappers) that a layered app would not have.
