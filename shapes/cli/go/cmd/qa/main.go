// Command qa-check verifies <name>'s command-line contract.
//
// A CLI's contract is not "it runs" — it is the things scripts and humans
// depend on and that break silently:
//
//	--help exits 0 and goes to stdout      (piping it into a pager must work)
//	--version reports the build version    (an incident asks "which build?")
//	a bad flag exits non-zero, with a hint (silently ignoring it is worse)
//	no arguments exits non-zero            (`cmd && next` must not proceed)
//	output matches the golden file         (stdout is an API for pipelines)
//
// Golden files live in testdata/. Regenerate deliberately with -update when
// output is *meant* to change, and review that diff like any other.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

type check struct {
	Name   string `json:"name"`
	OK     bool   `json:"ok"`
	Detail string `json:"detail,omitempty"`
}

type report struct {
	Status string  `json:"status"`
	Checks []check `json:"checks"`
}

type result struct {
	stdout, stderr string
	code           int
}

func run(binary string, args ...string) result {
	cmd := exec.Command(binary, args...)
	var out, errBuf bytes.Buffer
	cmd.Stdout = &out
	cmd.Stderr = &errBuf
	err := cmd.Run()
	code := 0
	var exitErr *exec.ExitError
	if err != nil {
		if ok := asExitError(err, &exitErr); ok {
			code = exitErr.ExitCode()
		} else {
			code = -1
		}
	}
	return result{stdout: out.String(), stderr: errBuf.String(), code: code}
}

func asExitError(err error, target **exec.ExitError) bool {
	if e, ok := err.(*exec.ExitError); ok {
		*target = e
		return true
	}
	return false
}

func main() {
	binary := flag.String("bin", "./bin/<name>", "path to the built binary")
	update := flag.Bool("update", false, "rewrite golden files instead of comparing")
	flag.Parse()

	if _, err := os.Stat(*binary); err != nil {
		fmt.Fprintf(os.Stderr, "qa-check: no binary at %s — run `make build` first\n", *binary)
		os.Exit(1)
	}

	var checks []check

	// --help: stdout, exit 0, and actually useful.
	help := run(*binary, "--help")
	checks = append(checks, check{
		Name:   "help",
		OK:     help.code == 0 && strings.Contains(help.stdout, "Usage:") && help.stderr == "",
		Detail: fmt.Sprintf("exit=%d stdout=%dB stderr=%dB", help.code, len(help.stdout), len(help.stderr)),
	})

	// --version: exit 0 and a non-empty version on stdout.
	version := run(*binary, "--version")
	checks = append(checks, check{
		Name:   "version",
		OK:     version.code == 0 && len(strings.Fields(version.stdout)) >= 2,
		Detail: strings.TrimSpace(version.stdout),
	})

	// An unknown flag must fail loudly. Ignoring it leaves the user believing
	// an option took effect when it did not.
	bad := run(*binary, "--definitely-not-a-flag")
	checks = append(checks, check{
		Name:   "rejects_unknown_flag",
		OK:     bad.code != 0 && bad.stderr != "",
		Detail: fmt.Sprintf("exit=%d stderr=%q", bad.code, truncate(bad.stderr, 60)),
	})

	// No arguments must not exit 0, or `cmd && next` proceeds as if it worked.
	none := run(*binary)
	checks = append(checks, check{
		Name:   "no_args_is_usage_error",
		OK:     none.code != 0,
		Detail: fmt.Sprintf("exit=%d", none.code),
	})

	// Golden output: stdout is an API for anything downstream in a pipeline.
	golden := filepath.Join("testdata", "count.golden")
	actual := run(*binary, "count", "the quick brown fox jumps over the lazy dog")
	if *update {
		if err := os.WriteFile(golden, []byte(actual.stdout), 0o644); err != nil {
			fmt.Fprintf(os.Stderr, "qa-check: cannot write %s: %v\n", golden, err)
			os.Exit(1)
		}
		fmt.Fprintf(os.Stderr, "qa-check: updated %s\n", golden)
	}
	expected, err := os.ReadFile(golden)
	switch {
	case err != nil:
		checks = append(checks, check{Name: "golden_output", OK: false,
			Detail: fmt.Sprintf("no golden file at %s — create it with `-update`", golden)})
	default:
		checks = append(checks, check{
			Name: "golden_output",
			OK:   actual.stdout == string(expected),
			Detail: func() string {
				if actual.stdout == string(expected) {
					return "stdout matches testdata/count.golden"
				}
				return "stdout differs from the golden file; if the change is intended, re-run with -update and review the diff"
			}(),
		})
	}

	// JSON mode must emit parseable JSON. A --json flag that emits prose is
	// worse than no flag: callers pipe it straight into a parser.
	jsonOut := run(*binary, "--json", "count", "a b a")
	var parsed map[string]any
	jsonErr := json.Unmarshal([]byte(jsonOut.stdout), &parsed)
	checks = append(checks, check{
		Name:   "json_mode",
		OK:     jsonOut.code == 0 && jsonErr == nil,
		Detail: fmt.Sprintf("exit=%d parse=%v", jsonOut.code, jsonErr),
	})

	final := report{Status: "ok", Checks: checks}
	for _, c := range checks {
		if !c.OK {
			final.Status = "fail"
		}
	}
	encoded, _ := json.MarshalIndent(final, "", "  ")
	fmt.Println(string(encoded))
	if final.Status != "ok" {
		os.Exit(1)
	}
}

func truncate(s string, n int) string {
	s = strings.TrimSpace(s)
	if len(s) <= n {
		return s
	}
	return s[:n] + "…"
}
