# Pull Request

## Summary
<!-- Describe what this PR does and why -->

## Merge strategy reminder
<!-- IMPORTANT: choose the correct merge button based on the target branch -->

| Target branch | Required strategy | Why |
|---|---|---|
| `dev` | Squash merge ✅ | Keeps dev history clean |
| `main` | **Merge commit** ✅ | Preserves dev→main ancestry; squash breaks future merges |

> **If merging dev → main: you MUST use "Create a merge commit". Never squash or rebase.**

## Checklist
- [ ] Tests pass
- [ ] CHANGELOG / version bump handled (if applicable)
