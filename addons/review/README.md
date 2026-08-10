# Code review add-on — `<name>`

AI code review on merge requests, using
[OpenCodeReview](https://github.com/alibaba/open-code-review) (`ocr`).

It reads the diff, sends changed files to an LLM, and produces structured
findings with file and line numbers. This add-on wires that into your pipeline
and adds a gate, so the result is a pass/fail signal rather than a wall of
prose nobody reads.

## What you need

- An **OpenAI- or Anthropic-compatible LLM endpoint** and a token for it. Any
  of: OpenAI, Anthropic, OpenRouter, a local vLLM/Ollama/llama.cpp server —
  anything speaking the same protocol.
- A GitLab project with merge requests. The pipeline job triggers on MR events.

Nothing is installed on your machine: the CI job installs `ocr` in a `node:20`
image, and `make code-review` runs it in a container.

## Setup

**1. Add the job to your pipeline.** In `.gitlab-ci.yml`, add `review` to
`stages:` and include the fragment:

```yaml
stages:
  - lint
  - review        # ← add
  - secret-scan
  - security
  - build
  - test

include:
  - local: 'review/ci.gitlab-ci.yml'
```

**2. Set the CI/CD variables** (Settings → CI/CD → Variables):

| Variable | Required | Notes |
|---|---|---|
| `OCR_LLM_URL` | yes | e.g. `https://api.openai.com/v1/chat/completions` |
| `OCR_LLM_AUTH_TOKEN` | yes | **mark as Masked** |
| `OCR_LLM_MODEL` | yes | e.g. `gpt-4o`. No default — unset fails the job immediately |
| `OCR_FAIL_ON` | no | `critical` (default), `high`, `medium`, `low`, `none` |
| `OCR_USE_ANTHROPIC` | no | `true` for Anthropic-native APIs |
| `OCR_LANGUAGE` | no | review output language |
| `OCR_POST_COMMENTS` | no | `true` to post inline discussions on the MR |
| `GITLAB_API_TOKEN` | no | `api` scope; only for posting comments. Falls back to `CI_JOB_TOKEN` |

If you run the Vault add-on, put the token there instead and pull it —
`OCR_LLM_AUTH_TOKEN  shared/openai  api_key` in `vault/secret-map.tsv`.

**3. Open a merge request.** The job runs, prints every finding grouped by
severity, uploads `.ocr/result.json` as an artifact, and fails only if
something is at or above `OCR_FAIL_ON`.

## Local use

```bash
make code-review                      # review uncommitted changes
make code-review FROM=main            # review this branch against main
make code-review FAIL_ON=none         # report everything, never fail
```

Runs in a container, so it needs no host Node. It reads `OCR_LLM_*` from your
`.env`.

## Inline MR comments (opt-in)

Set `OCR_POST_COMMENTS=true`. The job then fetches upstream's GitLab publisher
— several hundred lines of API handling for pagination, rate limits, retries
and sticky summaries — and posts each finding as an inline discussion on the
line it refers to.

That file is **not vendored into this repo.** `review/fetch_poster.sh` fetches
it at a pinned release tag and verifies a recorded SHA-256 before it runs.
Three reasons:

- It is Apache-2.0, and this project is MIT. Fetching keeps the boundary
  explicit, with a `NOTICE` written next to it recording source, version and
  licence.
- A vendored copy goes stale silently. A pinned fetch is a version number you
  can see and bump.
- Code that runs in CI with an API token in scope should never come from an
  unverified download. An unrecorded version fails closed rather than
  fetching something arbitrary.

To bump it, change `VERSION` in `review/fetch_poster.sh`, record the new
checksum (`curl -fsSL <url> | sha256sum`), and commit both together. A version
bump with a stale checksum fails — that is the point.

## The gate

`review/gate.py` (ours, no dependencies) turns the JSON into a readable summary
and decides whether the job fails.

It defaults to failing only on `critical`. An AI reviewer produces a lot of
reasonable low-severity opinion, and a job that goes red on all of it gets
disabled within a week — after which the critical findings stop being read
too. Failing on `critical` only means red always means something, while
everything else is still printed and still in the artifact.

Raise it to `high` once you have seen what your model actually produces on
your codebase. That is a decision to make with evidence, not upfront.

One deliberate detail: an **unrecognised severity ranks as high**, not low. If
upstream introduces a new severity name, the gate gets noisier rather than
silently letting findings through.

## Cost and privacy

Every MR sends your changed files to whatever endpoint `OCR_LLM_URL` points
at. Before enabling this on anything sensitive, be sure you know where that is
and what the provider retains. A local model endpoint keeps the code on your
own hardware.

Reviews cost tokens per MR, scaling with diff size. The job runs on merge
request events only — not every push — for exactly that reason.

## Limitations

It is an LLM reading a diff. It finds real bugs and it invents confident
nonsense, in the same output, with the same tone. Treat findings as a
reviewer's suggestions, not as test results: `make test`, `make qa` and
`make audit` are the checks that actually know whether the code works.

It also sees only the diff and the files it chooses to pull in — not your
runtime behaviour, not your data, and not the thing you were actually worried
about unless it happens to be on a changed line.
