# Concepts

Longer explanations of the ideas the README summarises. Read this when you want
to know *why*, not just *how*.

## Shapes

A shape is a claim about what "finished" means.

An HTTP service is finished when it answers requests. A backtest is finished
when it has produced metrics with a plausible number of trades. A report is
finished when the PDF exists and isn't 0 bytes. These are genuinely different
success conditions, and a single template cannot express all of them without
becoming useless.

So the shape decides four things: the directory layout, the Dockerfile's
command, what `qa_check` verifies, and which KPIs are pre-declared. Everything
else — conventions, security posture, documentation, CI — is identical, because
those *should* be identical.

## Why one number (`metric.sh`)

A project with a single scalar score can be improved by a process that has no
understanding of it. That is the whole basis of the autoresearch loop: change
something, re-measure, keep or revert.

The rule is that `metric.sh` prints exactly one number as the last line of
stdout, and everything else goes to stderr. That constraint is what lets any
caller — a Makefile, a cron job, an agent — consume it without parsing.

The hard part is honesty. A metric that measures the wrong thing produces
confident movement in the wrong direction, which is worse than no metric. If
your project's real goal is "users find what they searched for", do not settle
for "the endpoint returned 200".

## Why `qa_check` is one script

Every project has some way to answer "does this work?" — usually several,
mutually inconsistent: a test suite, a CI job, a manual curl someone remembers.
They drift, and the drift is invisible until an incident.

One script, run identically by hand, by CI, and by monitoring, cannot drift
from itself. It returns machine-readable JSON so automation can consume it, and
prints readable output so humans can too.

The failure mode to guard against is **vacuous success**: a check that verifies
nothing and reports "ok". That is why the shipped checker treats "found no
routes to test" as a failure rather than a pass. A red check gets fixed; a
green check that means nothing gets trusted.

## Public-safe by default

Every generated project is split in two: files safe to publish, and files that
are operator-only (`.env`, `LOCAL.md`, local data, host-specific compose
overrides). The second set is gitignored from the first commit, and the scaffold
runs a leak check for absolute home paths and private hostnames before it
finishes.

This matters because the decision to open-source usually comes *after* the code
is written, and retrofitting safety means rewriting history. Starting clean
costs nothing.

Concretely, committed files never contain: absolute paths from your machine,
private hostnames, credentials, or internal IPs. Anything host-specific is read
from `.env` at runtime.

## Localhost-only by default

Generated compose files bind to `127.0.0.1`, never `0.0.0.0`. A service is
reachable from the machine it runs on, and nothing else, until you deliberately
put a reverse proxy in front of it.

`0.0.0.0` exposes a service to every network the host is attached to, including
ones you forgot about. Binding to loopback and adding a proxy is one extra step
and removes a class of accident entirely.

The exception is SSH, which is not something this kit generates.

## Least-privilege containers

Localhost binding limits network exposure, but it does not reduce what a
compromised process can do inside its container. Core shapes therefore run as
the invoking user's numeric UID/GID rather than root, drop Linux capabilities,
set `no-new-privileges`, use read-only root filesystems, bound PID/CPU/memory
usage, and write only through declared project volumes or bounded tmpfs mounts.

The optional Gitea Actions runner is a distinct trust boundary because it mounts
the host Docker socket. It is disabled by default and requires the explicit
`make gitea-runner` command.

## Memory

`memory/` is a plain-text log of decisions and their reasons: why Postgres and
not SQLite, why that retry limit is 3, what you tried that didn't work.

Code records *what* it does. Git records *when* it changed. Neither records
*why* — and "why" is what you have lost six months later when you're deciding
whether a constraint still applies. It is cheap to write at the moment of the
decision and impossible to reconstruct afterwards.

## Living documentation

The convention is that docs change in the same commit as the code, not in a
follow-up that never comes. A feature added without updating `README`,
`CHANGELOG` and the relevant `docs/` page is half-finished.

This is a stronger rule than it looks. It is also the one most often skipped,
which is why generated projects ship the stubs already created — an empty
`docs/ARCHITECTURE.md` in the tree is a much louder reminder than a good
intention.

## Why configuration is a typed boundary

Reading `os.environ` at the point of use is the cheapest possible thing to
write and the most expensive possible thing to debug. The variable is
undeclared, so nothing documents it; untyped, so a port arrives as a string;
and unvalidated, so a typo becomes `None` and surfaces three layers away as a
`TypeError` at 3am.

Declaring every variable once, with a type and a one-line description, moves
that failure to process start, names it, and lists *every* problem at once
rather than one per restart.

The second-order benefit matters more. Because the schema is data, the
`.env.example` block can be generated from it, which makes it correct by
construction rather than by discipline. A hand-maintained example file is
always a little bit wrong — a variable added and never documented, or
documented long after deletion — and both are invisible until a deploy fails.

The rule that makes this hold is the unglamorous one: **never read the
environment outside the config module.** One exception, made once "just for a
debug flag", is how the guarantee stops being a guarantee.

## Why some checks are not allowed to fail the build

`make bench-compare` reports regressions and exits 0. That looks like weakness.
It is the opposite.

Benchmark timings on a shared machine jitter by a few percent from unrelated
load. A gate at zero fires on that jitter within a week. The team learns the
red is meaningless, starts passing `--no-verify`, and eventually deletes the
check — at which point real regressions also stop being caught. The check that
cried wolf is worse than no check, because it consumed the attention budget a
working check would have needed.

So the shipped default warns above +10% p50, writes a machine-readable report,
and never blocks. If you want enforcement, gate on the report JSON in a
separate job you have tuned against your own measured variance. That is a
decision to make deliberately, with data — not to inherit by default.

The same reasoning runs the other way for the drift checks. `check-env`,
`check-locales` and `check-styles` *do* fail the build, because they are
deterministic: they cannot be tripped by an unlucky neighbour on the runner. A
check should be exactly as strict as it is reliable.

## Why the generated conventions have markers

`AGENTS.md` is split by `<!-- scaffold:start -->` / `<!-- scaffold:end -->`.
Inside is generated; outside is yours.

Without the split, a project that wants an improved shared convention has to
hand-merge it or lose its local rules. In practice it does neither, the
conventions rot, and every project ends up with a slightly different stale copy
of the same document. With the split, `make refresh-agents KIT=<path>` is one
command and touches nothing you wrote.

This is also the kit's only upgrade path. Everything else it generates is yours
the moment it is written.

## The `model` shape: what "done" means for a fine-tune

Every shape is a claim about what finished looks like. For a fine-tune it is
not "training completed" — training always completes. It is:

**the dataset is sound, an evaluation actually ran, and the result clears
thresholds that were committed before the run started.**

That last clause carries most of the weight. Thresholds live in
`eval/thresholds.json`, in git. Deciding what counts as good enough *after*
seeing the number is how a regression ships with a rationalisation attached,
and it is the normal outcome when the bar is set by whoever is looking at the
dashboard that afternoon.

### Preflight before GPU

`preflight.py` runs in seconds and refuses to let `train.py` start on a broken
corpus. It checks schema, the output contract, length distribution — and two
things that are easy to miss and expensive to discover late:

**A drifted system prompt.** Every example must share one byte-identical
system prompt. A truncated or edited prompt raises no error; it quietly costs
accuracy, and you find out after the training run.

**Train/val leakage.** An input appearing in both splits produces excellent
eval numbers that do not predict production behaviour at all. Nothing else in
a normal pipeline notices, because every metric you are watching goes *up*.

This is why splitting is by hash of the input rather than by shuffle:
regenerating the dataset cannot silently move an example from val into train.

### Evaluate what you would serve

`evaluate.py` scores a **served endpoint**, not a checkpoint on disk, because
the serving stack, quantisation and sampling parameters all change the answer.
A checkpoint that scores well and a server that answers badly is a real and
frequent gap.

The report records accuracy and latency together, and the shipped thresholds
gate on both. A model two points more accurate and three times slower is
usually not an improvement — and a report that omits latency lets that trade
be made by accident.

Parse failures are counted separately from wrong answers. Output the consumer
cannot parse is a different kind of broken from output that is merely
incorrect, and averaging them together hides it.

### Why the heavy dependencies are quarantined

`torch` and CUDA live in a separate image behind a Compose profile. The
default image has neither, so `make setup`, `make test`, `make lint` and
`make qa` finish in seconds on any machine.

The alternative — one multi-gigabyte GPU image for everything — produces a
project where the quality loop only runs on the training box, which means in
practice it stops running. The split is what keeps a fine-tuning project a
normal project.

## Four shapes for things that break quietly

`mcp`, `scraper`, `bridge` and `cli` were added because each has a way of
failing that looks exactly like working, and that none of the existing shapes'
checks could see.

**`mcp`** — an MCP server that completes its handshake and exposes no tools
passes every process monitor, container healthcheck and port scan there is. It
is also useless. So `tools/list` returning zero is a failure, the same way zero
discovered routes already is in `service`. The checker also asserts the running
surface matches what the source declares, round-trips every tool, and watches
stdout for corruption — because stdio *is* the transport, and one stray `print`
produces a client-side parse error pointing nowhere near its cause.

**`scraper`** — when a site changes its markup, extraction returns nothing.
That is indistinguishable from a search that genuinely had no results, and a
check that only counts rows cannot tell them apart. So the extractor reports
*which* case it hit, and returning nothing without the page saying it was empty
fails the build. Everything runs against committed fixtures: a suite that hits
the live site fails for reasons unrelated to your code, and passes at exactly
the moment the markup moves.

**`bridge`** — a service whose behaviour is dominated by something it does not
control. Health and readiness become different questions: collapsing them means
either being restarted for someone else's outage, or reporting healthy while
serving nothing. Upstream failure maps to 502/503/504, never a bare 500, which
would claim the fault is yours and invite a retry storm into an already
struggling upstream. A circuit breaker stops you becoming the load that keeps
it down.

**`cli`** — stdout is an API. Scripts parse it, pipelines depend on it, and
changing it silently breaks all of them. Golden files make "I tweaked the
output" a reviewable diff. Exit codes get the same treatment, because `cmd &&
next` is a contract: printing help and exiting 0 on no arguments lets the next
command run as though work happened.

The common thread is the rule the kit already had: **a check that reports
success while measuring nothing is worse than one that fails**, because it
looks like coverage.

## The `agent` shape: why the model is a parameter

For an agent, **"it ran without erroring" is the vacuous success.** An agent
that runs, calls no tools, and returns a confident wrong answer looks perfectly
healthy to a process monitor, a container healthcheck and an HTTP probe. So the
same rule applies here as everywhere else in this kit: a scenario that declares
expected tool calls and produces none is a failure.

`build_graph(model)` takes the model as a parameter rather than constructing
one. That single choice is what makes everything else possible. With a scripted
model — a fixed list of assistant turns — the whole graph becomes
deterministic: routing, tool dispatch, multi-tool chaining and termination all
replay identically, offline, for free.

The alternative is an agent whose only checkable behaviour requires a live
model, which in practice means no checkable behaviour at all. Those tests cost
money per run and fail when a provider has a bad afternoon, so they get skipped,
then deleted.

So the shape splits the question in two:

- **Is the graph correct?** Offline, every commit, free. `make qa`.
- **Does a real model behave?** Opt-in, costs tokens. `make evaluate`.

### Termination is a property of the model, not the graph

A tool-calling loop only reaches END when the model stops asking for tools.
Nothing in the graph guarantees that. A model that keeps requesting tools runs
until something else stops it — and if nothing does, you get a hung process and
an unbounded bill rather than a wrong answer.

LangGraph's recursion limit is that backstop, so `qa_check` scripts a model
that never stops and asserts the limit actually fires. Trusting a safety
mechanism you have never seen trigger is how it turns out to be misconfigured
at the worst moment.

### Tool precision, not just pass rate

`evaluate.py` scores expected tool calls over actual ones alongside the pass
rate. An agent that reaches the right answer by calling four tools where one
would do scores a perfect pass rate while being slower, more expensive, and
closer to the edge on the next input. Measuring only correctness rewards
flailing.

### The description is the prompt

A tool's description is not documentation — it is what the model reads to
decide whether and how to call it. A blank one produces a tool that is
technically available and never used correctly, so `qa_check` fails it.
LangChain already rejects a *missing* docstring at import; the check catches
the blank-but-present case it allows.

## The `stream` shape: "connected" is not "working"

A WebRTC session can report `connected`, with ICE `completed` and DTLS
negotiated, and carry no media whatsoever — a codec mismatch, a track that was
never added, a source that failed to start. Every connection-level metric is
green. The viewer sees nothing.

So this shape refuses to treat connection state as success. `qa_check` drives a
real loopback session and asserts frames actually arrive; zero is a failure, in
the same family as zero discovered routes, zero exposed MCP tools and zero
extracted records elsewhere in this kit.

Its subtler sibling is the **stalled source**: the session connects, delivers a
few frames, then the source wedges while the connection stays perfectly
healthy. A byte counter sampled once still looks fine. Only freshness catches
it, which is why `SessionStats` tracks *when* the last frame moved and not just
how many there were.

Both directions count. A send-only broadcast server never receives anything, so
instrumenting only the inbound path reports every healthy stream as dead — a
mistake worth avoiding, since a metric that lies about a working system is
worse than no metric.

### The media source is a parameter

`build_track()` returns a synthetic, procedurally generated video track. That is
what lets the entire path — offer/answer, ICE, DTLS, VP8 encode and decode — be
exercised with no camera, no media file, no GPU and no external service.

Swap it for whatever you are actually streaming. The pattern is the same one the
`agent` shape uses for its model and the `model` shape uses for its serving
stack: the expensive, environment-dependent thing is injected, so everything
around it stays testable.

### Empty ICE servers, on purpose

`ICE_SERVERS` defaults to empty. Loopback and LAN peers need no STUN, and
unreachable public STUN servers turn a 1.3-second local handshake into a
15-second one — measured, not guessed. That is the difference between a check
that runs on every commit and one people quietly disable.

Configure real STUN/TURN for production, where peers are genuinely behind NATs.
Leave it empty for tests.

## The `browser` shape: flake is the defining failure

Browser automation does not usually fail by being wrong. It fails by being
*sometimes* wrong — passing on your laptop, failing in CI, passing again on
retry. So this shape's checks are aimed at flake before they are aimed at
correctness.

**No workflow may wait on a fixed delay.** A `sleep` is a bet that the machine
running the workflow is at least as fast as the one it was written on, and CI
loses that bet constantly. Every wait here is for a condition the page can
actually reach. This is checked statically, so it fails in milliseconds rather
than intermittently at 3am.

**Every workflow must assert something.** A workflow can visit five pages,
match nothing, and complete — the same vacuous pass as zero discovered routes
or zero extracted records. Navigation succeeding is not evidence that anything
worked. The fixture site includes a login page that renders a *failed* sign-in
with a 200 status, precisely because "the page loaded" is the assertion people
reach for and it proves nothing.

**The harness must be able to fail.** `qa_check` runs a workflow against a
selector that does not exist and requires it to go red. A green suite from a
harness that cannot detect breakage is worse than no suite, because it is
believed.

**Repeated runs must agree.** The same workflow runs several times and all
outcomes must match. Flake caught here is flake not debugged later.

### Fixtures, and an ephemeral port

Workflows run against a committed fixture site, not the live internet. A
browser suite pointed at a real site fails for reasons unrelated to your code —
an outage, a rate limit, a redesign — and passes at exactly the moment the site
changes underneath you.

The fixture server binds to port 0 and reports back what it got. On a machine
running dozens of services a hardcoded port is a coin flip, and losing it
produces a test that drives somebody else's service — which presents as a
broken selector and wastes an afternoon. That is not hypothetical: it happened
while building this shape.

### Artifacts on failure only

A failing step writes a screenshot and the page HTML. CI browser failures
rarely reproduce locally, and without artifacts the only remaining tool is
guessing. Capturing only on failure keeps successful runs fast and the
directory small.

## The `game` shape: determinism is the thing that breaks quietly

A game project has a failure mode nothing else in this kit does: **the same
seed stops producing the same game.** Nothing crashes. Nothing logs an error.
The game plays fine. But replays desync, netcode rollback corrupts state, and
old saves load into a different world than they were saved from — and by the
time anyone notices, the cause is many commits back.

So `qa_check` runs the simulation three times from one seed and requires
identical state hashes. Its companion check requires that *different* seeds
produce *different* games, because a seed being silently ignored would make
the determinism check pass perfectly while every match is identical.

And before either: the simulation must actually advance. Two identical runs of
a simulation that does nothing are still identical, so a frozen sim would score
perfect determinism. That is the same vacuous pass this kit refuses everywhere
— zero routes, zero tools, zero records, zero frames.

### The rules live outside the engine loop

`scripts/sim.gd` holds every rule that decides what happens, and knows nothing
about rendering or input. `scripts/main.gd` is a view over it. That separation
is what makes the game checkable at all: a simulation that can only be advanced
by a running game loop cannot be tested, replayed, or verified, and
"deterministic" then means "we hope so".

It is the same injection the `agent` shape uses for its model and the `stream`
shape for its media source — push the part that needs a display, a GPU or a
network to the edge, and the core stays verifiable.

### Positions are quantised before hashing

Floating-point noise far below anything a player could perceive would otherwise
report a false divergence. A determinism check that cries wolf gets deleted,
and then the real divergence ships.

### Other engines

The checks are engine-independent in intent — scenes load, references resolve,
scripts compile, the simulation is deterministic, a tick fits its budget. Only
`scripts/qa_check.gd` is Godot-specific; the Python wrapper and everything else
would be unchanged.

Godot is the reference implementation because it can be verified: it publishes
arm64 and x86_64 Linux builds, runs fully headless, and needs no licence
server. Unity's editor is x86_64-only and needs licence activation for
batchmode CI, so the same checks there run as EditMode/PlayMode tests on an
x86_64 runner.

## The `audio` shape: 200 OK and silence

A synthesis endpoint can return HTTP 200, with a well-formed WAV of exactly the
right length, containing nothing but zeros. Request rate looks fine. Latency
looks fine. Error rate is zero. `/health` is green. And every user hears
silence.

That is the same vacuous pass this kit refuses everywhere else — zero
discovered routes, zero exposed tools, zero extracted records, zero frames —
and it is the reason this shape exists. So the service measures its own output
before returning it, and refuses to serve audio that nobody could hear: an
engine failing on an edge case produces a 500 with a reason rather than a valid,
inaudible 200.

### Measuring the signal, not the response

The subtler failure is a sample-rate or format mismatch. Duration stays
plausible, loudness stays plausible, the file is valid — and playback is
pitch- and speed-shifted, so the voice sounds like a chipmunk.

Nothing about the response reveals that. Only measuring the audio does, which
is why the synthetic engine gives each word a **known, recoverable pitch**: the
checker asks for a word, decodes the result, and confirms the dominant
frequency is what that word should produce. A resampling bug shifts it while
everything else stays convincing.

Silence and emptiness are also kept distinct. An empty buffer means the engine
returned nothing; silence means it returned the wrong thing. Different causes,
different fixes, and conflating them sends you debugging the wrong layer.

### The engine is a parameter

`engines.py` ships a synthetic engine that produces real, audible,
deterministic audio with no model, no GPU and no API key. It is not a stand-in
for speech quality — it is a stand-in for *the pipeline being intact*, which is
what actually breaks: a resampling bug, a format mismatch, an engine returning
an empty buffer on an edge case. Those produce silence regardless of how good
the model is.

Same injection as the `agent` shape's scripted model, the `stream` shape's
synthetic track and the `game` shape's simulation: push the part that needs a
model or a GPU to the edge, and the core stays verifiable on every commit.
