"""Static checks of the builder's UI contract (docs: the redesign spec, §6 compatibility map and §7.3–§7.5).

The builder is plain files in edge/builder/static/ (no build step): these tests read them as text. They guard what
the parallel packages rely on: the page skeleton and its ids, the script and stylesheet order, a flat folder, the
names other modules, tutorials and tests call, the EDGE and ui contracts, and the design-system rules (no
color-mix, no native dialogs, no emoji). The last two start as expected failures until the lead makes them
required at integration.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "edge" / "builder" / "static"
HTML = (STATIC / "index.html").read_text()


def _js_files() -> list[Path]:
    return sorted(STATIC.glob("*.js"))


def _all_js() -> str:
    return "\n".join(f.read_text() for f in _js_files())


# §7.3: the skeleton (created in index.html; modules fill them)
SKELETON_IDS = """
app appbar logo docname filename filepath btn-save dirty save-label ws-nav nav-build btn-measures nav-test badge-test
nav-run badge-run nav-data badge-data btn-undo btn-redo try-split btn-try btn-try-menu assistant-toggle btn-help btn-more
banner proposal-bar body ws-home home-describe home-start home-list home-learn ws-build sidebar sidebar-tabs side-add
palette-filter palette side-files files side-devices btn-add-device devices btn-scan scan-results rail center
build-toolbar view-switch crumbs story-density est btn-settings btn-add-screen btn-try-screen preview-big btn-view-done
flowstrip canvas view-story flow view-screen preview-wrap preview preview-html preview-play preview-t preview-label
row-stepper stage-hint splitter timeline view-list list-editor view-diagram diagram view-source yaml btn-apply-yaml
inspector props-title props props-foot ws-measures ws-test test-ready test-check test-try test-run-card btn-dryrun
test-results test-devices ws-run ws-data data-sessions data-detail companion companion-tabs companion-tab-props
companion-tab-assistant companion-tab-help companion-close assistant-panel help-panel statusbar btn-validate sb-estimate
sb-test sb-devices sb-tutorial sb-saved btn-mode sb-palette menu-experiment btn-new btn-open menu-recent btn-import
menu-save menu-save-copy btn-versions btn-bundle menu-settings menu-yaml menu-copy-path menu-home menu-more modal
modal-body dialogs toast sr-live play
""".split()

SCRIPTS = ["icons.js", "ui.js", "app.js", "build.js", "inspector.js", "simple.js", "survey.js", "widgets.js", "stage.js",
           "measures.js", "assistant.js"]
STYLES = ["tokens.css", "components.css", "style.css", "build.css", "pages.css", "assistant.css"]

# §6.3 and §6.6: functions other modules, tests, tutorials and the MCP docs call by name
KEPT_FUNCTIONS = """
renderStoryboard openWizard tryIt runDialog addTrialColumn drawScreen setMode stageInput openAssetPicker drawStageOverlay
uploadAsset toggleBigPreview openMeasures monitorView recordingSummary preflightBox crashBox computerCheckBox api commit
undo redo renderAll normalize walkFlow getNode parentOf routineOfNode validate scheduleValidate save openFile loadDoc
showTab openModal closeModal helpLink md openHelp startTutorial checkTutorial tutorialCheck dryRun renderResults renderData
exportData versionsDialog importFiles welcome renderTimeline renderPreview renderProps renderPalette renderDevices
renderDiagram openScreen newRoutine addComponent selectComp flowInsertMenu nodeMenu moveFlowNode describeRoutine
screenSummary thumbTime sampleRowFor field startPlay stopPlay startRun createFromWizard drawMeasures openSurveyEditor
openLibrary scanHardware deviceMenu renderBuild icon ic
""".split()
KEPT_CONSTS = ["S", "h", "$", "clone", "toast", "comps", "findComp", "EDGE", "ui", "EDGE_ICONS", "TUTORIAL_CHECKS"]

EDGE_MEMBERS = """
on emit go ws setView select reveal pulse doc path snapshot historyIndex replaceDoc undoIf save ensurePath newExperiment
isFresh focus issues fmt proposal companion palette prefs toast announce
""".split()
UI_MEMBERS = "dialog confirm prompt menu popover toast seg switch announce trapFocus slug".split()


def test_skeleton_ids_exist():
    all_ids = re.findall(r'\sid="([\w-]+)"', HTML)
    missing = [i for i in SKELETON_IDS if i not in all_ids]
    assert not missing, f"index.html lost contract ids: {missing}"
    dupes = sorted({i for i in all_ids if all_ids.count(i) > 1})
    assert not dupes, f"duplicate ids in index.html: {dupes}"


def test_tutorial_selectors_keep_their_markup():
    # §6.1: exact markup the tutorials and test_novice rely on
    assert re.search(r'<button[^>]*id="btn-add-screen"[^>]*class="[^"]*\brtab add\b', HTML)
    assert 'data-tab="source" class="expert-only"' in HTML
    assert re.search(r'<a id="nav-data"[^>]*data-tab="data"', HTML)
    assert "/assets/edge-icon.svg" in HTML and "/assets/edge-48.png" in HTML
    assert '<body class="mode-simple">' in HTML


def test_script_and_stylesheet_order():
    scripts = re.findall(r'<script src="/static/([\w.-]+)"></script>', HTML)
    assert scripts == SCRIPTS, scripts
    styles = re.findall(r'<link rel="stylesheet" href="/static/([\w.-]+)">', HTML)
    assert styles == STYLES, styles


def test_static_folder_is_flat_and_complete():
    # pyproject packages static/* and the PyInstaller spec builder/static/*: no sub-folders
    assert all(p.is_file() for p in STATIC.iterdir()), [p.name for p in STATIC.iterdir() if not p.is_file()]
    for name in SCRIPTS + STYLES:
        assert (STATIC / name).is_file(), name


def test_every_static_file_says_what_it_owns():
    for f in list(STATIC.glob("*.js")) + list(STATIC.glob("*.css")):
        head = f.read_text()[:400]
        assert head.lstrip().startswith("/*") and "Owner" in head or f.name in ("survey.js", "measures.js"), \
            f"{f.name} should start with a comment naming what it owns"


def test_kept_functions_and_globals_exist():
    js = _all_js()
    missing = [fn for fn in KEPT_FUNCTIONS if not re.search(rf"\bfunction {re.escape(fn)}\s*\(", js)]
    assert not missing, f"functions other code calls by name are gone: {missing}"
    for name in KEPT_CONSTS:
        assert re.search(rf"^(const|let) {re.escape(name)}(?![\w$])", js, re.M), name


def test_no_global_declared_twice():
    # classic scripts share one global scope: a second const/let/class of the same name stops the page from loading
    seen: dict[str, str] = {}
    clashes = []
    functions: dict[str, list[str]] = {}
    for f in _js_files():
        for kind, name in re.findall(r"^(?:async\s+)?(const|let|var|class|function)\s+([A-Za-z_$][\w$]*)", f.read_text(), re.M):
            if kind == "function":
                functions.setdefault(name, []).append(f.name)
                continue
            if name in seen:
                clashes.append(f"{name}: {seen[name]} and {f.name}")
            seen[name] = f.name
    clashes += [f"{n}: const and function" for n in functions if n in seen]
    # a function declared in two files silently resolves to the later one; the only known case is SPEC §7.6 playSound
    twice = {n: fs for n, fs in functions.items() if len(fs) > 1 and n != "playSound"}
    assert not clashes and not twice, (clashes, twice)


def test_edge_and_ui_contracts():
    app = (STATIC / "app.js").read_text()
    block = app[app.index("const EDGE = "):]
    for m in EDGE_MEMBERS:
        assert re.search(rf"\b{m}\s*(\(|:|,)", block), f"EDGE.{m} is missing"
    for m in ("start", "apply", "discard", "active", "open", "close", "toggle", "isOpen", "current", "register", "setFallback", "get", "set"):
        assert re.search(rf"\b{m}\s*\(", block), m
    uijs = (STATIC / "ui.js").read_text()
    ret = uijs[uijs.rindex("return {"):]
    for m in UI_MEMBERS:
        assert re.search(rf"\b{m}\b", ret), f"ui.{m} is missing"


def test_no_color_mix_in_css():
    # older Chromium builds on lab computers lack color-mix(); every tint is a token (SPEC §3.1)
    bad = [f.name for f in STATIC.glob("*.css") if "color-mix(" in f.read_text()]
    assert not bad, bad


def test_tokens_define_light_dark_and_legacy_aliases():
    tokens = (STATIC / "tokens.css").read_text()
    for name in ("--canvas", "--surface-1", "--accent", "--assistant", "--cat-show-tint", "--loop-tint", "--z-play",
                 "--bg", "--panel", "--muted", "--mono"):
        assert f"{name}:" in tokens, name
    assert '@media (prefers-color-scheme: dark)' in tokens and ':root[data-theme="dark"]' in tokens
    assert tokens.count("--surface-1:#161A20") == 2      # the DARK block appears twice, verbatim


NATIVE = re.compile(r"(?<![\w.$])(prompt|confirm|alert)\s*\(|\bwindow\s*\.\s*(prompt|confirm|alert)\s*\(")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def test_no_native_dialogs():
    """Required since integration (SPEC §7.8): every package uses ui.dialog / ui.confirm / ui.prompt."""
    hits = []
    for f in _js_files():
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if NATIVE.search(line.split("//")[0]):
                hits.append(f"{f.name}:{n}")
    assert not hits, hits


def test_no_emoji_in_static_files():
    """Required since integration (SPEC §7.8): icons come from icons.js, never emoji or dingbat glyphs."""
    hits = [f"{f.name}:{n}" for f in sorted(STATIC.iterdir()) if f.suffix in (".js", ".css", ".html")
            for n, line in enumerate(f.read_text().splitlines(), 1) if EMOJI.search(line)]
    assert not hits, hits


# P1's own files (kept as a narrower check; the whole-folder checks above are required too)
P1_FILES = ["app.js", "ui.js", "icons.js", "index.html", "style.css", "components.css", "tokens.css"]


def test_shell_files_use_no_native_dialogs_or_emoji():
    hits = []
    for name in P1_FILES:
        for n, line in enumerate((STATIC / name).read_text().splitlines(), 1):
            if name.endswith(".js") and NATIVE.search(line.split("//")[0]):
                hits.append(f"{name}:{n} native dialog")
            if EMOJI.search(line):
                hits.append(f"{name}:{n} emoji")
    assert not hits, hits


def test_shell_keeps_the_redesign_hooks():
    app = (STATIC / "app.js").read_text()
    # §6.2: the new tutorial checks; §6.1: the coach's reveal rules; §2.5: hash routes and the S.tab shim
    for key in ("workspace:", "view:", "assistant_open:", "assistant_applied:"):
        assert key in app[app.index("const TUTORIAL_CHECKS"):], key
    assert "const TOUR_REVEAL" in app and "function routeFromHash" in app and "function showTab" in app
    # §2.3, §2.4: the status bar test chip and its "Test now" link, the recording pill, the palette hint
    for token in ("sb-test-now", "badge-run", "sb-recording", "sb-palette", "/api/runs"):
        assert token in app or token in HTML, token
    # §2.7: Import, History and Share are in the Experiment menu in both modes
    menu = HTML[HTML.index('id="menu-experiment"'):HTML.index('id="menu-more"')]
    for item in ("btn-import", "btn-versions", "btn-bundle", "btn-new", "btn-open"):
        tag = re.search(rf'<button id="{item}"[^>]*>', menu).group(0)
        assert "expert-only" not in tag, item


def test_every_tutorial_check_of_the_builder_is_a_known_check_type():
    """A tutorial step may only use checks the builder evaluates (TUTORIAL_CHECKS) and that
    edge.help.validate_tutorial accepts (CHECK_TYPES): the two lists name the same keys (UI spec §6.2)."""
    from edge.help import CHECK_TYPES
    app = (STATIC / "app.js").read_text()
    block = app[app.index("const TUTORIAL_CHECKS = {"):]
    block = block[:block.index("\n};")]
    keys = set(re.findall(r"^  ([a-z_]+):", block, re.M))
    assert keys == CHECK_TYPES, (keys ^ CHECK_TYPES)


# ---------------------------------------------------------------- P5: tutorials, docs, screenshots (SPEC §6.1, §7.2)
ROOT = STATIC.parents[2]
DOCS = ROOT / "docs"


def _tutorials():
    from edge.help import tutorials
    return tutorials()


def test_every_tutorial_target_names_the_redesigned_ui():
    """Targets point at the new UI (§6.1): no retired container (#console, #left, #right, #routine-tabs, the old
    tabs), and an id the coach cannot reveal must be one the page always shows or one a step before it opens."""
    retired = ["#console", "#left", "#right", "#layout", "#topbar", "#routine-tabs", "#routine-area", "#flow-area",
               "#tab-issues", "#tab-results", "#tab-hardware", "#tab-data", "#btn-run", "#issue-count"]
    for tut in _tutorials():
        for st in tut["steps"]:
            target = st.get("target") or ""
            assert not any(re.search(re.escape(r) + r"(?![\w-])", target) for r in retired), (tut["id"], target)


def test_the_assistant_tutorial_works_without_a_model():
    """§7.2 P5: tutorial 10's required steps only open the panel, the settings and the privacy note; the one step
    that needs a model (assistant_applied) says to skip it, so the tutorial can be finished offline."""
    tut = next(t for t in _tutorials() if t["id"] == "assistant_basics")
    checks = [st.get("check") or {} for st in tut["steps"]]
    assert {"assistant_open": True} in checks
    needs_model = [st for st in tut["steps"] if "assistant_applied" in (st.get("check") or {})]
    assert len(needs_model) == 1 and "skip" in needs_model[0]["body"].lower()
    assert all(set(c) <= {"assistant_open", "assistant_applied"} for c in checks), "a step needs more than the panel"
    targets = " ".join(st.get("target") or "" for st in tut["steps"])
    for stable in ("#assistant-toggle", "#assistant-settings", "#assistant-input"):     # §7.4 stable ids
        assert stable in targets, stable


def test_every_tutorial_has_a_playwright_run():
    """tools/ui_check/tutorials.js plays every tutorial end to end; it must know each one (by id)."""
    runner = (ROOT / "tools" / "ui_check" / "tutorials.js").read_text()
    for tut in _tutorials():
        assert re.search(rf"^  {tut['id']}: \[", runner, re.M), f"tools/ui_check/tutorials.js doesn't play {tut['id']}"


def test_documentation_screenshots_are_1440_by_900():
    """§7.2 P5: docs/*.png are taken by tools/ui_check/screenshots.js at 1440 × 900 (light)."""
    import struct
    for name in ("builder", "wizard", "workflow", "survey_editor", "assistant"):
        data = (DOCS / f"{name}.png").read_bytes()[:24]
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name
        assert struct.unpack(">II", data[16:24]) == (1440, 900), name
        assert name in (ROOT / "tools" / "ui_check" / "screenshots.js").read_text(), name


# ---------------------------------------------------------------- QA round 2 (static checks of the fixes)
def _src(name: str) -> str:
    return (STATIC / name).read_text()


def _fn(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    m = re.search(r"\n(?:async )?function \w+\(|\n/\* =+|\n(?:const|let) \w+ = ", src[i + 10:])
    return src[i: i + 10 + (m.start() if m else len(src))]


def test_drawing_a_device_never_writes_to_the_document():
    """inspector.js used `d.options ||= {}` while drawing: the YAML got `options: {}` and 'Tested' was lost."""
    src = _src("inspector.js")
    assert "d.options ||= {};" not in src and "const opts = d.options || {};" in src


def test_try_it_and_test_run_ask_about_unread_assistant_code_first():
    app, simple, asst = _src("app.js"), _src("simple.js"), _src("assistant.js")
    assert "if (!(await assistantCodeGate())) return;" in _fn(app, "dryRun")
    assert "assistantCodeGate()" in _fn(simple, "startPlay") and "r.unread_code" in _fn(simple, "startPlay")
    assert "reviewed_code: reviewedCodeHashes()" in _fn(app, "dryRun")
    gate = _fn(app, "assistantCodeGate")
    assert "Review it" in gate and "I've read it" in gate and "/api/assistant/reviewed" in gate
    # the panel merges what the server knows, and "I've read it" is stored next to the experiment
    assert "/api/assistant/code?exp=" in asst and '"/api/assistant/reviewed"' in _fn(asst, "markReviewed")
    assert "serverCode.written" in _fn(asst, "unreviewedCode")


def test_try_it_toast_and_data_alerts_use_builder_words():
    simple, app = _src("simple.js"), _src("app.js")
    assert "Try it couldn't start: ${builderWords(" in simple
    assert "(OK|WARNING|ERROR|COMPUTER|NOTE)" in app and "cap(builderWords(v.replace(" in app


def test_try_it_end_panel_does_not_restart_on_the_participants_last_key():
    fin = _fn(_src("simple.js"), "finishPlay")
    assert 'end.querySelector(".pe-title")?.focus()' in fin and "again.focus()" not in fin
    assert "e.detail === 0 && Date.now() - endedAt < 1000" in fin


def test_tested_and_tried_are_restored_with_their_time():
    app = _src("app.js")
    rt = _fn(app, "restoreTested")
    assert "r.tried" in rt and "S.triedAt" in rt
    assert "S.tested?.restored ? clock(S.tested.at) : ago(S.tested?.at)" in app


def test_save_a_copy_takes_its_files_and_is_checked_again():
    save = _fn(_src("app.js"), "save")
    assert "&copy_from=" in save and "if (newPath) validate();" in save and "S.exp.name = slug" in save


def test_sessions_of_a_sibling_experiment_are_not_ours():
    body = _fn(_src("app.js"), "sessionBelongs")
    assert "f.name === s.experiment" in body


def test_list_footer_for_a_loop_without_rows():
    assert "(no rows: the screens just repeat)" in _src("build.js")


def test_timeline_names_give_way_last():
    css = _src("components.css")
    assert re.search(r"\.timeline \.tl-label b \{[^}]*flex: 0 0 auto; max-width: 60%", css)
    assert re.search(r"\.timeline \.tl-label span \{[^}]*flex: 1 1 0; min-width: 0", css)


def test_breadcrumb_focus_ring_is_inset():
    assert re.search(r"#crumbs \.crumb:focus-visible \{[^}]*outline-offset: -2px", _src("build.css"))


def test_position_grid_is_one_radio_group():
    pg = _fn(_src("widgets.js"), "placeGrid")
    assert 'role: "radiogroup"' in pg and 'role: "radio"' in pg and "aria-checked" in pg and "aria-pressed" not in pg
    assert "ArrowRight" in pg and "Home" in pg and "End" in pg and "tabIndex = k === j ? 0 : -1" in pg


def test_backspace_never_deletes_from_a_menu_and_never_adds_a_key():
    app, insp = _src("app.js"), _src("inspector.js")
    on = _fn(app, "onKey")
    assert '.menu, [role=menu], [role=listbox], .popover' in on
    kc = _fn(insp, "inspKeyChips")
    assert 'e.key === "Backspace" || e.key === "Delete"' in kc and "e.stopPropagation()" in kc


def test_focus_returns_to_the_card_or_page_after_leaving_a_view():
    app, build = _src("app.js"), _src("build.js")
    assert "subViewReturnKey(S.view)" in app and "BUILD.forceFocus" in _fn(build, "buildFocusFallback")
    assert "focusWorkspace(ws);" in app and 'page.querySelector("h1")' in _fn(app, "focusWorkspace")
    assert 'leaveSubView("story")' in _fn(build, "timelineKeys")         # Esc on a timeline row goes up
    scan = _fn(build, "scanHardware")
    assert "ui.announce(found.length" in scan and ".focus(" in scan


def test_coach_shrinks_only_for_real_controls_and_never_covers_a_menu():
    app = _src("app.js")
    place = _fn(app, "placeCoach")
    assert "overlap(cand[0].x, cand[0].y, 5)" in place and "#canvas" in place
    assert '[".menu", 8]' in app
    assert re.search(r"\.menu \{ position: fixed; z-index: calc\(var\(--z-coach\) \+ 1\)", _src("components.css"))
    assert "function isFullyInView(" in app and "coachScroll(st)" in _fn(app, "checkTutorial")
    assert 'EDGE.companion.current() === "assistant"' in app and "dialogUp" in _fn(app, "updateCoach")


def test_tutorial_steps_that_end_on_a_result_wait_for_next():
    """The explanation of a test run or of the YAML must stay until the researcher presses Next or Finish."""
    tuts = {t["id"]: t for t in _tutorials()}
    for tid in ("eyetracking", "html_questionnaire", "rules_and_feedback", "data_and_export"):
        assert tuts[tid]["steps"][-1].get("advance") == "manual", tid
    rules = tuts["rules_and_feedback"]["steps"]
    assert "replace `$t > 1`" in rules[2]["body"] and rules[2]["check"]["rule"]["valid"] is True
    assert rules[1]["target"] == "#props [data-fkey='rule:add']" and rules[4]["target"].startswith("#props [data-prop=if]")
    assert tuts["eyetracking"]["steps"][4]["target"] == "#props [data-prop=marker]"
    assert "`<>`" in tuts["data_and_export"]["steps"][-1]["body"]
    assert tuts["trial_lists"]["steps"][5]["target"] == "#btn-undo"


def test_reloaded_and_home_proposals_can_be_shown_again():
    asst = _src("assistant.js")
    assert "restoreProposal(m, path)" in _fn(asst, "loadTranscript")
    assert 'job.phase === "reloaded"' in asst and "Show again" in asst
    assert "HOME_PENDING" in _fn(asst, "buildIt") and "You have an unapplied design for" in asst


def test_try_one_screen_says_what_runs_and_in_words_names_unknown_results():
    build = _src("build.js")
    assert "function triedTogether(" in build and "tryOneLabel(rid)" in _src("app.js")
    assert "doesn't have" in _fn(build, "unknownResult") and "unknownResult(s)" in _fn(build, "exprInWords")


def test_preflight_words_for_devices_and_the_verdict():
    m = _src("measures.js")
    assert '"no-go": "Not ready yet"' in m and "NO-GO" not in m
    assert "not answering" in _fn(m, "pfItemText")
