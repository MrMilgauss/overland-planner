# Overland Route Planner

Source of truth for requirements: `REQUIREMENTS.md` (hard constraints HC-1..HC-5 are non-negotiable).

## Development Paradigm

This project follows the **object-oriented** paradigm. Use @nw-software-crafter for implementation.

## Mutation Testing Strategy

This project uses **per-feature** mutation testing. Runs after refactoring during each delivery, scoped to modified files. Kill rate gate: >= 80%.
