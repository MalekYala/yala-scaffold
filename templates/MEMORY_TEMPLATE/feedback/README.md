# `memory/feedback/` — user feedback + reports

External input about the project: user reports, complaints, feature
requests, reviewer comments. Captured here so the orchestration bot has
context on what users are asking for when planning the next iteration.

## When to write a feedback memory

- A user reports a problem that isn't an outright bug (UX issues, unclear
  docs, unexpected behavior)
- A reviewer or stakeholder requests a change
- A post-launch survey surfaces patterns
- A customer asks for a feature that's not currently planned

Do NOT write one for:

- Bugs (those go in `bugs/`)
- Internal team opinions (those are decisions — use `decisions/`)

## Suggested body structure

```markdown
## Source
Who said it, when, via what channel.

## What they said
Quote if possible, paraphrase otherwise.

## Interpretation
What the underlying need is (users often describe solutions, not problems).

## Action taken / planned
What was done about it, or what's blocking action.
```

## Privacy

If the feedback is from a named user or customer, **anonymize before
committing**. Use `<customer-A>`, `<reviewer-B>`, etc. Raw names and
emails do not belong in a public-safe repo.
