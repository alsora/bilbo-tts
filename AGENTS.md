# Engineering Guidelines

These guidelines apply to every change in this repository.

References:
 - [Current state of the project](HANDOFF.md)
 - [How to run](README.md)
 - [Project design](design.md)
 - [Implementation milestones](implementation.md)

## Coding practice

- Keep implementations small, sharp, cohesive, and easy to understand.
- Look beyond the first workable idea and choose the simplest design that fully solves the problem.
- Prefer explicit data flow and narrow interfaces over clever abstractions or unnecessary indirection.
- Do not introduce fragile special-case patches, speculative abstractions, dead code, unused code, or accidental complexity.
- Remove obsolete paths when replacing behavior instead of leaving compatibility code without a demonstrated need.
- Keep functions and modules focused on one responsibility.
- Validate inputs and invariants at boundaries, and report failures with actionable errors.
- Preserve the deterministic, idempotent, and auditable behavior defined in [`design.md`](design.md).
- Add comments when they explain intent, constraints, trade-offs, or non-obvious behavior.
- Do not add comments that merely restate what the code already says.

## Source documents

- Treat configured book source documents as user-owned, read-only inputs.
- Never edit source documents, even to fix extraction, normalization, pronunciation, or synthesis problems.
- Report source-level problems to the user and record unresolved items in the `TODO` section of [`HANDOFF.md`](HANDOFF.md).
- Wait for the user to make source changes, then refresh derived artifacts through the normal pipeline.

## Testing

- Write extensive unit tests for domain logic, edge cases, failure modes, and boundary conditions.
- Maintain infrastructure for integration tests that exercise complete pipeline stages against small deterministic fixtures.
- Add opt-in hardware tests for MLX/MPS model integrations instead of requiring model downloads in ordinary test runs.
- Add a regression test whenever fixing a bug, and make the test fail against the previous behavior.
- Prefer realistic fakes at external boundaries over mocks of internal implementation details.
- Keep tests deterministic, isolated, readable, and fast enough for their intended verification level.
- Run the relevant focused tests while developing and `pixi run check` before considering a change complete.
- Follow the milestone-specific verification gates in [`implementation.md`](implementation.md).

## Documentation

- Keep documentation synchronized with behavior and configuration in the same change.
- Write documentation with one sentence per line to make diffs clear and reviews precise.
- Keep architectural decisions and stable policies in [`design.md`](design.md).
- Keep delivery order, verification stages, and checkpoint criteria in [`implementation.md`](implementation.md).
- Link to the owning document instead of copying information that could become stale.
- Document user-visible commands, configuration, failure recovery, and non-obvious operational constraints.

## Session handoff

- Update [`HANDOFF.md`](HANDOFF.md) at the end of every working session and at every milestone or checkpoint boundary.
- Treat `HANDOFF.md` as the concise operational state for the next agent, not as an architecture or progress-history document.
- Record the active branch, relevant commits, completed work, verification actually run, blockers, manual checks, and the next concrete action.
- Replace stale handoff information instead of appending a chronological diary.
- Link to `design.md` and `implementation.md` for durable decisions rather than duplicating them.
- Do not describe uncommitted work as complete, and identify any intentional working-tree changes explicitly.
- Include the handoff in the final milestone push when milestone execution authorizes commits and pushing.

## Dependencies and generated artifacts

- Manage Python packages, native tools, and commands through Pixi rather than system installations.
- Commit dependency manifests and lock files, but never commit `.pixi/`, model caches, generated workspaces, or model weights.
- Add a dependency only when it materially simplifies a verified requirement and cannot be implemented more clearly with existing tools.

## Commits

- Keep commits focused, reviewable, and internally consistent.
- Prefix commit subjects with `feat:`, `fix:`, `docs:`, `refactor:`, or `chore:`.
- Use imperative, specific subjects that explain the purpose of the change.
- Do not mix unrelated cleanup with feature or bug-fix commits.
- Commit after a coherent implementation slice is complete and its focused checks pass.
- Keep tests, documentation, configuration, and lock-file updates in the commit that requires them.
- Include a regression test in the same commit as the corresponding bug fix.
- Do not create checkpoint or work-in-progress commits merely to save partial state.

## Milestone branches and pushing

- A user request to proceed with a milestone in [`implementation.md`](implementation.md) explicitly authorizes the agent to create a branch, implement the milestone, create all necessary commits, and push that branch to `origin`.
- Create a dedicated branch named `milestone/cN-short-description` from the intended base branch.
- Never commit directly to or push directly to `main` as part of automatic milestone execution.
- Never force-push, rewrite published commits, merge the branch, or create a pull request unless the user explicitly asks.
- Before each commit, inspect the complete diff and status, remove unrelated changes, and check for secrets, model weights, caches, generated workspaces, and accidental large binaries.
- Before each commit, run the focused unit and integration tests relevant to that slice.
- Before pushing, run `pixi run check`, all automated verification required by the milestone, and any applicable local hardware smoke tests.
- Before pushing, update the owning documentation, review the full branch diff against its base, and require a clean working tree after the final commit.
- Do not push when a required automated check fails unless the user explicitly requests a work-in-progress push.
- If a milestone requires human verification such as listening review, push the automatically verified branch but report the checkpoint as awaiting human approval rather than complete.
- Push with a normal upstream-setting push and report the branch name, commits, verification results, and any remaining manual checkpoint.
