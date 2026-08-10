package app

import (
	"bytes"
	"strings"
	"testing"
)

// Run's streams are injected, so these drive the whole program and assert on
// exact bytes — no subprocess, no golden file needed at this level.

func exec(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	var stdout, stderr bytes.Buffer
	code := Run(args, &stdout, &stderr)
	return code, stdout.String(), stderr.String()
}

func TestHelpGoesToStdoutAndSucceeds(t *testing.T) {
	// Help was asked for, so it is not an error, and piping it into a pager
	// must work — both of which mean stdout and exit 0.
	code, stdout, stderr := exec(t, "--help")
	if code != ExitOK {
		t.Errorf("exit = %d, want %d", code, ExitOK)
	}
	if !strings.Contains(stdout, "Usage:") {
		t.Error("help does not mention usage")
	}
	if stderr != "" {
		t.Errorf("help wrote to stderr: %q", stderr)
	}
}

func TestVersionPrintsTheBuildVersion(t *testing.T) {
	Version = "1.2.3"
	code, stdout, _ := exec(t, "--version")
	if code != ExitOK || !strings.Contains(stdout, "1.2.3") {
		t.Errorf("exit=%d stdout=%q", code, stdout)
	}
}

func TestNoArgumentsIsAUsageError(t *testing.T) {
	// Exiting 0 here would make `cmd && next` proceed as though work happened.
	code, stdout, stderr := exec(t)
	if code != ExitUsage {
		t.Errorf("exit = %d, want %d", code, ExitUsage)
	}
	if stdout != "" {
		t.Errorf("usage error wrote to stdout: %q", stdout)
	}
	if stderr == "" {
		t.Error("usage error gave no explanation")
	}
}

func TestUnknownFlagIsRejected(t *testing.T) {
	// Silently ignoring it leaves the user believing an option took effect.
	code, _, stderr := exec(t, "--nope")
	if code != ExitUsage {
		t.Errorf("exit = %d, want %d", code, ExitUsage)
	}
	if !strings.Contains(stderr, "unknown flag") {
		t.Errorf("stderr = %q", stderr)
	}
}

func TestUnknownCommandIsRejected(t *testing.T) {
	code, _, stderr := exec(t, "frobnicate")
	if code != ExitUsage || !strings.Contains(stderr, "unknown command") {
		t.Errorf("exit=%d stderr=%q", code, stderr)
	}
}

func TestCountRequiresAnArgument(t *testing.T) {
	code, _, stderr := exec(t, "count")
	if code != ExitUsage || stderr == "" {
		t.Errorf("exit=%d stderr=%q", code, stderr)
	}
}

func TestCountOutputIsDeterministic(t *testing.T) {
	// Go randomises map iteration; unstable output makes golden files flaky
	// for reasons unrelated to the code.
	_, first, _ := exec(t, "count", "b a c a")
	for i := 0; i < 20; i++ {
		_, again, _ := exec(t, "count", "b a c a")
		if again != first {
			t.Fatalf("output varies between runs:\n%q\n%q", first, again)
		}
	}
}

func TestCountStatistics(t *testing.T) {
	got := Count("the quick the")
	if got.Words != 3 {
		t.Errorf("words = %d, want 3", got.Words)
	}
	if got.Frequency["the"] != 2 {
		t.Errorf("frequency[the] = %d, want 2", got.Frequency["the"])
	}
}

func TestCountHandlesEmptyInput(t *testing.T) {
	got := Count("")
	if got.Words != 0 || got.Lines != 0 {
		t.Errorf("empty input gave %+v", got)
	}
}

func TestCountStripsPunctuationWhenTallying(t *testing.T) {
	got := Count("dog, dog. dog!")
	if got.Frequency["dog"] != 3 {
		t.Errorf("frequency = %v", got.Frequency)
	}
}

func TestJSONModeEmitsParseableOutput(t *testing.T) {
	code, stdout, _ := exec(t, "--json", "count", "a b")
	if code != ExitOK || !strings.HasPrefix(strings.TrimSpace(stdout), "{") {
		t.Errorf("exit=%d stdout=%q", code, stdout)
	}
}
