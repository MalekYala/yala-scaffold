extends RefCounted
class_name Sim

## Deterministic game simulation for <name>.
##
## Separated from rendering and input on purpose. A simulation that can only be
## advanced by a running game loop cannot be tested, replayed, or verified —
## and "deterministic" then means "we hope so".
##
## The contract this holds: [b]the same seed and the same inputs must always
## produce the same state[/b]. Replays, netcode rollback, and save compatibility
## all rest on it, and it breaks silently — the game still runs, it just
## diverges. Normal tests never catch it because they only run once.

const ARENA_SIZE := Vector2(640, 360)
const ENTITY_COUNT := 24

var rng := RandomNumberGenerator.new()
var tick: int = 0
var entities: Array[Dictionary] = []
var score: int = 0


func _init(seed_value: int = 0) -> void:
	reset(seed_value)


func reset(seed_value: int) -> void:
	rng = RandomNumberGenerator.new()
	rng.seed = seed_value
	tick = 0
	score = 0
	entities.clear()
	for i in ENTITY_COUNT:
		entities.append({
			"id": i,
			"pos": Vector2(rng.randf() * ARENA_SIZE.x, rng.randf() * ARENA_SIZE.y),
			"vel": Vector2(rng.randf_range(-60, 60), rng.randf_range(-60, 60)),
			"alive": true,
		})


## Advance one fixed step. `input` is the player's action for this tick.
func step(delta: float, input: Dictionary = {}) -> void:
	tick += 1
	var thrust: Vector2 = input.get("thrust", Vector2.ZERO)

	for entity in entities:
		if not entity["alive"]:
			continue
		entity["vel"] += thrust * delta
		entity["pos"] += entity["vel"] * delta
		# Bounce, rather than wrap: wrapping hides position drift, bouncing
		# amplifies it, which makes a determinism break visible sooner.
		if entity["pos"].x < 0 or entity["pos"].x > ARENA_SIZE.x:
			entity["vel"].x = -entity["vel"].x
			entity["pos"].x = clampf(entity["pos"].x, 0, ARENA_SIZE.x)
		if entity["pos"].y < 0 or entity["pos"].y > ARENA_SIZE.y:
			entity["vel"].y = -entity["vel"].y
			entity["pos"].y = clampf(entity["pos"].y, 0, ARENA_SIZE.y)

	if tick % 30 == 0 and entities.size() > 0:
		var victim: int = rng.randi() % entities.size()
		if entities[victim]["alive"]:
			entities[victim]["alive"] = false
			score += 10


## A stable fingerprint of the whole simulation state.
##
## Positions are quantised before hashing: floating-point noise below what any
## player could perceive would otherwise report a false divergence, and a
## determinism check that cries wolf gets deleted.
func state_hash() -> String:
	var parts: Array[String] = ["t=%d" % tick, "s=%d" % score]
	for entity in entities:
		parts.append("%d:%d:%d:%d" % [
			entity["id"],
			roundi(entity["pos"].x * 100.0),
			roundi(entity["pos"].y * 100.0),
			1 if entity["alive"] else 0,
		])
	return ",".join(parts).sha256_text()


func alive_count() -> int:
	var n := 0
	for entity in entities:
		if entity["alive"]:
			n += 1
	return n
