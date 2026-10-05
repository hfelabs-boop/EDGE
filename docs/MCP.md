# Natural-language control with MCP (Claude, VS Code)

EDGE includes an [MCP](https://modelcontextprotocol.io) server. Connect it to Claude Code,
Claude Desktop, VS Code or any MCP client, and design, test and analyze experiments by describing
what you want:

> *"Create a flanker task with 4 blocks of 40 trials, F/J responses, a Gazepoint eye tracker and LSL
> markers on every stimulus onset. Add a practice block that repeats until accuracy is above 80%.
> Then dry-run it and show me the timing."*

The assistant turns this into tool calls (`create_experiment`, `edit_experiment`, `add_loop`,
`set_conditions`, `dry_run` …). Every edit is validated, saved atomically with a backup (so
**undo always works**) and shows up **live in the EDGE builder** if it's open.

## Setup

```bash
pip install -e ".[mcp]"        # or: pip install "edge-experiments[mcp]"
edge mcp --root path/to/experiments     # what clients launch (stdio)
```

The server only reads and writes inside `--root`.

### Claude Code
```bash
claude mcp add edge -- edge mcp --root .
```
Or rely on the `.mcp.json` in this repository (Claude Code asks you to approve it the first time):
```json
{ "mcpServers": { "edge": { "command": "edge", "args": ["mcp", "--root", "."] } } }
```

### VS Code (Copilot agent mode, or any MCP-capable extension)
`.vscode/mcp.json` (included in this repository):
```json
{ "servers": { "edge": { "type": "stdio", "command": "edge", "args": ["mcp", "--root", "${workspaceFolder}"] } } }
```
Open the Chat view in **Agent** mode; the EDGE tools appear in the tools picker.

### Claude Desktop
Settings → Developer → Edit config (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "edge": { "command": "edge", "args": ["mcp", "--root", "/Users/me/experiments"] }
  }
}
```
If `edge` isn't on the PATH Claude Desktop uses, give the full path to the executable, or use
`"command": "python", "args": ["-m", "edge", "mcp", "--root", "..."]`.

## Tools

| Area | Tools |
|---|---|
| Discover | `list_experiments`, `list_component_types`, `list_device_types`, `list_templates`, `scan_hardware` |
| Documents | `create_experiment`, `describe_experiment`, `get_experiment_source`, `replace_experiment_source` |
| Batch edit | `edit_experiment`: many operations, applied all-or-nothing |
| Routines | `add_routine`, `update_routine`, `remove_routine` |
| Components | `add_component`, `update_component`, `remove_component`, `move_component` |
| Flow | `add_loop`, `update_loop`, `set_conditions`, `add_branch`, `modify_flow` |
| Workflow logic | `add_workflow` (state machines), `update_workflow_state`, `add_routine_rule` |
| Import | `import_experiment`: PsychoPy, E-Prime, OpenSesame, jsPsych |
| Devices & settings | `add_device`, `update_device`, `remove_device`, `update_settings` |
| Test & run | `validate_experiment`, `dry_run`, `run_experiment`, `run_status` |
| Data | `list_sessions`, `analyze_session`, `export_data` |
| History & files | `undo`, `list_versions`, `restore_version`, `bundle_experiment`, `import_experiment_bundle`, `write_file` |
| Builder | `open_builder`: starts the visual builder and returns its URL |
| Help | `search_help`, `read_help`, `list_tutorials`: the documentation and cookbook, so the assistant can look things up instead of guessing |

**Resources:** `edge://docs/{name}` (any guide), `edge://docs/experiment-format`, `edge://docs/devices`, `edge://docs/data`,
`edge://templates/{name}`.

**Prompts:** `design_experiment` (paradigm → finished, dry-run-tested experiment),
`prepare_for_data_collection` (pre-flight checklist), `analyze_my_data`.

## How it stays safe

* **Workspace jail:** paths are resolved inside `--root`. The server won't write scripts or
  executables.
* **Validated edits:** unknown component types, properties, devices and options are rejected, and
  the error message lists the valid choices so the assistant can correct itself.
* **All-or-nothing batches:** if any operation in `edit_experiment` fails, the file is left untouched.
* **Backups and undo:** every save keeps the previous version (`.edge/backups/`); `undo` and
  `restore_version` walk back through them.
* **No silent overwrites:** the builder detects edits made over MCP. If you have unsaved changes
  of your own, it asks which version to keep.
* **Real sessions only when asked:** `run_experiment` opens the experiment window and uses real
  hardware; the tool description tells the model to call it only on explicit request. `dry_run`
  is the default way to test.

## Example session

```
you:    Make an emotional Stroop with words from words.csv (columns word, valence), 2 blocks,
        Tobii eye tracker, 500 ms fixation, response keys d/k, feedback only in practice.
claude: create_experiment → edit_experiment (devices, routines, components) → add_loop × 2
        → add_branch → validate_experiment → dry_run
        "Built 'emo_stroop': practice (8 trials, feedback) → 2 blocks × 60 trials, ~11 min.
         Dry run OK: 0 dropped frames, Tobii markers 128/128 aligned, accuracy summary by valence attached."
you:    Make the fixation jittered between 400 and 600 ms.
claude: update_component(trial, fix, {"duration": "$random.uniform(0.4, 0.6)"})
you:    Undo that, use 300-700.
claude: undo → update_component(...)
```
