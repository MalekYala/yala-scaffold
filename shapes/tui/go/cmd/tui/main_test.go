package main

import (
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
)

func TestViewContainsProjectAndHelp(t *testing.T) {
	view := initialModel().View()
	if !strings.Contains(view, "<name>") {
		t.Fatal("view does not contain project name")
	}
	if !strings.Contains(view, "q quit") {
		t.Fatal("view does not contain keyboard help")
	}
}

func TestNavigationAndSelection(t *testing.T) {
	current := initialModel()
	updated, _ := current.Update(tea.KeyMsg{Type: tea.KeyDown})
	current = updated.(model)
	if current.cursor != 1 {
		t.Fatalf("cursor = %d, want 1", current.cursor)
	}

	updated, _ = current.Update(tea.KeyMsg{Type: tea.KeyEnter})
	current = updated.(model)
	if current.selected != menuItems[1] {
		t.Fatalf("selected = %q, want %q", current.selected, menuItems[1])
	}
}

func TestNavigationStaysWithinBounds(t *testing.T) {
	current := initialModel()
	updated, _ := current.Update(tea.KeyMsg{Type: tea.KeyUp})
	if updated.(model).cursor != 0 {
		t.Fatal("cursor moved above first item")
	}
}
