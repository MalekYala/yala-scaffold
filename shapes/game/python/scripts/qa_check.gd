extends SceneTree

## Headless contract check for <name>. Emits one JSON object on stdout.
##
## Run by `qa_check.py`, which parses the JSON and applies the kit's usual
## reporting. Everything here runs with no window, no GPU and no input, which
## is what lets a game be checked on every commit rather than by someone
## remembering to play it.
##
## The checks are engine-independent in intent; only their implementation is
## Godot-specific. Porting to Unity means running the same questions through
## EditMode/PlayMode tests — see docs/USAGE.md.

const SIM_TICKS := 600  # 10 seconds at 60Hz
const FRAME_BUDGET_MS := 4.0

## Loaded by path rather than by its global `class_name`.
##
## Global class names come from Godot's script cache, which only exists after
## the project has been imported. A fresh clone has no `.godot/` directory, so
## a check that relies on `Sim` being registered fails on exactly the run that
## matters most: the first one, in CI.
const SimScript := preload("res://scripts/sim.gd")


func _init() -> void:
	var checks: Array[Dictionary] = []

	# ── 1. The project and its declared entry point exist ──────────────────
	var main_scene: String = ProjectSettings.get_setting("application/run/main_scene", "")
	checks.append({
		"name": "main_scene_declared",
		"ok": main_scene != "" and ResourceLoader.exists(main_scene),
		"detail": ("main scene: %s" % main_scene) if main_scene != "" else
			"application/run/main_scene is unset — the game has no entry point",
	})

	# ── 2. Every scene loads ───────────────────────────────────────────────
	# A broken ext_resource is the classic silent breakage: the file still
	# parses, the editor still opens, and the node is simply missing at run
	# time. Loading each scene is the only way to find it without playing.
	var scenes := _find_files("res://", ".tscn")
	var broken_scenes: Array[String] = []
	for path in scenes:
		var packed := ResourceLoader.load(path)
		if packed == null:
			broken_scenes.append(path)
	checks.append({
		"name": "scenes_load",
		"ok": scenes.size() > 0 and broken_scenes.is_empty(),
		"detail": ("%d scene(s) load" % scenes.size()) if broken_scenes.is_empty()
			else "failed to load: %s" % str(broken_scenes),
	})

	# ── 3. Every referenced resource exists ────────────────────────────────
	# Catches a renamed or deleted asset that nothing has loaded yet.
	var missing := _missing_resource_refs(scenes)
	checks.append({
		"name": "resources_resolve",
		"ok": missing.is_empty(),
		"detail": "every res:// reference resolves" if missing.is_empty()
			else "dangling reference(s): %s" % str(missing),
	})

	# ── 4. Every script compiles ───────────────────────────────────────────
	var scripts := _find_files("res://", ".gd")
	var broken_scripts: Array[String] = []
	for path in scripts:
		var script := ResourceLoader.load(path)
		if script == null or not (script as GDScript).can_instantiate():
			broken_scripts.append(path)
	checks.append({
		"name": "scripts_compile",
		"ok": scripts.size() > 0 and broken_scripts.is_empty(),
		"detail": ("%d script(s) compile" % scripts.size()) if broken_scripts.is_empty()
			else "failed: %s" % str(broken_scripts),
	})

	# ── 5. The simulation actually does something ──────────────────────────
	# A sim that advances and changes nothing would pass a determinism check
	# perfectly — two identical runs of nothing are still identical. Reporting
	# that as success is the vacuous pass this kit refuses everywhere.
	var probe := SimScript.new(7)
	var before := probe.state_hash()
	for i in SIM_TICKS:
		probe.step(1.0 / 60.0, {})
	var after := probe.state_hash()
	checks.append({
		"name": "simulation_advances",
		"ok": before != after and probe.tick == SIM_TICKS,
		"detail": "%d ticks, state changed, %d/%d entities alive" % [
			probe.tick, probe.alive_count(), probe.entities.size(),
		] if before != after else
			"state is identical after %d ticks — the simulation is not running" % SIM_TICKS,
	})

	# ── 6. Determinism ─────────────────────────────────────────────────────
	# The same seed and inputs must produce the same state. Replays, netcode
	# rollback and save compatibility all rest on this, and it breaks silently:
	# the game still runs, it just diverges.
	var hashes: Array[String] = []
	for run in 3:
		var sim := SimScript.new(99)
		for i in SIM_TICKS:
			sim.step(1.0 / 60.0, {"thrust": Vector2(1, 0) if i % 7 == 0 else Vector2.ZERO})
		hashes.append(sim.state_hash())
	var deterministic := hashes[0] == hashes[1] and hashes[1] == hashes[2]
	checks.append({
		"name": "deterministic",
		"ok": deterministic,
		"detail": "3 runs of %d ticks agree (%s)" % [SIM_TICKS, hashes[0].substr(0, 12)]
			if deterministic else
			"same seed diverged across runs: %s — replays and netcode cannot work" % str(hashes),
	})

	# ── 7. Different seeds must actually differ ────────────────────────────
	# Otherwise the seed is being ignored and every "random" game is identical,
	# which check 6 would happily call deterministic.
	var seed_a := SimScript.new(1)
	var seed_b := SimScript.new(2)
	for i in 120:
		seed_a.step(1.0 / 60.0, {})
		seed_b.step(1.0 / 60.0, {})
	checks.append({
		"name": "seed_matters",
		"ok": seed_a.state_hash() != seed_b.state_hash(),
		"detail": "different seeds produce different games" if seed_a.state_hash() != seed_b.state_hash()
			else "seeds 1 and 2 produced identical state — the seed is being ignored",
	})

	# ── 8. Frame budget ────────────────────────────────────────────────────
	var budget_sim := SimScript.new(3)
	var started := Time.get_ticks_usec()
	for i in SIM_TICKS:
		budget_sim.step(1.0 / 60.0, {})
	var per_tick_ms := float(Time.get_ticks_usec() - started) / float(SIM_TICKS) / 1000.0
	checks.append({
		"name": "frame_budget",
		"ok": per_tick_ms < FRAME_BUDGET_MS,
		"detail": "%.3f ms/tick (budget %.1f)" % [per_tick_ms, FRAME_BUDGET_MS]
			+ ("" if per_tick_ms < FRAME_BUDGET_MS else
			   " — simulation alone exceeds the budget, before any rendering"),
	})

	var status := "ok"
	for check in checks:
		if not check["ok"]:
			status = "fail"

	print(JSON.stringify({
		"status": status,
		"checks": checks,
		"per_tick_ms": per_tick_ms,
	}))
	quit(0 if status == "ok" else 1)


func _find_files(root: String, suffix: String) -> Array[String]:
	var found: Array[String] = []
	var dir := DirAccess.open(root)
	if dir == null:
		return found
	dir.list_dir_begin()
	var entry := dir.get_next()
	while entry != "":
		if entry.begins_with("."):
			entry = dir.get_next()
			continue
		var full := root.path_join(entry)
		if dir.current_is_dir():
			found.append_array(_find_files(full, suffix))
		elif entry.ends_with(suffix):
			found.append(full)
		entry = dir.get_next()
	dir.list_dir_end()
	return found


## Every `res://` path mentioned in a scene file that does not exist on disk.
func _missing_resource_refs(scenes: Array[String]) -> Array[String]:
	var missing: Array[String] = []
	var pattern := RegEx.new()
	pattern.compile('path="(res://[^"]+)"')
	for scene_path in scenes:
		var file := FileAccess.open(scene_path, FileAccess.READ)
		if file == null:
			continue
		var text := file.get_as_text()
		file.close()
		for match in pattern.search_all(text):
			var referenced := match.get_string(1)
			if not ResourceLoader.exists(referenced) and not FileAccess.file_exists(referenced):
				missing.append("%s -> %s" % [scene_path, referenced])
	return missing
