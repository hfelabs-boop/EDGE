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

import pytest

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


@pytest.mark.xfail(reason="P1, P4a and P4b replace the remaining native dialogs; the lead makes this required (SPEC §7.8)",
                   strict=False)
def test_no_native_dialogs():
    hits = []
    for f in _js_files():
        for n, line in enumerate(f.read_text().splitlines(), 1):
            if NATIVE.search(line.split("//")[0]):
                hits.append(f"{f.name}:{n}")
    assert not hits, hits


@pytest.mark.xfail(reason="the owning packages replace emoji with icons; the lead makes this required (SPEC §7.8)",
                   strict=False)
def test_no_emoji_in_static_files():
    hits = [f"{f.name}:{n}" for f in sorted(STATIC.iterdir()) if f.suffix in (".js", ".css", ".html")
            for n, line in enumerate(f.read_text().splitlines(), 1) if EMOJI.search(line)]
    assert not hits, hits


# P1 makes its own files pass the native-dialog and emoji checks now (the lead makes the whole-folder checks required)
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
