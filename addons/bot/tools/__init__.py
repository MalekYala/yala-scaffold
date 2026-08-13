# Bot tools for <name>.
#
# Each submodule exposes:
#   NAME        — string, used in the tool spec sent to the LLM
#   DESCRIPTION — string, shown to the LLM so it knows when to call the tool
#   call(query: str, ctx: dict) -> str  — the actual implementation
#
# Tools are loaded by bot.py::load_tools() based on the `tools:` list in
# bot/config.yml. A tool is skipped if its `requires_env` entries in config
# are missing from the environment at startup.
