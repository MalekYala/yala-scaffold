// Command envtool renders and validates <name>'s configuration schema.
//
// It exists so the same two operations available in the Python and Node
// shapes are available here:
//
//	go run ./cmd/envtool --print-env   # render the .env.example managed block
//	go run ./cmd/envtool --check       # validate the current environment
//
// `make env-example` and `make check-env` drive it; there is rarely a reason
// to run it by hand.
package main

import (
	"flag"
	"fmt"
	"os"
	"sort"

	"example.com/yala/tui/internal/config"
)

func main() {
	printEnv := flag.Bool("print-env", false, "render the .env.example managed block")
	check := flag.Bool("check", false, "validate the current environment")
	envFile := flag.String("env-file", ".env", "path to the .env file")
	flag.Parse()

	switch {
	case *printEnv:
		fmt.Println(config.Describe())

	case *check:
		cfg, err := config.Load(*envFile)
		if err != nil {
			fmt.Fprintln(os.Stderr, err)
			os.Exit(1)
		}
		fmt.Println("configuration valid")
		public := cfg.Public()
		names := make([]string, 0, len(public))
		for name := range public {
			names = append(names, name)
		}
		sort.Strings(names)
		for _, name := range names {
			fmt.Printf("  %s=%v\n", name, public[name])
		}

	default:
		fmt.Fprintln(os.Stderr, "usage: envtool [--print-env | --check] [--env-file PATH]")
		os.Exit(2)
	}
}
