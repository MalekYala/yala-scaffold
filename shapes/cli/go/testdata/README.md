# testdata/

Golden files: the exact bytes `<name>` is expected to write to stdout.

Stdout is an API. Anything downstream in a pipeline — `jq`, `awk`, another
program, a human's muscle memory — depends on it, and changing it silently
breaks all of them. A golden file turns "I tweaked the output a bit" into a
reviewable diff.

Regenerate deliberately, when the output is *meant* to change:

```bash
make qa-update      # rewrites the golden files
git diff testdata/  # review this like any other change
```

If you find yourself regenerating on every run, the output is not
deterministic — sort your map iteration, pin your timestamps — and that is a
bug in the program, not in the test.
