/* tablefile.js: trial lists that come from a file, edited in place (builder editing, part 3). Owner: builder editing.
 * The Trial list view (W5) draws a list whose rows come from a CSV, TSV or Excel file with fileTableView() (called
 * first by build.js fileListView): the same grid as "Typed here" (arrows, Enter or typing edits, Tab moves on, Esc
 * cancels), plus the row and column menus (insert, duplicate, move, delete, rename), Paste from Excel (or Ctrl/Cmd+V
 * on a cell: a block of cells lands there, rows and columns are added as needed) and the editor's own Undo / Redo.
 * Every change is written back to the same file, in its own format, shortly after you stop (GET/POST
 * /api/edit/table): the first save of a session keeps the previous version in the file's History (.edge/backups),
 * which History… lists and restores. An Excel workbook with other sheets or formulas asks first (that sheet is
 * then saved as values); without openpyxl an Excel file is offered as a CSV copy. While the view is open the file
 * is watched (/api/fingerprint): a change made in another program is loaded, or, with edits of yours not yet
 * saved, a strip asks which version to keep.
 */
"use strict";

const FT = {key: null, data: null, error: null, loading: false, fp: null, undo: [], redo: [], dirty: false, saving: false, timer: null,
  backedUp: false, confirmValues: false, conflict: null, savedAt: null, poll: null, cell: {r: 0, c: 0}, n: null, path: null};
const FT_EXT = /\.(csv|tsv|txt|xlsx)$/i;

const ftExpDir = () => (S.path ? S.path.replace(/[^/]*$/, "") : "");
const ftFileOf = (n) => (typeof n.conditions === "string" ? n.conditions : n.conditions?.file);
const ftRowsKey = (n) => JSON.stringify(n.conditions) + "|" + (S.path || "");

function fileTableView(n, path) {
  const file = ftFileOf(n);
  if (!file || !FT_EXT.test(file) || !S.path || S.noDoc || isExpr(file)) return null;
  const key = S.path + "|" + file;
  FT.n = n; FT.path = path;
  if (FT.key !== key) { ftReset(key); ftLoad(); }
  ftWatch();
  const box = h("div", {class: "le-filebox ft-box", "data-file": file});
  box.append(ftInfoBar(n, path, file));
  if (FT.conflict) box.append(ftConflictStrip(file));
  for (const w of FT.data?.warnings || []) box.append(h("div", {class: "alert warning ft-warn"}, icon("warning"), h("div", {}, w)));
  if (FT.error) {
    box.append(h("div", {class: "alert danger"}, icon("error"), h("div", {}, h("b", {}, `EDGE can't read ${file.split("/").pop()}`), " ", FT.error)),
      h("div", {class: "le-foot"}, btn("Read it again", () => { ftReset(key); ftLoad(); renderAll(); }, {ic: "refresh"})));
    return box;
  }
  if (!FT.data) { box.append(h("div", {class: "le-loading"}, h("span", {class: "spin"}), "Reading the file…")); return box; }
  box.append(ftGrid(n, file));
  if (typeof listWarnings === "function") box.append(...listWarnings(n, FT.data.columns));
  return box;
}
function ftReset(key) {
  clearTimeout(FT.timer);
  Object.assign(FT, {key, data: null, error: null, fp: null, undo: [], redo: [], dirty: false, saving: false, backedUp: false,
    confirmValues: false, conflict: null, savedAt: null, cell: {r: 0, c: 0}});
}
async function ftLoad({quiet = false} = {}) {
  const key = FT.key, [exp, file] = [S.path, key.split("|").slice(1).join("|")];
  FT.loading = true;
  try {
    const d = await api(`/api/edit/table?exp=${encodeURIComponent(exp)}&file=${encodeURIComponent(file)}`);
    if (FT.key !== key) return;
    d.rows = d.rows.map((r) => r.map((v) => (v === null || v === undefined ? "" : typeof v === "boolean" ? (v ? "true" : "false") : String(v))));
    FT.data = d; FT.fp = d.fingerprint; FT.error = null;
  } catch (e) {
    if (FT.key !== key) return;
    FT.error = e.message;
  } finally { FT.loading = false; }
  if (!quiet || S.view === "list") ftRender();
}
function ftRender() { if (S.view === "list" && typeof renderListEditor === "function") renderListEditor(); }

/* ---------------- the bar above the grid */
function ftInfoBar(n, path, file) {
  const d = FT.data;
  const state = FT.saving ? "Saving…" : FT.dirty ? "Not saved yet" : FT.savedAt ? `Saved to the file ${clock(FT.savedAt)}` : "Edits are saved to the file";
  const ro = !!S.proposal;
  return h("div", {class: "le-fileinfo ft-info"},
    h("span", {class: "label"}, "File"), h("span", {class: "mono le-file"}, file),
    d ? h("span", {class: "t-caption"}, `${plural(d.rows.length, "row")} · ${plural(d.columns.length, "column")}${d.sheet ? ` · sheet “${d.sheet}”` : ""}`) : null,
    h("span", {class: "ft-state t-caption" + (FT.dirty ? " dirty" : ""), role: "status"}, ro && d ? "Read-only here" : state),
    h("span", {class: "grow"}),
    iconBtn("undo", "Undo (in this file)", () => ftUndo(), "btn ghost icon sm", FT.undo.length && !ro ? {} : {disabled: ""}),
    iconBtn("redo", "Redo (in this file)", () => ftRedo(), "btn ghost icon sm", FT.redo.length && !ro ? {} : {disabled: ""}),
    btn("History…", () => ftHistory(file), {cls: "btn sm ghost", ic: "history"}),
    btn("Change file…", () => switchListSource(n, path, "file"), {cls: "btn sm", ic: "folder"}),
    btn("Copy into the experiment", () => {
      if (!bEditable() || !FT.data) return;
      n.conditions = FT.data.rows.map((r) => Object.fromEntries(FT.data.columns.map((c, i) => [c, cellValue(r[i] ?? "")])));
      commit(`Copy ${file} into the experiment`);
      toast(`The rows of ${file.split("/").pop()} are now typed in the experiment. The file itself is unchanged.`);
    }, {cls: "btn sm ghost", attrs: d ? {} : {disabled: ""}}),
    iconBtn("refresh", "Read the file again", () => { ftFlush().then(() => { ftReset(FT.key); ftLoad(); renderAll(); }); }));
}
function ftConflictStrip(file) {
  return h("div", {class: "alert warning ft-conflict", role: "alert"}, icon("warning"),
    h("div", {class: "msg"}, h("b", {}, `${file.split("/").pop()} was changed in another program. `), "Your edits here aren't saved yet."),
    btn("Use the file's version", () => { FT.conflict = null; FT.dirty = false; clearTimeout(FT.timer); ftReset(FT.key); ftLoad(); }, {cls: "btn sm"}),
    btn("Keep my version", () => { FT.conflict = null; ftSave({force: true}); }, {cls: "btn sm primary"}));
}

/* ---------------- the grid */
function ftGrid(n, file) {
  const d = FT.data, cols = d.columns, rows = d.rows;
  const ro = !!S.proposal;      // an Excel file without openpyxl: editing offers a CSV copy (ftEditable)
  const use = typeof columnUse === "function" ? columnUse(n, cols) : {};
  const colour = typeof colourColumns === "function" ? colourColumns(use) : new Set();
  const table = h("table", {class: "grid edit le-grid ft-grid", role: "grid", "aria-label": `Rows of ${file}`, "aria-rowcount": String(rows.length + 1)});
  const head = h("tr", {}, h("th", {class: "le-num", scope: "col"}, "#"));
  cols.forEach((col, ci) => {
    const u = use[col] || [];
    head.append(h("th", {scope: "col", class: BUILD.listColumn === col ? "hl" : ""},
      h("button", {type: "button", class: "le-colname", "data-fkey": "ftcol:" + ci, title: "Rename, insert, move or delete this column", onclick: (e) => ftColumnMenu(e.currentTarget, ci)},
        h("span", {class: "mono"}, col || "(no name)"), icon("chev-down")),
      h("div", {class: "le-use" + (u.length ? "" : " unused")}, u.length ? `▸ ${u[0].id} · ${u[0].prop}${u.length > 1 ? ` +${u.length - 1}` : ""}` : "(not used: for analysis)")));
  });
  head.append(h("th", {class: "le-addcol"}, iconBtn("plus", "Add a column", () => ftAddColumn(cols.length), "btn ghost icon sm", ro ? {disabled: ""} : {})));
  const body = h("tbody", {});
  rows.forEach((r, ri) => {
    const tr = h("tr", {"aria-rowindex": String(ri + 2)},
      h("th", {class: "le-num", scope: "row"}, h("button", {type: "button", class: "le-rowbtn", tabindex: "-1", title: "Insert, move or delete rows", onclick: (e) => ftRowMenu(e.currentTarget, ri)}, String(ri + 1))));
    cols.forEach((col, ci) => {
      const td = h("td", {role: "gridcell", tabindex: ri === FT.cell.r && ci === FT.cell.c ? "0" : "-1", "data-r": ri, "data-c": ci, "data-fkey": `ftcell:${ri}:${ci}`,
        class: BUILD.listColumn === col ? "hl" : ""});
      td.append(...cellDisplay(r[ci] === "" ? "" : cellValue(r[ci]), colour.has(col)));
      td.addEventListener("mousedown", () => ftActive(table, ri, ci));
      td.addEventListener("dblclick", () => ftEdit(table, ri, ci));
      tr.append(td);
    });
    tr.append(h("td", {class: "le-pad"}));
    body.append(tr);
  });
  table.append(h("thead", {}, head), body);
  table.addEventListener("keydown", (e) => ftKeys(e, table));
  table.addEventListener("paste", (e) => { if (e.target.tagName === "INPUT") return; e.preventDefault(); ftPaste(e.clipboardData.getData("text/plain")); });
  table.addEventListener("copy", (e) => {
    if (e.target.tagName === "INPUT") return;
    const v = FT.data.rows[FT.cell.r]?.[FT.cell.c]; if (v === undefined) return;
    e.preventDefault(); e.clipboardData.setData("text/plain", v);
  });
  table.addEventListener("focusin", (e) => { const td = e.target.closest("td[data-r]"); if (td) FT.cell = {r: +td.dataset.r, c: +td.dataset.c}; });
  return h("div", {class: "le-table"},
    h("div", {class: "le-gridwrap"}, table),
    h("div", {class: "le-foot"},
      btn("Row", () => ftChange("Add a row", () => { rows.push(cols.map(() => "")); FT.cell = {r: rows.length - 1, c: 0}; }), {ic: "plus", attrs: ro ? {disabled: ""} : {}}),
      btn("Paste from Excel", () => ftPasteDialog(), {cls: "btn sm ghost", ic: "table", attrs: ro ? {disabled: ""} : {}}),
      h("span", {class: "t-caption le-hint"}, `Arrows move · Enter edits · ${MOD}+V pastes cells from a spreadsheet · changes are saved to the file`)));
}
function ftActive(table, r, c) {
  FT.cell = {r, c};
  for (const td of table.querySelectorAll("td[data-r]")) td.tabIndex = +td.dataset.r === r && +td.dataset.c === c ? 0 : -1;
}
function ftFocusCell() {
  const td = document.querySelector(`.ft-grid td[data-r="${FT.cell.r}"][data-c="${FT.cell.c}"]`);
  if (td) { ftActive(td.closest("table"), FT.cell.r, FT.cell.c); td.focus(); td.scrollIntoView({block: "nearest", inline: "nearest"}); }
}
function ftKeys(e, table) {
  const mod = e.ctrlKey || e.metaKey;
  if (mod && !e.altKey && (e.key.toLowerCase() === "z" || e.key.toLowerCase() === "y")) {
    e.preventDefault(); e.stopPropagation();
    if (e.key.toLowerCase() === "y" || e.shiftKey) ftRedo(); else ftUndo();
    return;
  }
  const td = e.target.closest("td[data-r]");
  if (!td || e.target.tagName === "INPUT") return;
  const r = +td.dataset.r, c = +td.dataset.c, rows = FT.data.rows, cols = FT.data.columns;
  const go = (rr, cc) => { FT.cell = {r: Math.max(0, Math.min(rows.length - 1, rr)), c: Math.max(0, Math.min(cols.length - 1, cc))}; ftFocusCell(); };
  if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); e.stopPropagation(); ftMoveRow(r, e.key === "ArrowUp" ? -1 : 1); return; }
  if (e.key === "ArrowUp") { e.preventDefault(); go(r - 1, c); }
  else if (e.key === "ArrowDown") { e.preventDefault(); go(r + 1, c); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); go(r, c - 1); }
  else if (e.key === "ArrowRight") { e.preventDefault(); go(r, c + 1); }
  else if (e.key === "Home") { e.preventDefault(); go(mod ? 0 : r, 0); }
  else if (e.key === "End") { e.preventDefault(); go(mod ? rows.length - 1 : r, cols.length - 1); }
  else if (e.key === "Enter" || e.key === "F2") { e.preventDefault(); ftEdit(table, r, c); }
  else if ((e.key === "Delete" || e.key === "Backspace") && !mod) {
    e.preventDefault(); e.stopPropagation();
    if (rows[r][c] !== "") ftChange("Clear a cell", () => { rows[r][c] = ""; });
  } else if (e.key.length === 1 && !mod && !e.altKey) { e.preventDefault(); ftEdit(table, r, c, e.key); }
}
function ftEdit(table, r, c, initial = null) {
  if (!ftEditable()) return;
  const td = table.querySelector(`td[data-r="${r}"][data-c="${c}"]`); if (!td) return;
  const cur = FT.data.rows[r][c] ?? "";
  const input = h("input", {class: "input le-input", value: initial !== null ? initial : cur, "aria-label": `Row ${r + 1}, ${FT.data.columns[c]}`, spellcheck: "false"});
  td.replaceChildren(input); td.classList.add("editing");
  input.focus();
  if (initial === null) input.select(); else input.setSelectionRange(input.value.length, input.value.length);
  let done = false;
  const finish = (save, move) => {
    if (done) return; done = true;
    const [dr, dc] = move || [0, 0];
    FT.cell = {r: Math.max(0, Math.min(FT.data.rows.length - 1, r + dr)), c: Math.max(0, Math.min(FT.data.columns.length - 1, c + dc))};
    if (save && input.value !== cur) ftChange(`Edit ${FT.data.columns[c]} in row ${r + 1}`, () => { FT.data.rows[r][c] = input.value; });
    else { ftRender(); ftFocusCell(); }
  };
  input.addEventListener("keydown", (e) => {
    e.stopPropagation();
    if (e.key === "Enter") { e.preventDefault(); finish(true, [e.shiftKey ? -1 : 1, 0]); }
    else if (e.key === "Tab") { e.preventDefault(); finish(true, [0, e.shiftKey ? -1 : 1]); }
    else if (e.key === "Escape") { e.preventDefault(); finish(false); }
  });
  input.addEventListener("blur", () => finish(true));
}
function ftEditable() {
  if (!bEditable()) return false;
  const d = FT.data;
  if (d && d.format === "xlsx" && !d.writable) { ftOfferCsv(); return false; }
  return !!d;
}

/* One change = one step of the editor's Undo, then a save shortly after. */
function ftChange(label, fn) {
  if (!ftEditable()) return;
  FT.undo.push({label, data: JSON.stringify([FT.data.columns, FT.data.rows])});
  if (FT.undo.length > 100) FT.undo.shift();
  FT.redo = [];
  fn();
  FT.dirty = true;
  ftRender(); ftFocusCell();
  ftSchedule();
  ui.announce(label);
}
function ftRestore(snap) { const [c, r] = JSON.parse(snap); FT.data.columns = c; FT.data.rows = r; }
function ftUndo() {
  const s = FT.undo.pop(); if (!s || !ftEditable()) return;
  FT.redo.push({label: s.label, data: JSON.stringify([FT.data.columns, FT.data.rows])});
  ftRestore(s.data); FT.dirty = true; ftRender(); ftFocusCell(); ftSchedule();
  ui.announce(`Undid: ${s.label}`);
}
function ftRedo() {
  const s = FT.redo.pop(); if (!s || !ftEditable()) return;
  FT.undo.push({label: s.label, data: JSON.stringify([FT.data.columns, FT.data.rows])});
  ftRestore(s.data); FT.dirty = true; ftRender(); ftFocusCell(); ftSchedule();
  ui.announce(`Redid: ${s.label}`);
}

/* ---------------- rows and columns */
function ftRowMenu(anchor, ri) {
  const rows = FT.data.rows, blank = () => FT.data.columns.map(() => "");
  ui.menu(anchor, [
    {label: "Insert a row above", run: () => ftChange("Insert a row", () => rows.splice(ri, 0, blank()))},
    {label: "Insert a row below", run: () => ftChange("Insert a row", () => rows.splice(ri + 1, 0, blank()))},
    {label: "Duplicate the row", icon: "duplicate", run: () => ftChange("Duplicate a row", () => rows.splice(ri + 1, 0, [...rows[ri]]))},
    {label: "Move up", shortcut: "Alt ↑", disabled: ri === 0, run: () => ftMoveRow(ri, -1)},
    {label: "Move down", shortcut: "Alt ↓", disabled: ri === rows.length - 1, run: () => ftMoveRow(ri, 1)},
    {sep: true},
    {label: "Delete the row", icon: "trash", danger: true, run: () => ftChange(`Delete row ${ri + 1}`, () => { rows.splice(ri, 1); FT.cell = {r: Math.max(0, ri - 1), c: FT.cell.c}; })}]);
}
function ftMoveRow(ri, d) {
  const rows = FT.data.rows, j = ri + d;
  if (j < 0 || j >= rows.length) return;
  ftChange(`Move row ${ri + 1} ${d < 0 ? "up" : "down"}`, () => { [rows[ri], rows[j]] = [rows[j], rows[ri]]; FT.cell = {r: j, c: FT.cell.c}; });
}
function ftColumnMenu(anchor, ci) {
  const cols = FT.data.columns, col = cols[ci];
  ui.menu(anchor, [
    {label: "Rename…", run: () => ftRenameColumn(ci)},
    {label: "Insert a column on the left…", run: () => ftAddColumn(ci)},
    {label: "Insert a column on the right…", run: () => ftAddColumn(ci + 1)},
    {label: "Move left", icon: "chev-left", disabled: ci === 0, run: () => ftMoveColumn(ci, -1)},
    {label: "Move right", icon: "chev-right", disabled: ci === cols.length - 1, run: () => ftMoveColumn(ci, 1)},
    {sep: true},
    {label: "Delete the column", icon: "trash", danger: true, run: () => ftChange(`Delete the column “${col}”`, () => {
      cols.splice(ci, 1); FT.data.rows.forEach((r) => r.splice(ci, 1)); FT.cell = {r: FT.cell.r, c: Math.max(0, Math.min(ci, cols.length - 1))};
    })}]);
}
function ftMoveColumn(ci, d) {
  const j = ci + d, cols = FT.data.columns;
  if (j < 0 || j >= cols.length) return;
  ftChange(`Move the column “${cols[ci]}”`, () => {
    [cols[ci], cols[j]] = [cols[j], cols[ci]];
    for (const r of FT.data.rows) [r[ci], r[j]] = [r[j], r[ci]];
    FT.cell = {r: FT.cell.r, c: j};
  });
}
async function ftAddColumn(at) {
  if (!ftEditable()) return;
  const cols = FT.data.columns;
  const name = await ui.prompt({title: "New column", label: "Column name", value: uniqueId("column", new Set(cols)), ok: "Add column",
    help: "Something that changes from trial to trial: the word, its colour, the right key.",
    transform: (v) => ui.slug(v), validate: (v) => !v ? "Type a name first." : cols.includes(v) ? `There is already a column “${v}”.` : null});
  if (!name) return;
  ftChange(`Add the column “${name}”`, () => {
    cols.splice(at, 0, name);
    for (const r of FT.data.rows) r.splice(at, 0, "");
    if (!FT.data.rows.length) FT.data.rows.push(cols.map(() => ""));
    FT.cell = {r: 0, c: at};
  });
}
async function ftRenameColumn(ci) {
  if (!ftEditable()) return;
  const cols = FT.data.columns, col = cols[ci];
  const nc = await ui.prompt({title: `Rename the column “${col}”`, label: "Column name", value: col, ok: "Rename", transform: (v) => ui.slug(v),
    validate: (v) => !v ? "Type a name first." : v !== col && cols.includes(v) ? `There is already a column “${v}”.` : null});
  if (!nc || nc === col) return;
  ftChange(`Rename the column “${col}”`, () => { cols[ci] = nc; });
  // the screens of this trial list keep working: $old becomes $new in their items (one step of the experiment's Undo)
  const n = FT.n; if (!n) return;
  let changed = 0;
  const re = new RegExp(`\\$${col}\\b`, "g");
  for (const rid of routinesInside(n)) for (const c of S.exp.routines[rid]?.components || [])
    for (const [k, v] of Object.entries(c)) if (isExpr(v) && re.test(v)) { re.lastIndex = 0; c[k] = v.replace(re, "$" + nc); changed++; }
  if (changed) { commit(`Rename the column “${col}”`); toast(`Renamed the column and updated ${plural(changed, "item")} that used it`); }
}
function ftParse(text) {
  text = String(text || "").replace(/\r\n?/g, "\n").replace(/\n+$/, "");
  if (!text) return [];
  const sep = text.includes("\t") ? "\t" : text.includes(";") && !text.includes(",") ? ";" : text.includes(",") && text.includes("\n") ? "," : "\t";
  return text.split("\n").map((l) => l.split(sep).map((x) => x.replace(/^"(.*)"$/, "$1")));
}
/* A block copied from Excel, LibreOffice or Google Sheets lands at the active cell; rows and columns are added as needed. */
function ftPaste(text, {at = FT.cell} = {}) {
  const grid = ftParse(text); if (!grid.length || !ftEditable()) return;
  const cols = FT.data.columns, rows = FT.data.rows;
  let block = grid;
  // the column names copied along: drop them when they match
  if (grid.length > 1 && grid[0].length <= cols.length && grid[0].every((x, j) => x === cols[at.c + j])) block = grid.slice(1);
  const width = Math.max(...block.map((g) => g.length));
  ftChange(`Paste ${plural(block.length, "row")}`, () => {
    while (cols.length < at.c + width) { cols.push(uniqueId("column", new Set(cols))); rows.forEach((r) => r.push("")); }
    block.forEach((g, i) => {
      const ri = at.r + i;
      while (rows.length <= ri) rows.push(cols.map(() => ""));
      g.forEach((v, j) => { rows[ri][at.c + j] = v.trim(); });
    });
  });
  toast(`Pasted ${plural(block.length, "row")} × ${plural(width, "column")}`);
}
async function ftPasteDialog() {
  if (!ftEditable()) return;
  const ta = h("textarea", {class: "input mono", rows: "8", placeholder: "word\tink\tkey\nRED\tred\tr", "aria-label": "Cells to paste"});
  const v = await ui.dialog({title: "Paste cells from a spreadsheet", icon: "table", size: "md", initialFocus: ta,
    body: h("div", {class: "field"}, h("p", {class: "t-2"}, "Copy the cells in Excel, LibreOffice or Google Sheets, then paste them here. They land at the selected cell; with the row of column names they replace all rows."), ta),
    buttons: [{label: "Cancel", value: null}, {label: "At the selected cell", value: "cell"}, {label: "Replace all rows", value: "replace", kind: "primary"}]});
  if (!v || !ta.value.trim()) return;
  if (v === "cell") return ftPaste(ta.value);
  const grid = ftParse(ta.value);
  ftChange("Replace all rows", () => {
    const header = grid[0].every((x) => x && isNaN(Number(x)));
    FT.data.columns = header ? grid[0].map((x, i) => ui.slug(x) || `column${i + 1}`) : FT.data.columns.length ? FT.data.columns : grid[0].map((_, i) => `column${i + 1}`);
    const w = FT.data.columns.length;
    FT.data.rows = (header ? grid.slice(1) : grid).map((g) => Array.from({length: w}, (_, j) => (g[j] ?? "").trim()));
    FT.cell = {r: 0, c: 0};
  });
}

/* ---------------- saving */
function ftSchedule() { clearTimeout(FT.timer); FT.timer = setTimeout(() => ftSave(), 700); }
async function ftFlush() { if (FT.dirty && !FT.conflict) { clearTimeout(FT.timer); await ftSave(); } }
async function ftSave({force = false, asCsv = false} = {}) {
  if (!FT.data || FT.saving) { if (FT.saving) ftSchedule(); return; }
  const key = FT.key, file = key.split("|").slice(1).join("|");
  FT.saving = true; ftRenderState();
  let r;
  try {
    r = await api("/api/edit/table", {exp: S.path, file, sheet: FT.data.sheet || null, columns: FT.data.columns, rows: FT.data.rows,
      fingerprint: FT.fp, force, backup: !FT.backedUp, confirm_values: FT.confirmValues || undefined, as_csv: asCsv || undefined});
  } catch (e) {
    FT.saving = false; ftRenderState();
    if (FT.key === key) toast(`Couldn't save ${file.split("/").pop()}: ${e.message}`, {tone: "danger"});
    return;
  }
  FT.saving = false;
  if (FT.key !== key) return;
  if (r.ok === false) {          // a question, not an error: nothing was written
    ftRenderState();
    if (r.conflict) { FT.conflict = {fp: r.fingerprint}; ftRender(); return; }
    if (r.needs_csv) return ftOfferCsv();
    if (r.needs_confirm) {
      const parts = [];
      if (r.formulas) parts.push(`its ${plural(r.formulas, "formula")} will be saved as their current values`);
      if ((r.other_sheets || []).length) parts.push(`the other sheets (${r.other_sheets.join(", ")}) are kept as they are`);
      const ok = await ui.confirm({title: `Save “${FT.data.sheet}” as values?`, ok: "Save as values", cancel: "Not now",
        message: `This sheet will be written as plain values: ${parts.join("; ")}. The previous version stays in History.`});
      if (ok) { FT.confirmValues = true; return ftSave({force}); }
      return;
    }
    return toast(`Couldn't save ${file.split("/").pop()}: ${r.message || "unknown reason"}`, {tone: "danger"});
  }
  if (r.new_file) return ftUseCsv(r.saved);
  FT.fp = r.fingerprint; FT.backedUp = true; FT.dirty = false; FT.savedAt = new Date(); FT.conflict = null;
  ftRenderState();
  ftRowsChanged();
}
function ftRenderState() {
  const el = document.querySelector(".ft-info .ft-state"); if (!el) return;
  el.textContent = FT.saving ? "Saving…" : FT.dirty ? "Not saved yet" : FT.savedAt ? `Saved to the file ${clock(FT.savedAt)}` : "Edits are saved to the file";
  el.classList.toggle("dirty", FT.dirty);
  const [u, r] = document.querySelectorAll(".ft-info .btn.icon");
  if (u) u.disabled = !FT.undo.length; if (r) r.disabled = !FT.redo.length;
}
/* The preview, the storyboard and the checks read the new rows (no new request). */
function ftRowsChanged() {
  const n = FT.n; if (!n || !FT.data) return;
  BUILD.rows[ftRowsKey(n)] = FT.data.rows.map((r) => Object.fromEntries(FT.data.columns.map((c, i) => [c, cellValue(r[i] ?? "")]).filter(([, v]) => v !== "")));
  BUILD.thumbs?.clear?.();
  scheduleValidate();
  if (typeof renderProps === "function" && S.ws === "build") renderProps();       // "From stroop.csv · 10 rows", its columns
}
async function ftOfferCsv() {
  const file = FT.key.split("|").slice(1).join("|");
  const ok = await ui.confirm({title: "Save as a CSV file?", ok: "Save as CSV", cancel: "Not now",
    message: `Editing ${file.split("/").pop()} here needs openpyxl (pip install edge-experiments[excel]). EDGE can save your rows as a CSV file next to it and use that file instead; the Excel file stays as it is.`});
  if (ok) { FT.data.writable = true; ftSave({asCsv: true}); }
}
function ftUseCsv(rel) {
  const n = FT.n; if (!n) return;
  if (typeof n.conditions === "object" && n.conditions) n.conditions.file = rel; else n.conditions = rel;
  commit(`Use ${rel} as the trial list “${n.loop}”`);
  toast(`Saved as ${rel}: the trial list uses it now.`);
}

/* ---------------- History of the file */
async function ftHistory(file) {
  await ftFlush();
  const rel = ftExpDir() + file;
  let list = [];
  try { list = (await api(`/api/backups?path=${encodeURIComponent(rel)}`)).backups || []; } catch (e) { return toast(e.message, {tone: "danger"}); }
  const body = h("div", {class: "ft-history"});
  if (!list.length) body.append(h("p", {class: "t-2"}, `No earlier versions of ${file.split("/").pop()} yet. Each editing session here keeps the version before it.`));
  else body.append(h("p", {class: "t-2"}, "Earlier versions of the file, newest first. Restoring one keeps the current version too."),
    h("div", {class: "pick-list", role: "list"}, list.slice(0, 30).map((b) => h("div", {class: "pick-row", role: "listitem"}, icon("history"),
      h("span", {}, dayTime(b.time)), h("span", {class: "t-caption"}, b.label || ""), h("span", {class: "grow"}),
      btn("Restore", async () => {
        try { await api(`/api/restore?path=${encodeURIComponent(rel)}&id=${encodeURIComponent(b.id)}`, {}); } catch (e) { return toast(e.message, {tone: "danger"}); }
        ui.closeMenus();
        document.querySelector("#dialogs .scrim [data-value='close'], #dialogs .scrim footer .btn")?.click();
        ftReset(FT.key); FT.backedUp = true; await ftLoad(); ftRowsChanged();
        toast(`Restored the version of ${dayTime(b.time)}. The one before is in History too.`);
      }, {cls: "btn sm"})))));
  await ui.dialog({title: `History of ${file.split("/").pop()}`, icon: "history", size: "md", body, buttons: [{label: "Close", value: "close", kind: "primary"}]});
}

/* ---------------- changes made in another program */
function ftWatch() {
  if (FT.poll) return;
  FT.poll = setInterval(ftPoll, 2500);
  window.addEventListener("focus", ftPoll);
}
async function ftPoll() {
  if (S.view !== "list" || !FT.key || !FT.fp || FT.saving || FT.loading || document.hidden) return;
  const file = FT.key.split("|").slice(1).join("|");
  if (!S.path || FT.key !== S.path + "|" + file) return;
  let fp;
  try { fp = (await api(`/api/fingerprint?path=${encodeURIComponent(ftExpDir() + file)}`)).fingerprint; } catch { return; }
  if (!fp || fp === FT.fp || FT.saving) return;
  if (FT.dirty) { if (!FT.conflict) { FT.conflict = {fp}; ftRender(); } return; }
  const keep = FT.cell;
  ftReset(FT.key); FT.cell = keep;
  await ftLoad();
  ftRowsChanged();
  toast(`${file.split("/").pop()} was changed in another program: showing the new version.`);
}
EDGE.on("view", ({view}) => { if (view !== "list") ftFlush(); });
EDGE.on("doc:loaded", () => { ftReset(null); });
window.addEventListener("beforeunload", (e) => { if (FT.dirty) { ftSave(); e.preventDefault(); e.returnValue = ""; } });
