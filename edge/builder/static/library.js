/* library.js: the Task library dialog. Owner: task library (edge/library, edge/builder/library_api.py).
 * Ready-made classic tasks (Stroop, flanker, n-back …), each a complete, tested experiment with its own pictures and
 * sounds. Opened from Home (next to "Start from an example"), from the examples gallery and from Ctrl+K.
 * GET /api/library lists them (categories, cards: title, summary, duration, input, measures, references, a "see also
 * PsyToolkit" link); "Use this task" asks for a name, POST /api/library/new copies the task into this folder and opens
 * it; "Use and try it" does the same and starts Try it. Globals used: h, icon, ui, api, toast, countWord,
 * askExperimentName, confirmLeaveDirty, openFile, refreshFiles, tryIt, EDGE.
 * Operational adaptations (meta: domain, themes; docs/library/DEFENSE.md) have their own entry in the sidebar
 * ("Operational adaptations", with a theme filter), show their display themes as chips, and "Use this task" asks
 * which theme the copy starts in (POST {theme}, which sets the experiment's variable `theme`). A classic task's card
 * links to its operational version.
 */
"use strict";

const TASKLIB = {data: null, cat: "", q: "", theme: ""};
const TASKLIB_OPS = "__ops";        // the sidebar entry of the operational adaptations (not a category)
const TASKLIB_INPUT = {keyboard: "Keyboard", mouse: "Mouse", touch: "Touch screen", "keyboard+mouse": "Keyboard and mouse"};
const TASKLIB_ICON = {keyboard: "keyboard", mouse: "mouse", touch: "mouse", "keyboard+mouse": "keyboard"};

async function taskLibraryData(force = false) {
  if (!TASKLIB.data || force) TASKLIB.data = await api("/api/library");
  return TASKLIB.data;
}

/* The library dialog. opts.category opens one category. */
async function openTaskLibrary(opts = {}) {
  let data;
  try { data = await taskLibraryData(true); }
  catch (e) { return toast(`The task library couldn't be opened: ${e.message}`, {tone: "danger", ms: 8000}); }
  if (opts.category !== undefined) TASKLIB.cat = opts.category;
  let closeIt = () => {};
  const tasks = data.tasks || [];
  const themeTitle = Object.fromEntries((data.themes || []).map((x) => [x.id, x.title]));
  const ops = tasks.filter((t) => t.domain);
  const themeRow = h("div", {class: "tl-themes", role: "group", "aria-label": "Display theme"});
  const search = h("input", {class: "input", type: "search", placeholder: "Search: Stroop, memory, inhibition, touch…",
    "aria-label": "Search the task library", value: TASKLIB.q});
  const cats = h("nav", {class: "tl-cats", "aria-label": "Categories"});
  const grid = h("div", {class: "tl-grid", role: "list", "aria-label": "Tasks"});
  const count = h("p", {class: "t-caption tl-count", "aria-live": "polite"});
  const matches = (t, q) => {
    const hay = [t.id.replace(/_/g, " "), t.title, t.category, t.summary, t.description, t.input, t.adaptation || "",
      ...(t.themes || []).map((x) => themeTitle[x] || x), ...(t.measures || []), ...(t.references || [])].join(" ").toLowerCase();
    return q.split(/\s+/).filter(Boolean).every((w) => hay.includes(w));
  };
  // the sidebar's choice: a category, all tasks, or the operational adaptations (then optionally one theme)
  const inView = (t, c) => (c === TASKLIB_OPS ? !!t.domain && (!TASKLIB.theme || (t.themes || []).includes(TASKLIB.theme)) : (!c || t.category === c));
  const drawThemes = () => {
    themeRow.hidden = TASKLIB.cat !== TASKLIB_OPS;
    const b = (id, label) => h("button", {type: "button", class: "chip lg" + (TASKLIB.theme === id ? " accent" : " outline"), "aria-pressed": String(TASKLIB.theme === id),
      onclick: () => { TASKLIB.theme = id; drawThemes(); drawCards(); }}, label);
    themeRow.replaceChildren(h("span", {class: "t-caption"}, "Theme:"), b("", "All themes"), ...(data.themes || []).map((x) => b(x.id, x.title)));
  };
  // a classic task's "Operational version" link: show the adaptation's card
  const showTask = (id) => {
    TASKLIB.cat = TASKLIB_OPS; TASKLIB.theme = ""; TASKLIB.q = ""; search.value = "";
    drawCats(); drawThemes(); drawCards();
    const card = grid.querySelector(`[data-task="${id}"]`);
    if (card) { card.scrollIntoView({block: "nearest"}); card.querySelector("button")?.focus(); card.classList.add("tl-flash"); setTimeout(() => card.classList.remove("tl-flash"), 1600); }
  };
  const drawCats = () => {
    const q = TASKLIB.q.trim().toLowerCase();
    const n = (c) => tasks.filter((t) => inView(t, c) && (!q || matches(t, q))).length;
    const item = (c, label, extra = "") => h("button", {type: "button", class: "tl-cat" + extra + (TASKLIB.cat === c ? " on" : ""), "aria-pressed": String(TASKLIB.cat === c),
      onclick: () => { TASKLIB.cat = c; drawCats(); drawThemes(); drawCards(); }}, h("span", {}, label), h("span", {class: "t-caption"}, String(n(c))));
    cats.replaceChildren(item("", "All tasks"), ...(data.categories || []).filter((c) => c.count).map((c) => item(c.name, c.name)),
      ...(ops.length ? [item(TASKLIB_OPS, "Operational adaptations", " tl-cat-ops")] : []));
  };
  const drawCards = () => {
    const q = TASKLIB.q.trim().toLowerCase();
    const shown = tasks.filter((t) => inView(t, TASKLIB.cat) && (!q || matches(t, q)));
    grid.replaceChildren(...shown.map((t) => taskCard(t, () => closeIt(), {themeTitle, showTask})));
    if (!tasks.length) grid.append(h("p", {class: "tl-none t-2"}, "The task library is empty in this copy of EDGE."));
    else if (!shown.length) grid.append(h("p", {class: "tl-none t-2"}, q ? `Nothing called “${TASKLIB.q}”${TASKLIB.cat ? ` in ${TASKLIB.cat}` : ""}. Try another word.` : "No task in this category yet."));
    const where = TASKLIB.cat === TASKLIB_OPS ? ` (operational adaptations${TASKLIB.theme ? `, ${themeTitle[TASKLIB.theme]}` : ""})` : (TASKLIB.cat ? ` in ${TASKLIB.cat}` : "");
    count.textContent = tasks.length ? `${countWord(shown.length, "task")}${where}` : "";
  };
  search.oninput = () => { TASKLIB.q = search.value; drawCats(); drawCards(); };
  if (TASKLIB.cat === TASKLIB_OPS && !ops.length) TASKLIB.cat = "";
  drawCats(); drawThemes(); drawCards();
  const body = h("div", {class: "tl"},
    h("p", {class: "t-2 tl-intro"}, "Classic tasks, ready to run: instructions, practice, the main trials and a thank-you screen, with their measures. Each is EDGE's own version of the published method; use one, then change it as you like."),
    h("div", {class: "tl-main"}, cats, h("div", {class: "tl-right"}, h("div", {class: "input-wrap tl-search"}, icon("search", "lead"), search), themeRow, count, grid)));
  return ui.dialog({title: "Task library", icon: "book", size: "lg", body, initialFocus: search,
    buttons: [{label: "Close", value: null}], onOpen: (dlg, close) => { closeIt = close; dlg.classList.add("tl-dialog"); }});
}

function taskCard(t, close, {themeTitle = {}, showTask} = {}) {
  const facts = [t.category, `about ${t.duration_min} min`, TASKLIB_INPUT[t.input] || t.input, (t.languages || []).join(", ").toUpperCase()].filter(Boolean).join(" · ");
  const names = (list) => (list || []).map((x) => themeTitle[x] || x.toUpperCase());
  // operational adaptation: its themes as chips (the default first); classic task: a link to its operational version
  const themes = (t.themes || []).length ? h("div", {class: "tl-chips", "aria-label": "Display themes"},
    h("span", {class: "chip accent"}, "Operational"), ...names(t.themes).map((x) => h("span", {class: "chip outline"}, x))) : null;
  const opsLinks = (t.adaptations || []).map((a) => h("p", {class: "tl-ops t-small"}, h("button", {type: "button", class: "linkbtn",
    title: `${a.title}: the same paradigm with operator displays`, onclick: () => showTask?.(a.id)}, `Operational version: ${names(a.themes).join(" · ")}`)));
  const refs = t.references || [];
  const more = h("details", {class: "tl-more"}, h("summary", {}, "More: what it does, references"),
    h("p", {}, t.description || ""),
    t.adaptation ? h("p", {}, h("b", {}, "Operational adaptation: "), t.adaptation) : null,
    t.notes ? h("p", {class: "t-caption"}, t.notes) : null,
    refs.length ? h("p", {class: "t-overline tl-refs-head"}, "Please cite") : null,
    refs.length ? h("ul", {class: "tl-refs"}, refs.map((r) => h("li", {}, r))) : null);
  const psy = t.psytoolkit ? h("a", {class: "linkbtn tl-see", href: t.psytoolkit, target: "_blank", rel: "noopener noreferrer",
    title: "PsyToolkit's page about this paradigm (opens in your browser)"}, "See also PsyToolkit", icon("external")) : null;
  return h("article", {class: "card tl-card", role: "listitem", "aria-label": t.title, "data-task": t.id},
    h("div", {class: "tl-head"}, h("span", {class: "tile"}, icon(TASKLIB_ICON[t.input] || "storyboard", "m")),
      h("span", {class: "tl-title"}, h("h4", {}, t.title), h("span", {class: "t-caption"}, facts))),
    themes,
    h("p", {class: "tl-summary"}, t.summary),
    ...opsLinks,
    (t.measures || []).length ? h("p", {class: "tl-measures t-small"}, h("b", {}, "Measures: "), t.measures.join("; ")) : null,
    refs.length ? h("p", {class: "tl-cite t-caption"}, refs[0].length > 110 ? refs[0].slice(0, 107) + "…" : refs[0], refs.length > 1 ? ` (+${refs.length - 1} more)` : "") : null,
    more,
    h("div", {class: "tl-actions"},
      h("button", {type: "button", class: "btn sm primary", "aria-label": `Use ${t.title}`, onclick: () => { close(); useLibraryTask(t, {tryIt: false}); }}, icon("plus"), "Use this task"),
      h("button", {type: "button", class: "btn sm", "aria-label": `Use and try ${t.title}`, onclick: () => { close(); useLibraryTask(t, {tryIt: true}); }}, icon("play"), "Use and try it"),
      h("span", {class: "grow"}), psy));
}

/* Which display theme an operational adaptation's copy starts in (its default first); null when cancelled. */
async function chooseTaskTheme(t) {
  const about = Object.fromEntries(((TASKLIB.data && TASKLIB.data.themes) || []).map((x) => [x.id, x]));
  let chosen = t.themes[0];
  const list = h("div", {class: "tl-theme-pick", role: "radiogroup", "aria-label": "Display theme"},
    ...t.themes.map((id, i) => h("label", {class: "tl-theme-opt"},
      h("input", {type: "radio", name: "tl-theme", value: id, checked: i === 0, onchange: () => { chosen = id; }}),
      h("span", {}, h("b", {}, (about[id] || {}).title || id.toUpperCase()), i === 0 ? h("span", {class: "t-caption"}, " (default)") : null,
        h("span", {class: "t-caption tl-theme-about"}, (about[id] || {}).about || "")))));
  const ok = await ui.dialog({title: `Display theme: ${t.title}`, icon: "book", size: "sm",
    body: h("div", {class: "tl-theme-body"}, h("p", {class: "t-2"}, "The same task and measures, shown the way an operator's console shows it. You can switch later with the variable theme (Settings › Variables)."), list),
    buttons: [{label: "Cancel", value: false}, {label: "Next", value: true, kind: "primary"}],
    initialFocus: ".tl-theme-pick input:checked"});
  return ok ? chosen : null;
}

/* Copy task t into this folder (asking for a name, and for an adaptation its theme), open it, and optionally Try it. */
async function useLibraryTask(t, {tryIt: andTry = false} = {}) {
  if (!(await confirmLeaveDirty())) return;
  let theme = null;
  if ((t.themes || []).length) {
    theme = await chooseTaskTheme(t);
    if (!theme) return;
  }
  const slug = await askExperimentName({title: `New experiment: ${t.title}`, suggest: theme ? `${t.id}_${theme}` : t.id,
    help: "It gets its own folder with a copy of the task, its pictures and sounds, and CITATION.md (what to cite)."});
  if (!slug) return;
  let r;
  try { r = await api("/api/library/new", theme ? {id: t.id, name: slug, theme} : {id: t.id, name: slug}); }
  catch (e) { return toast(`Couldn't create it: ${e.message}`, {tone: "danger", ms: 8000}); }
  try { await refreshFiles(); await openFile(r.path); }
  catch (e) { return toast(e.message, {tone: "danger"}); }
  EDGE.go("build");
  toast(`Created ${r.path} from the task library${r.theme ? ` (theme: ${r.theme.toUpperCase()})` : ""}. CITATION.md next to it says what to cite.`, {tone: "success", ms: 6000});
  if (andTry && typeof tryIt === "function") tryIt("all");
}
