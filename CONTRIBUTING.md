# Contributing and branch policy

## Branches

- **`main` is the released history.** It is protected (the rule below) and
  moves only by fast-forward: a commit reaches `main` after it has been
  pushed to a working branch, its CI check has passed there, and the
  fast-forward push is made deliberately.
- **Development happens on a working branch.** This project's is
  `claude/geo-ecommerce-evaluation-system-qzv3qn`. CI runs on every push
  to every branch (`.github/workflows/okf-ci.yml`, job `test-and-lint`:
  the suite, the strict lint of the example bundle, the dry-run
  evaluation, and a publish smoke test), so a branch head always carries
  the check that `main` requires.
- **History stays linear.** No merge commits, no force pushes to `main`,
  and nothing already on `main` is ever rewritten. A mistake on `main` is
  corrected by a new commit.
- The verification loop in `CLAUDE.md` runs before every commit
  regardless of branch; the protection rule is the backstop, not the
  gate.

## The protection rule for `main`

Apply once, in the repository's settings on GitHub. Classic rule:
Settings → Branches → Add branch protection rule, branch name pattern
`main`.

| Setting | Value | Why |
| --- | --- | --- |
| Require a pull request before merging | off | This project moves `main` by fast-forward on the maintainer's word. Turning this on moves the workflow to pull requests, which is a separate decision, and can be made later without touching anything else here. |
| Require status checks to pass before merging | on, with the check `test-and-lint` selected and "Require branches to be up to date before merging" on | A commit reaches `main` only after the suite, the strict lint, the dry-run evaluation and the publish smoke test passed on that exact commit. |
| Require linear history | on | Fast-forward only. |
| Do not allow bypassing the above settings | on | Without it an administrator's push skips the check, and the rule protects nothing. |
| Allow force pushes | off | Nothing on `main` is rewritten. |
| Allow deletions | off | |
| Restrict who can push to matching branches | off | It needs an explicit allow-list that includes the identity sessions push with; set wrong, it locks `main` for everyone. The rules above already stop what matters. |
| Require signed commits | off | Commits here are not GPG-signed. The sigstore signatures in this project sign published bundles and statements, not git history. |
| Lock branch | off | |

The same rule as a ruleset (Settings → Rules → Rulesets → New branch
ruleset; target `main`; enforcement Active; bypass list empty): restrict
deletions, require linear history, require status checks to pass
(`test-and-lint`, up to date), block force pushes.

## What changes for the fast-forward push

Nothing in the command: `git push origin <sha>:refs/heads/main`. One
precondition: the check on `<sha>` must already be green. GitHub refuses
a push whose head commit has no passing required check, so wait for the
branch's CI to finish, then push. If CI is red on the branch, fix it on
the branch first; there is no route around the check, by design.

## Verifying the rule

- The branches endpoint reports `protected: true` for `main` (the
  session's GitHub `list_branches` tool shows the same field).
- A force push to `main` is refused.
- A push to `main` of a commit whose check has not run is refused with
  a message naming the required check.
