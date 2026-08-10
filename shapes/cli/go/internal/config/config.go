// Package config is the typed, validated configuration boundary for <name>.
//
// **Never read os.Getenv anywhere else in this project.** Every environment
// variable is declared once, in Fields, with a type, a default and a one-line
// description. Code calls Load and reads validated values.
//
// Why this exists: an undeclared env var fails at the point of use, deep in a
// call stack, as an empty string. A declared one fails at startup, by name,
// with every problem listed at once.
//
// It also makes .env.example correct by construction — `make env-example`
// regenerates the managed block in that file from Fields, and `make check-env`
// fails when the two drift apart.
//
// To add a variable: append a Field to Fields, run `make env-example`, then
// read it via the Config accessors.
package config

import (
	"bufio"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"
)

// Cast parses and validates one raw value. The error message is shown to
// whoever has to fix the .env, so write it for them.
type Cast func(raw string) (any, error)

// Field declares a single environment variable.
type Field struct {
	Name string
	Help string
	// Cast defaults to AsString when nil.
	Cast Cast
	// Default is used when the variable is unset. Ignored when Required.
	Default  any
	Required bool
	// Secret values are never echoed by Describe, Public or any error.
	Secret bool
	// Commented emits the variable commented-out in .env.example.
	Commented bool
	// Section starts a new labelled group in .env.example.
	Section string
}

// AsString accepts any value.
func AsString(raw string) (any, error) { return raw, nil }

// AsInt requires a base-10 integer.
func AsInt(raw string) (any, error) {
	value, err := strconv.Atoi(strings.TrimSpace(raw))
	if err != nil {
		return nil, fmt.Errorf("expected an integer, got %q", raw)
	}
	return value, nil
}

// AsBool accepts the usual truthy/falsy spellings.
func AsBool(raw string) (any, error) {
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "1", "true", "yes", "on":
		return true, nil
	case "0", "false", "no", "off":
		return false, nil
	}
	return nil, fmt.Errorf("expected a boolean (true/false), got %q", raw)
}

// AsPort requires a valid TCP port.
func AsPort(raw string) (any, error) {
	value, err := AsInt(raw)
	if err != nil {
		return nil, err
	}
	port := value.(int)
	if port < 1 || port > 65535 {
		return nil, fmt.Errorf("port must be between 1 and 65535, got %d", port)
	}
	return port, nil
}

// AsLogLevel restricts to the levels the project's logger understands.
func AsLogLevel(raw string) (any, error) {
	level := strings.ToLower(strings.TrimSpace(raw))
	for _, allowed := range []string{"debug", "info", "warn", "error", "fatal"} {
		if level == allowed {
			return level, nil
		}
	}
	return nil, fmt.Errorf("expected one of debug, info, warn, error, fatal, got %q", raw)
}

// Fields is the schema. Add your own variables here.
var Fields = []Field{
	{
		Name:    "LOG_LEVEL",
		Help:    "One of debug, info, warn, error, fatal.",
		Cast:    AsLogLevel,
		Default: "info",
		Section: "Application",
	},
	{
		Name:    "ENV",
		Help:    "Deployment environment name: development, staging, production.",
		Default: "development",
	},
	{
		Name:    "APP_VERSION",
		Help:    "Build version, injected at build time. Reported by `--version`.",
		Default: "0.0.0-dev",
	},
	{
		Name:      "NO_COLOR",
		Help:      "Set to any value to disable ANSI colour output.",
		Commented: true,
	},
	{
		Name:    "HOST_UID",
		Help:    "Numeric UID the container runs as, so bind mounts stay writable.",
		Cast:    AsInt,
		Default: <HOST_UID>,
		Section: "Container ownership",
	},
	{
		Name:    "HOST_GID",
		Help:    "Numeric GID the container runs as.",
		Cast:    AsInt,
		Default: <HOST_GID>,
	},
}

// Config holds validated values.
type Config struct {
	values map[string]any
}

// String returns a string-typed field, or "" when absent.
func (c Config) String(name string) string {
	if v, ok := c.values[name].(string); ok {
		return v
	}
	return ""
}

// Int returns an int-typed field, or 0 when absent.
func (c Config) Int(name string) int {
	if v, ok := c.values[name].(int); ok {
		return v
	}
	return 0
}

// Bool returns a bool-typed field, or false when absent.
func (c Config) Bool(name string) bool {
	if v, ok := c.values[name].(bool); ok {
		return v
	}
	return false
}

// Public returns every non-secret value — safe for logs and QA output.
func (c Config) Public() map[string]any {
	secrets := map[string]bool{}
	for _, f := range Fields {
		if f.Secret {
			secrets[f.Name] = true
		}
	}
	out := map[string]any{}
	for k, v := range c.values {
		if !secrets[k] {
			out[k] = v
		}
	}
	return out
}

// readEnvFile parses a .env file. Real process env always wins over the file.
func readEnvFile(path string) map[string]string {
	values := map[string]string{}
	file, err := os.Open(path)
	if err != nil {
		return values
	}
	defer file.Close()

	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		key, raw, _ := strings.Cut(line, "=")
		raw = strings.TrimSpace(raw)
		// Strip one layer of matching quotes, the way dotenv does.
		if len(raw) >= 2 && raw[0] == raw[len(raw)-1] && (raw[0] == '\'' || raw[0] == '"') {
			raw = raw[1 : len(raw)-1]
		}
		values[strings.TrimSpace(key)] = raw
	}
	return values
}

// Load validates the environment against Fields. It collects every problem
// before returning — fixing config one error per restart is a miserable loop.
func Load(envFile string) (Config, error) {
	fileValues := readEnvFile(envFile)

	values := map[string]any{}
	var problems []string

	for _, spec := range Fields {
		raw, ok := os.LookupEnv(spec.Name)
		if !ok || raw == "" {
			raw, ok = fileValues[spec.Name]
		}
		if !ok || raw == "" {
			if spec.Required {
				problems = append(problems,
					fmt.Sprintf("  %s is required but not set — %s", spec.Name, spec.Help))
			} else {
				values[spec.Name] = spec.Default
			}
			continue
		}
		cast := spec.Cast
		if cast == nil {
			cast = AsString
		}
		parsed, err := cast(raw)
		if err != nil {
			// Never echo the offending value for a secret.
			detail := err.Error()
			if spec.Secret {
				detail = "invalid value"
			}
			problems = append(problems, fmt.Sprintf("  %s: %s", spec.Name, detail))
			continue
		}
		values[spec.Name] = parsed
	}

	if len(problems) > 0 {
		sort.Strings(problems)
		return Config{}, fmt.Errorf(
			"invalid configuration in .env:\n%s\n\nSee .env.example for every supported variable",
			strings.Join(problems, "\n"))
	}

	return Config{values: values}, nil
}

// Managed-block delimiters in .env.example. The marker text is identical
// across every language the kit supports, so scripts/check_env.py needs no
// per-language special-casing.
const (
	EnvBlockStart = "# scaffold:env:start — generated by 'make env-example', do not edit by hand"
	EnvBlockEnd   = "# scaffold:env:end"
)

func wrap(text string, width int) []string {
	var lines []string
	current := ""
	for _, word := range strings.Fields(text) {
		if current != "" && len(current)+len(word)+1 > width {
			lines = append(lines, current)
			current = word
			continue
		}
		if current == "" {
			current = word
		} else {
			current += " " + word
		}
	}
	if current != "" {
		lines = append(lines, current)
	}
	if len(lines) == 0 {
		return []string{""}
	}
	return lines
}

// Describe renders the managed block of .env.example from Fields.
func Describe() string {
	var b strings.Builder
	fmt.Fprintln(&b, EnvBlockStart)
	fmt.Fprintln(&b)
	for _, spec := range Fields {
		if spec.Section != "" {
			pad := 66 - len(spec.Section)
			if pad < 0 {
				pad = 0
			}
			fmt.Fprintf(&b, "# ── %s %s\n", spec.Section, strings.Repeat("─", pad))
		}
		for _, chunk := range wrap(spec.Help, 74) {
			fmt.Fprintf(&b, "# %s\n", chunk)
		}
		if spec.Required {
			fmt.Fprintln(&b, "# REQUIRED.")
		}
		prefix := ""
		if spec.Commented {
			prefix = "# "
		}
		value := ""
		if spec.Default != nil {
			value = fmt.Sprintf("%v", spec.Default)
		}
		fmt.Fprintf(&b, "%s%s=%s\n\n", prefix, spec.Name, value)
	}
	fmt.Fprint(&b, EnvBlockEnd)
	return b.String()
}
