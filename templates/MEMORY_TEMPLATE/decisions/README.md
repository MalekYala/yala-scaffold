# `memory/decisions/` — architectural decision records

**ADRs** (architectural decision records) live here. Each file captures a
single decision: what was chosen, what was rejected, and why.

## When to write a decision memory

Write one **whenever a non-obvious choice was made**. Examples:

- Picking between two libraries, frameworks, or approaches
- Choosing a data model, schema, or file layout
- Deciding NOT to do something (scope cut)
- Naming conventions that differ from the obvious default
- Trade-offs where the "better" answer is contextual

Do NOT write an ADR for:

- Obvious defaults (we use Python 3.12 because it's the scaffold's default)
- Style preferences with no trade-off (just pick one)
- Implementation details that can be changed later without impact

## Suggested body structure

```markdown
## Context
What situation called for a decision?

## Options considered
1. Option A — pros / cons
2. Option B — pros / cons
3. Option C — pros / cons

## Decision
Which option was chosen, and by whom.

## Consequences
What changes as a result. Include both the good (why this option) and the
bad (what we gave up).

## Revisit if
Under what conditions should this decision be reopened?
```

## Example files

- `0000-example-adr.md` — reference example showing the frontmatter +
  body structure
