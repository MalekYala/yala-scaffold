# Secret rotation — `<name>`

A runbook stub. Fill in the project-specific parts the first time you rotate
something; the shape of the procedure is the same for every secret.

## When to rotate

- On a schedule, per your policy (quarterly is a common default).
- Immediately, on any suspected exposure: a secret in a log, a laptop lost, a
  contractor offboarded, a dependency compromised.
- Whenever someone with access leaves.

## The order that avoids an outage

The failure mode to design around is rotating the secret *before* the consumers
can accept the new one. Where the provider supports two live credentials, use
that window.

1. **Enumerate consumers.** Everything reading this value: this project, other
   projects, CI, deploy hosts, monitoring. `grep` the secret's `ENV_VAR` name
   across your `secret-map.tsv` files — that is what makes them worth
   committing.

   | Consumer | Reads | Owner | Notes |
   |---|---|---|---|
   | `<name>` | `vault/secret-map.tsv` | | |
   | *(add others)* | | | |

2. **Mint the new credential at the provider**, leaving the old one live.

3. **Write it to Vault:**

   ```bash
   vault kv patch kv/<name>/<path> <field>=<new-value>
   ```

   Use `patch`, not `put`: `put` replaces the entire secret and silently drops
   every other field at that path.

4. **Roll consumers**, one at a time, verifying each:

   ```bash
   make secrets-pull
   make secrets-check
   make run && make qa
   ```

5. **Revoke the old credential at the provider.** Not before step 4 completes
   everywhere — this is the step people skip, and a revoked-too-early secret is
   an outage while a revoked-too-late one is merely a risk.

6. **Record it** in `memory/decisions/` — what was rotated, when, why, and
   anything that surprised you. The next rotation is usually done by someone
   who was not here for this one.

## Rotating the AppRole credential itself

The project's own `secret-id` expires or gets consumed. Re-mint it:

```bash
umask 077
vault write -f -field=secret_id \
    auth/approle/role/<name>/secret-id > ~/.vault/<name>/secret-id
```

The `role-id` is stable and does not need re-minting.

## Verifying afterwards

```bash
make secrets-check     # every mapped secret still resolves
make secrets-diff      # local .env agrees with Vault (by key name)
make qa                # the project actually works with the new values
```

`make qa` matters most. A rotation that resolves cleanly but breaks
authentication against the downstream service has not succeeded — it has just
failed somewhere you are not looking yet.
