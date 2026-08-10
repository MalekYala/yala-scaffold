# Repository Readiness and Code Review

## Readiness verdict

This repository is a project generator, not a single application. Its supported
workflow is Docker Compose: the host needs Bash, Git, Docker, and Compose v2,
while generated Python/Node dependencies and quality tools run inside
containers.

The original templates generated every supported shape and valid Compose
configuration, but they were not fully out of the box. The implementation work
in this repository addresses the highest-impact gaps below.

## Findings

| Priority | Finding | Resolution |
|---|---|---|
| High | `--license Apache-2.0` wrote an MIT body but labeled it Apache | Unsupported licenses are rejected before project creation |
| High | Node templates used `node --test tests/`, which fails on supported modern Node versions | Test discovery and production-code test wiring updated |
| High | Generated Node docs invoked nonexistent `qa_check.py` | QA filenames and commands are language-aware |
| High | Broad Python lower bounds allowed incompatible dependency combinations | Python versions are constrained and tested in container targets |
| High | Scaffolding depended on host Git identity and attempted optional host formatting | Commit-scoped fallback identity; no host package installation/config changes |
| Medium | Default docs and Make targets advertised add-ons that were not generated | Add-on output is conditional and disabled targets explain the required flag |
| Medium | Node tests duplicated handlers/helpers instead of importing production code | App factories and pure helpers are exported and tested directly |
| Medium | The generator had no automated regression suite | `make test` and `make test-full` exercise the scaffold matrix |
| Low | Missing flag values produced `$2: unbound variable` | Value-taking flags now produce explicit usage errors |

## Container security feedback

Core containers should preserve all of these controls:

- Dedicated non-root runtime users.
- `cap_drop: [ALL]`.
- `security_opt: [no-new-privileges:true]`.
- Read-only root filesystems with explicit writable volumes and bounded tmpfs.
- CPU, memory, and PID limits.
- Host port publication on `127.0.0.1` only.
- No privileged mode, host networking, or Docker socket mounts.

The optional Gitea Actions runner is the exception that requires special
operator trust: it mounts `/var/run/docker.sock`, which provides host-level
Docker control. It is therefore placed behind an explicit Compose profile and
the separate `make gitea-runner` command instead of starting with core or Gitea
server workflows.

## Dependency guidance

Use the generated Make targets:

```bash
make doctor
make setup
make run
make test
make qa
```

Do not install generated project dependencies globally. Node lockfiles and
bounded Python requirements make container builds deterministic enough for the
supported runtime, while the test image contains lint, typecheck, and unit-test
tools without inflating the runtime image.

## Remaining maintenance recommendations

1. Keep the full scaffold matrix required in CI whenever templates, Dockerfiles,
   Compose files, or `yala.sh` change.
2. Pin third-party CI and container images deliberately rather than following
   floating `latest` tags.
3. Treat enabling the Gitea runner as a security boundary and review every
   workflow/action before use.
4. Periodically rebuild all template images to catch upstream package and base
   image changes before users encounter them.
