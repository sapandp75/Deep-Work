# Build, Test, Prove

---
name: build
description: Build the feature, write tests, run everything, fix failures, self-review, prove it works. Use after design approval or for any implementation task.
---

You are in BUILD MODE. Execute the full loop with no shortcuts.

## Step 1 - Build
Implement the feature. Follow existing codebase patterns for naming, structure, and style. If patterns exist, match them exactly.

## Step 2 - Test
Write tests covering:
- Happy path (it works as intended)
- Edge cases (empty inputs, boundaries, nulls, large data)
- Error states (bad input, network failures, missing dependencies)

## Step 3 - Run
Run the full verification stack:
- Tests: run the test suite
- Types: run the type checker if applicable
- Lint: run the linter if applicable
- Build: verify it compiles or bundles cleanly

## Step 4 - Fix
If anything fails, fix it. Rerun until everything passes. Do not move on with failures.

## Step 5 - Self-Review
Review your own code as a staff engineer. Check for:
- Missed error handling
- Naming inconsistencies
- Unnecessary complexity
- Security issues (injection, leaks, auth gaps)
- Missing cleanup or teardown

Fix anything you find. Rerun tests after fixes.

## Step 6 - Prove
Show:
- All tests passing
- Type checker clean
- Linter clean
- A summary of what was built and any decisions made
