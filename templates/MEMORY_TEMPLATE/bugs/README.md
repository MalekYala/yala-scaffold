# `memory/bugs/` — bugs + fixes

Post-mortem style entries for bugs encountered during development.
**Especially valuable** because bugs repeat across projects, and a
well-captured fix saves future agents from re-debugging the same class
of issue.

## When to write a bug memory

- Any bug that took more than 30 minutes to diagnose
- Any bug that would be hard to rediscover from the fix commit alone
- Any bug that reveals a misunderstanding about a library, API, or
  architectural assumption
- Any bug that will definitely recur in similar projects

Do NOT write a memory for:

- Trivial typos caught by the linter
- Bugs fixed during initial scaffolding before anything was running
- Bugs whose root cause is a single-line mistake with no broader lesson

## Suggested body structure

```markdown
## Symptom
What the user / log / test saw.

## Diagnosis
How we found the root cause. Include the detective work — which hypotheses
were wrong, what command revealed the truth.

## Root cause
The underlying bug, stated precisely.

## Fix
What was changed. Link the commit.

## How to detect / prevent recurrence
- Test that would have caught it
- Lint rule / type check that would have caught it
- Code review pattern to watch for
```

## Example

See `0000-example-bug.md`.

## Naming

`<4-digit-id>-<short-slug>.md`, e.g. `0007-race-in-worker-pull-batch.md`.
