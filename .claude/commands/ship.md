Ship the current work: create a feature branch, run security/quality audit, commit, push, review loop, create PR, and clean up.

Steps:
1. Run tests (`scripts/test_summary.sh`) and lint (`poetry run ruff check`) on modified Python files — stop if failures
2. Review the full `git diff` for security issues (SQL injection, XSS, secrets, unsafe DOM, input validation)
3. Create a new branch from the current branch named `feat/<descriptive-slug>` based on the changes
4. Stage all modified files (not untracked unless relevant) and commit with a conventional commit message (single line, no AI/Claude mention)
5. Ask the user to confirm the commit message before committing
6. Push with `-u origin`
7. **Review loop** — repeat until clean:
   a. Spawn the `diff-auditor` agent to audit the full diff — paste `git diff master...HEAD` into its prompt rather than letting it re-read the changed files
   b. Print the review findings as a table (Severity | Issue | File)
   c. Fix all HIGH + MEDIUM issues, and LOW issues that are easy/fast fixes
   d. Run `scripts/test_summary.sh` + lint after fixes — stop if failures
   e. Commit review fixes and push
   f. Re-review. If new issues found, repeat from (c). If clean, exit loop.
8. Report a summary (branch name, commit count, test results, review fixes applied) and ask: **"Create a PR?"**
9. When the user confirms, create the PR with `gh pr create` targeting `master`
10. **Spec cleanup** — if a `docs/specs/SPEC_*.md` file was implemented:
    a. Ask the user to confirm deletion of the spec file
    b. If confirmed: delete the spec file, remove the entry from `docs/TODO.md` "In Progress", commit with `docs:` prefix, and push to the same branch — so the cleanup is part of the PR, not a separate commit on master after merge
11. **ADR check** — if the shipped work introduced a new technology, replaced a component, or made a significant architectural choice:
    a. Ask: "Does this change warrant an Architecture Decision Record?"
    b. If yes: create the ADR file in `docs/decisions/records/` following `docs/decisions/TEMPLATE.md`, update `docs/decisions/README.md`, commit with a `docs:` prefix, and push to the same branch
12. Print the final PR URL

If on a feature branch already (not master), skip branch creation and just commit + push.
