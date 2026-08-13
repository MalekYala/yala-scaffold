// Package app holds <name>'s behaviour, separate from its command-line
// plumbing in cmd/cli.
//
// The split matters for testability: Run takes its streams and arguments as
// parameters rather than reaching for os.Args and os.Stdout, so a test can
// drive the whole program with a buffer and assert on exact bytes. A CLI whose
// logic is welded to package-level globals can only be tested by executing it.
package app

import (
	"encoding/json"
	"fmt"
	"io"
	"sort"
	"strings"
)

// Version is overridden at build time via -ldflags.
var Version = "0.0.0-dev"

// Name is the command name shown in help and errors.
const Name = "<name>"

// Exit codes. Documented here and in the README because they are a contract:
// scripts branch on them, and changing one silently breaks a caller.
const (
	ExitOK       = 0
	ExitError    = 1
	ExitUsage    = 2
	ExitNotFound = 3
)

const usage = `` + Name + ` — one-line description of what this does

Usage:
  ` + Name + ` [flags] <command> [args]

Commands:
  count <text>    Count words, characters and lines in the argument
  version         Print the version and exit

Flags:
  -h, --help      Show this help and exit
  -v, --version   Print the version and exit
      --json      Emit machine-readable JSON instead of text

Exit codes:
  0  success
  1  runtime error
  2  usage error (bad flag, unknown command, missing argument)
  3  requested thing not found
`

// Run executes the CLI. Streams are injected so tests can capture output
// exactly; the returned int is the process exit code.
func Run(args []string, stdout, stderr io.Writer) int {
	var (
		asJSON    bool
		rest      []string
		wantsHelp bool
		wantsVer  bool
	)

	for _, arg := range args {
		switch arg {
		case "-h", "--help":
			wantsHelp = true
		case "-v", "--version":
			wantsVer = true
		case "--json":
			asJSON = true
		default:
			if strings.HasPrefix(arg, "-") {
				// An unrecognised flag is a usage error, not something to
				// silently ignore — ignoring it means the user believes an
				// option took effect when it did not.
				fmt.Fprintf(stderr, "%s: unknown flag %q\nTry '%s --help'.\n", Name, arg, Name)
				return ExitUsage
			}
			rest = append(rest, arg)
		}
	}

	// --help goes to stdout and exits 0: it was asked for, so it is not an
	// error, and a user piping it into a pager should get it on stdout.
	if wantsHelp {
		fmt.Fprint(stdout, usage)
		return ExitOK
	}
	if wantsVer || (len(rest) > 0 && rest[0] == "version") {
		fmt.Fprintf(stdout, "%s %s\n", Name, Version)
		return ExitOK
	}

	if len(rest) == 0 {
		// No arguments: print usage to stderr and exit non-zero. Printing help
		// and exiting 0 would make `cmd && next` proceed as if work happened.
		fmt.Fprint(stderr, usage)
		return ExitUsage
	}

	switch rest[0] {
	case "count":
		if len(rest) < 2 {
			fmt.Fprintf(stderr, "%s: count requires a text argument\n", Name)
			return ExitUsage
		}
		return count(strings.Join(rest[1:], " "), asJSON, stdout)
	default:
		fmt.Fprintf(stderr, "%s: unknown command %q\nTry '%s --help'.\n", Name, rest[0], Name)
		return ExitUsage
	}
}

// Counts is the result of the count command.
type Counts struct {
	Words      int            `json:"words"`
	Characters int            `json:"characters"`
	Lines      int            `json:"lines"`
	Frequency  map[string]int `json:"frequency"`
}

// Count computes the statistics. Exported and pure so it can be tested
// without going through argument parsing.
func Count(text string) Counts {
	fields := strings.Fields(text)
	frequency := map[string]int{}
	for _, word := range fields {
		frequency[strings.ToLower(strings.Trim(word, ".,!?;:\"'"))]++
	}
	lines := 0
	if text != "" {
		lines = strings.Count(text, "\n") + 1
	}
	return Counts{
		Words:      len(fields),
		Characters: len([]rune(text)),
		Lines:      lines,
		Frequency:  frequency,
	}
}

func count(text string, asJSON bool, stdout io.Writer) int {
	result := Count(text)

	if asJSON {
		encoded, err := json.MarshalIndent(result, "", "  ")
		if err != nil {
			return ExitError
		}
		fmt.Fprintln(stdout, string(encoded))
		return ExitOK
	}

	fmt.Fprintf(stdout, "words:      %d\n", result.Words)
	fmt.Fprintf(stdout, "characters: %d\n", result.Characters)
	fmt.Fprintf(stdout, "lines:      %d\n", result.Lines)

	// Deterministic ordering: map iteration in Go is randomised, and unstable
	// output makes golden-file tests flaky for no reason.
	words := make([]string, 0, len(result.Frequency))
	for word := range result.Frequency {
		words = append(words, word)
	}
	sort.Strings(words)
	for _, word := range words {
		fmt.Fprintf(stdout, "  %-16s %d\n", word, result.Frequency[word])
	}
	return ExitOK
}
