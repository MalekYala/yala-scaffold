"""Shape-specific configuration for <name> (shape: game)."""

from __future__ import annotations

from config import Field, as_int

FIELDS: list[Field] = [
    Field(
        "GODOT_BIN",
        "Path to the Godot binary. The container image provides one; set this only when running on the host.",
        default="godot",
        section="Engine",
    ),
    Field(
        "GAME_SEED",
        "Default simulation seed. Fixed by default so a fresh run is reproducible — randomise it per match, not per launch.",
        cast=as_int,
        default=12345,
        section="Simulation",
    ),
    Field(
        "SIM_TICK_RATE",
        "Fixed simulation steps per second. Must stay constant: a variable step makes the simulation non-reproducible, which breaks replays, netcode rollback and save compatibility.",
        cast=as_int,
        default=60,
    ),
    Field(
        "FRAME_BUDGET_MS",
        "Milliseconds a single simulation tick may take before the check fails. Simulation only — rendering has its own budget on top.",
        default="4.0",
    ),
]
