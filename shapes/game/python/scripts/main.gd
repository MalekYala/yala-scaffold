extends Node2D

## Entry scene for <name>.
##
## Owns rendering and input only. Every rule that decides what happens lives in
## [code]Sim[/code], which is why the game can be verified headlessly: this node
## is a view over a simulation that runs perfectly well without it.

const DOT_RADIUS := 4.0

## Loaded by path, not by global `class_name`: the class registry lives in
## Godot's script cache, which a fresh clone does not have until the project
## has been imported once.
const SimScript := preload("res://scripts/sim.gd")

var sim
var _score_label: Label


func _ready() -> void:
	# A fixed seed by default so a fresh run is reproducible. Pass --seed on the
	# command line, or set it from a lobby, for a varied game.
	var seed_value := 12345
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--seed="):
			seed_value = int(arg.split("=")[1])
	sim = SimScript.new(seed_value)
	_score_label = get_node_or_null("HUD/Score")
	print("[<name>] booted seed=%d entities=%d" % [seed_value, sim.entities.size()])


func _physics_process(delta: float) -> void:
	var thrust := Vector2(
		Input.get_axis("ui_left", "ui_right"),
		Input.get_axis("ui_up", "ui_down"),
	) * 120.0
	sim.step(delta, {"thrust": thrust})
	if _score_label:
		_score_label.text = "score: %d" % sim.score
	queue_redraw()


func _draw() -> void:
	# Drawn from simulation state, never from its own stored positions — a view
	# that keeps its own copy is a second source of truth waiting to disagree.
	for entity in sim.entities:
		if entity["alive"]:
			draw_circle(entity["pos"], DOT_RADIUS, Color(0.4, 0.8, 1.0))
