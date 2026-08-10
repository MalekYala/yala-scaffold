# Vault add-on — `<name>`

Pulls this project's secrets from HashiCorp Vault into `.env`, instead of
having someone paste them in by hand and then forget which copy is current.

## What you need

This add-on talks to infrastructure you must already run:

- A reachable Vault server (`VAULT_ADDR`), unsealed.
- A **KV v2** secrets engine (default mount `kv`).
- An AppRole this project can authenticate as, with read access to its own
  secrets and nothing else.

If you do not already run Vault, skip this add-on entirely — `.env.example` and
a hand-written `.env` remain fully supported, and nothing here is required to
run the project.

## Configuration

All of it comes from the environment, never from a path baked into a file.
That is deliberate: an absolute path into somebody's home directory works
beautifully on one machine and makes the project unpublishable.

| Variable | Default | Meaning |
|---|---|---|
| `VAULT_ADDR` | — | Vault API address, e.g. `http://127.0.0.1:8200`. Required. |
| `VAULT_ROLE` | — | AppRole to authenticate as. Required unless `VAULT_TOKEN` is set. |
| `VAULT_KV_MOUNT` | `kv` | Name of the KV v2 mount. |
| `VAULT_CREDS_DIR` | `~/.vault` | Where `<role>/role-id` and `<role>/secret-id` live. |
| `VAULT_TOKEN` | — | Pre-obtained token. Skips AppRole login. |

Credentials live **outside the repository**, under `VAULT_CREDS_DIR`, mode
`0600`. Nothing in this directory is ever committed.

## First run

**1. Create a project-scoped policy.** Grant read on this project's prefix and
nothing more. A shared, broadly-scoped credential is how one compromised
project becomes every compromised project.

```hcl
# <name>-read
path "kv/data/<name>/*"     { capabilities = ["read"] }
path "kv/metadata/<name>/*" { capabilities = ["read", "list"] }
```

```bash
vault policy write <name>-read <name>-read.hcl
```

**2. Create an AppRole bound to it**, with a short token TTL:

```bash
vault auth enable approle   # once per Vault, if not already enabled

vault write auth/approle/role/<name> \
    token_policies=<name>-read \
    token_ttl=1h token_max_ttl=1h
```

**3. Write the credentials to disk**, readable only by you:

```bash
mkdir -p ~/.vault/<name> && chmod 700 ~/.vault ~/.vault/<name>
umask 077
vault read  -field=role_id   auth/approle/role/<name>/role-id   > ~/.vault/<name>/role-id
vault write -f -field=secret_id auth/approle/role/<name>/secret-id > ~/.vault/<name>/secret-id
```

**4. Point the project at it** — in `.env`:

```bash
VAULT_ADDR=http://127.0.0.1:8200
VAULT_ROLE=<name>
```

**5. Declare what you need** in `vault/secret-map.tsv`, then:

```bash
make secrets-check    # does every mapped secret resolve?
make secrets-pull     # write them into .env (mode 0600)
```

## Day to day

| Command | Does |
|---|---|
| `make secrets-pull` | Fetch every mapped secret into `.env`. Refuses to clobber a locally-changed value without `FORCE=1`. |
| `make secrets-check` | Verify each mapped secret resolves. Prints names and pass/fail — never values. |
| `make secrets-diff` | Report which local values differ from Vault, **by key name only**. |

## Design rules

These are not negotiable, and are worth understanding before you extend this.

**Nothing is a hardcoded path.** Discovery is by environment variable, so a
generated project stays publishable and portable.

**Fail-closed, never partial.** `pull.sh` builds the whole file in memory and
writes only if every secret resolved. A half-written `.env` starts the service
in a broken state that surfaces somewhere unrelated — far worse than not
starting.

**Sealed and unreachable are different errors.** They have different fixes
(unseal it / correct `VAULT_ADDR`), so they get different messages.

**No values are ever printed.** Not on success, not in an error, not under
`set -x`. `check.sh` reports names and status only, so it is safe to run in a
screen share or paste into an issue.

**CI never authenticates to Vault.** Pipelines use their own injected
variables. This add-on is for developer workstations and deploy hosts. Wiring a
long-lived Vault credential into CI undoes most of the benefit.

**`secret-map.tsv` is committed; secrets are not.** Names and paths in review,
values in Vault.

## Rotation

See [rotate.md](rotate.md).

## Troubleshooting

**`Vault unreachable at …`** — the server is not answering. Check `VAULT_ADDR`
and that the container or service is running.

**`Vault at … is sealed`** — it is running but locked. Unseal it, then retry.

**`AppRole login failed`** — the `secret-id` has most likely expired or been
consumed. Mint a new one (step 3 above).

**`cannot read kv/<path>`** — either the path does not exist, or the role's
policy does not grant `read` on it. `vault kv get kv/<path>` with your own
token distinguishes the two.

**`field '<x>' not present at …`** — the secret exists but has no such field.
`vault kv get kv/<path>` lists the real field names; fix the third column in
`secret-map.tsv`.
