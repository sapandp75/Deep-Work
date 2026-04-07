# Design & Validate

---
name: implement
description: Design-first workflow. Clarify requirements, propose architecture, attack the plan for failures, revise, then present for approval. Use before any non-trivial feature build.
---

You are in IMPLEMENT MODE. Do not write any code.

## Phase 1 - Clarify
Ask every clarifying question about the feature. Requirements, constraints, edge cases, dependencies. Do not assume. Ask.

## Phase 2 - Propose
Propose the architecture: files to create or modify, modules, data flow, API contracts, state management. Be specific.

## Phase 3 - Attack
Attack your own plan:
- What breaks under load, bad input, or race conditions?
- What assumptions are fragile?
- What edge cases did you miss?
- What is the simplest thing that could go wrong?
- Where does this design couple too tightly or leak abstractions?

List every failure mode you find.

## Phase 4 - Revise
Revise the plan to address every issue you found. Show what changed and why.

## Phase 5 - Present
Present the final design cleanly. Wait for explicit approval before writing any code.
