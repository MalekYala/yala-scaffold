#!/usr/bin/env bash
# Scaffold every shape/lang variant into a temp dir and check the generated CI
# files. Needs only bash, git and python3 + PyYAML, so it runs in CI where
# tests/scaffold_matrix.sh (which builds and runs the projects) can't.
set -euo pipefail

cd "$(dirname "$0")/.."

# yala.sh preflights `docker compose version` but generation never runs docker.
# Without a real docker, use a stub that answers that one call and fails
# loudly on anything else.
if ! command -v docker >/dev/null 2>&1; then
    stub_dir="$(mktemp -d)"
    cat > "$stub_dir/docker" <<'STUB'
#!/bin/sh
[ "$1 $2" = "compose version" ] && { echo "Docker Compose version v2 (stub)"; exit 0; }
echo "docker called during scaffold: $*" >&2
exit 99
STUB
    chmod +x "$stub_dir/docker"
    PATH="$stub_dir:$PATH"
fi

export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-ci}" GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-ci@example.invalid}"
export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-ci}" GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-ci@example.invalid}"

out="$(mktemp -d)"
n=0
for dir in shapes/*/*/; do
    shape="$(basename "$(dirname "$dir")")"
    lang="$(basename "$dir")"
    if ! ./yala.sh "ci-$shape-$lang" --type "$shape" --lang "$lang" --port "$((18000 + n))" --into "$out" >/dev/null 2>"$out/err.log"; then
        echo "FAIL $shape/$lang" >&2
        tail -20 "$out/err.log" >&2
        exit 1
    fi
    test -f "$out/ci-$shape-$lang/.gitlab-ci.yml"
    n=$((n + 1))
done

python3 tests/check_ci_yaml.py "$out"
echo "scaffolded $n shape/lang variants"
