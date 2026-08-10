package main

import (
	"flag"
	"fmt"
	"os"
	"strings"

	tea "github.com/charmbracelet/bubbletea"
)

var menuItems = []string{
	"Inspect system status",
	"Run project checks",
	"View recent activity",
}

type model struct {
	cursor   int
	selected string
}

func initialModel() model {
	return model{}
}

func (model) Init() tea.Cmd {
	return nil
}

func (m model) Update(message tea.Msg) (tea.Model, tea.Cmd) {
	switch message := message.(type) {
	case tea.KeyMsg:
		switch message.String() {
		case "ctrl+c", "q":
			return m, tea.Quit
		case "up", "k":
			if m.cursor > 0 {
				m.cursor--
			}
		case "down", "j":
			if m.cursor < len(menuItems)-1 {
				m.cursor++
			}
		case "enter":
			m.selected = menuItems[m.cursor]
		}
	}
	return m, nil
}

func (m model) View() string {
	var view strings.Builder
	fmt.Fprintln(&view, "\033[1;36m<name>\033[0m")
	fmt.Fprintln(&view, "A sandboxed Go terminal interface")
	fmt.Fprintln(&view)
	for index, item := range menuItems {
		cursor := " "
		if index == m.cursor {
			cursor = ">"
		}
		fmt.Fprintf(&view, "%s %s\n", cursor, item)
	}
	if m.selected != "" {
		fmt.Fprintf(&view, "\nSelected: %s\n", m.selected)
	}
	fmt.Fprintln(&view, "\n↑/k up  ↓/j down  enter select  q quit")
	return view.String()
}

func main() {
	demo := flag.Bool("demo", false, "render one frame and exit")
	flag.Parse()
	if *demo {
		fmt.Print(initialModel().View())
		return
	}
	if _, err := tea.NewProgram(initialModel(), tea.WithAltScreen()).Run(); err != nil {
		fmt.Fprintf(os.Stderr, "terminal interface failed: %v\n", err)
		os.Exit(1)
	}
}
