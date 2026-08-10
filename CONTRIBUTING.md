# Contributing

## Testing a change

The repository includes a scaffold matrix that creates every supported core
shape in isolated temporary directories:

```bash
make test
```

Before merging container, dependency, or runtime changes, run the full sandbox
matrix:

```bash
make test-full
```

The full matrix builds, tests, lints, typechecks, runs, and QA-checks all ten
supported shape/language combinations. It uses project-specific names and ports
and cleans up only the containers, images, networks, and temporary files it
created.

## Rules for template changes

1. **No absolute paths, private hostnames, or credentials** in anything a
   generated project would commit. Host-specific values come from `.env` with a
   documented default.
2. **External Docker networks need `name:`.** The alias in a compose file is
   never the real network name; without the mapping the stack cannot start.
3. **`docker-compose.override.yml` replaces `networks:`, it does not merge.**
   Anything added there must repeat every network the service needs.
4. **A check that verifies nothing must fail, not pass.** Vacuous success looks
   like coverage and is worse than an honest failure.
5. **Docs change with the code.** A template gaining a feature without a README
   or `docs/` update is half-done.
6. **Do not mutate the host.** Scaffold and validation commands must not install
   host packages, write global Git config, use host networking, mount the Docker
   socket, or touch unrelated Docker resources.
7. **Containers run least-privileged.** Core services use non-root users,
   dropped capabilities, `no-new-privileges`, read-only root filesystems,
   process/resource limits, and explicit writable volumes only.

## Layout

```
yala.sh     the whole tool — one bash script
shapes/         per-shape, per-language project skeletons
templates/      files every project gets, whatever its shape
addons/         opt-in modules (bot, gitea, rag, kpi)
docs/           documentation for this kit, not for generated projects
```

Placeholders substituted into templates: `<name>`, `<PORT>`, `<shape>`,
`<lang>`, `<domain>`, `<year>`, `<date>`, `<holder>`.
