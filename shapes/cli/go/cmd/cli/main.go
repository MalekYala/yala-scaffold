// Command <name> is the entry point. Deliberately thin: everything testable
// lives in internal/app, so the only thing here is wiring os.Args and the
// process exit code.
package main

import (
	"os"

	"example.com/yala/cli/internal/app"
)

// version is injected at build time: -ldflags "-X main.version=$(VERSION)".
var version = "0.0.0-dev"

func main() {
	app.Version = version
	os.Exit(app.Run(os.Args[1:], os.Stdout, os.Stderr))
}
