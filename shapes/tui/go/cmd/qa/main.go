package main

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"strings"
)

type check struct {
	Name  string `json:"name"`
	OK    bool   `json:"ok"`
	Error string `json:"error,omitempty"`
}

type report struct {
	Status string  `json:"status"`
	Checks []check `json:"checks"`
}

func main() {
	command := exec.Command("/app/<name>", "--demo")
	output, err := command.CombinedOutput()
	rendered := string(output)
	renderCheck := check{
		Name: "demo_render",
		OK:   err == nil && strings.Contains(rendered, "<name>") && strings.Contains(rendered, "q quit"),
	}
	if err != nil {
		renderCheck.Error = err.Error()
	}
	result := report{Status: "ok", Checks: []check{renderCheck}}
	if !renderCheck.OK {
		result.Status = "fail"
	}
	encoded, encodeErr := json.MarshalIndent(result, "", "  ")
	if encodeErr != nil {
		fmt.Fprintf(os.Stderr, "encode QA report: %v\n", encodeErr)
		os.Exit(1)
	}
	fmt.Println(string(encoded))
	if result.Status != "ok" {
		os.Exit(1)
	}
}
