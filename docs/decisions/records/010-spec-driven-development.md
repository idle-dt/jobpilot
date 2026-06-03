# ADR-010: Spec-driven development workflow

**Status:** accepted
**Date:** 2026-05-07
**Tags:** process, workflow

## Context

JobPilot is developed largely with AI coding assistance. Features touch multiple
layers (routes → services → repositories, classifier pipeline, Gmail/scraper
pipelines), so changes implemented straight from a chat prompt tend to drift from
intent, skip edge cases, and ship without a defined way to verify they actually
work. We needed a lightweight but enforced process that captures *why* and *what*
before code, and defines concrete acceptance checks.

## Decision

Adopt a **spec-driven workflow** centered on `docs/specs/`.

- Each feature/bugfix starts as a `docs/specs/SPEC_<name>.md` copied from
  `SPEC_TEMPLATE.md`, with sections: **Problem** (must explain *why*), a testable
  **Requirements** table, focused **Implementation Steps**, **Verification**, and an
  **Implementation Report** filled in on completion.
- **Verification > Logic Verification** is the most important section: each item is a
  concrete "input X produces output Y" scenario, not a vague "verify it works".
- Active specs are tracked in `docs/TODO.md` under "In Progress".
- The `CLAUDE.md` Implementation Workflow (Plan → Implement → Verify → Report) and
  the `/ship` flow operationalize the process: tests, lint, logic verification, and a
  code-review audit run before merge.

## Alternatives Considered

| Alternative | Why Rejected |
|-------------|-------------|
| Ad-hoc prompting, no specs | Intent and acceptance criteria get lost; regressions and scope creep are common. |
| GitHub Issues only | Less structured than the template's Problem/Requirements/Verification sections; not co-located with the repo workflow. |
| Heavy formal design docs / RFCs | Too much ceremony for a solo local project; the lightweight template hits the needed rigor. |

## Consequences

### Positive
- Forces motivation and concrete acceptance checks before code is written.
- Specs double as a feature changelog and historical record.
- `/ship` ties implementation to verification and review gates.

### Negative / Tradeoffs
- Up-front spec-writing overhead for every change, including small ones.
- Specs can drift from code if not maintained (mitigated by the Implementation Report + TODO.md tracking).

### Risks
- Skipping the Logic Verification rigor undermines the whole process's value.

## Related

- ADRs: this ADR system itself extends the documentation workflow.
- Specs: `docs/specs/SPEC_TEMPLATE.md`
- Docs: `CLAUDE.md` (Implementation Workflow, Writing Specs, /ship Command)
