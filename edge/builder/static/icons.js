/* icons.js: the EDGE icon set v1 (SPEC §3.8). Owner: P1 (written by P0).
 * Owns EDGE_ICONS (name -> inner SVG markup on a 24 x 24 grid, 1.75 stroke, round caps and joins, currentColor),
 * the inline sprite injected once into <body> as <symbol id="i-NAME">, and two helpers:
 *   icon(name, cls = "") -> an <svg class="ic cls" aria-hidden="true"><use href="#i-name"/></svg> element
 *   ic(name, cls = "")   -> the same markup as an HTML string
 * Unknown names render the "info" icon and are logged once. No icon font, no CDN, no emoji.
 * Loaded first: it reads no other global.
 */
"use strict";

const EDGE_ICONS = {
  // app and workspaces
  home: '<path d="M4 11l8-7 8 7"/><path d="M6 9.5V20h12V9.5"/><path d="M10 20v-5.5h4V20"/>',
  design: '<path d="M4 20l1-4.2L16.2 4.6a2 2 0 0 1 2.8 0l.4.4a2 2 0 0 1 0 2.8L8.2 19z"/><path d="M14.5 6.3l3.2 3.2"/>',
  measures: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1" class="dotf"/>',
  test: '<path d="M9 3h6"/><path d="M10 3v6.2L4.6 18.4A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.4-2.6L14 9.2V3"/><path d="M7.2 15h9.6"/>',
  run: '<circle cx="9" cy="7" r="3.2"/><path d="M3 20.5c0-3.4 2.7-6.1 6-6.1"/><path d="M14 13.5v7l6-3.5z"/>',
  results: '<path d="M4 20h16"/><path d="M7 16.5V11M12 16.5V6.5M17 16.5V9"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.4a2.5 2.5 0 1 1 3.4 2.4c-.6.3-1 .8-1 1.5v.5"/><path d="M12 17h.01"/>',
  assistant: '<path d="M11 3.5l1.9 5.1 5.1 1.9-5.1 1.9L11 17.5l-1.9-5.1L4 10.5l5.1-1.9z"/><path d="M18.5 14.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  settings: '<path d="M4 6.5h9M18 6.5h2M4 12h3M11 12h9M4 17.5h11M19 17.5h1"/><circle cx="15.5" cy="6.5" r="2.2"/><circle cx="9" cy="12" r="2.2"/><circle cx="17" cy="17.5" r="2.2"/>',
  command: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M7 10l2.5 2L7 14M12 14h5"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
  save: '<path d="M5 3.5h10.5L19.5 7.5V19a1.5 1.5 0 0 1-1.5 1.5H6A1.5 1.5 0 0 1 4.5 19V5A1.5 1.5 0 0 1 5 3.5z"/><path d="M8 3.5V8h7V3.5M8 20.5v-6h8v6"/>',
  folder: '<path d="M3.5 6.5A1.5 1.5 0 0 1 5 5h4l2 2h8a1.5 1.5 0 0 1 1.5 1.5v9.5A1.5 1.5 0 0 1 19 19.5H5A1.5 1.5 0 0 1 3.5 18z"/>',
  file: '<path d="M14 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3.5V8h4.5"/>',
  import: '<path d="M12 3.5v11M7.5 10l4.5 4.5 4.5-4.5"/><path d="M5 20h14"/>',
  export: '<path d="M12 14.5v-11M7.5 8L12 3.5 16.5 8"/><path d="M5 20h14"/>',
  history: '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1"/><path d="M3.5 4v4.5H8"/><path d="M12 8v4.2l3 1.8"/>',
  package: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  lock: '<rect x="5" y="11" width="14" height="9.5" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  book: '<path d="M4.5 5.5A2 2 0 0 1 6.5 3.5h13v15h-13a2 2 0 0 0-2 2z"/><path d="M4.5 20.5v-15M8.5 7.5h7"/>',
  learn: '<path d="M2.5 9.5L12 5l9.5 4.5L12 14z"/><path d="M6.5 11.5v4.5c3 2.2 8 2.2 11 0v-4.5M21.5 9.5v5"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
  moon: '<path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10z"/>',
  // generic actions
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  close: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  'chev-down': '<path d="M6.5 9.5l5.5 5.5 5.5-5.5"/>',
  'chev-right': '<path d="M9.5 6.5l5.5 5.5-5.5 5.5"/>',
  'chev-left': '<path d="M14.5 6.5L9 12l5.5 5.5"/>',
  more: '<path d="M5.5 12h.01M12 12h.01M18.5 12h.01" stroke-width="2.6"/>',
  drag: '<path d="M9 6h.01M15 6h.01M9 12h.01M15 12h.01M9 18h.01M15 18h.01" stroke-width="2.6"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
  trash: '<path d="M4 7h16M9.5 7V4.5h5V7M6.5 7l.9 12.6A1.5 1.5 0 0 0 8.9 21h6.2a1.5 1.5 0 0 0 1.5-1.4L17.5 7M10 11v6M14 11v6"/>',
  duplicate: '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/><path d="M15.5 8.5V5a1.5 1.5 0 0 0-1.5-1.5H5A1.5 1.5 0 0 0 3.5 5v9A1.5 1.5 0 0 0 5 15.5h3.5"/>',
  expand: '<path d="M14 4h6v6M10 20H4v-6M20 4l-6.5 6.5M4 20l6.5-6.5"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9"/><path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
  refresh: '<path d="M19.5 10.5A7.8 7.8 0 0 0 5.8 7L4 9M4 4.5V9h4.5M4.5 13.5A7.8 7.8 0 0 0 18.2 17l1.8-2M20 19.5V15h-4.5"/>',
  play: '<path d="M7.5 4.8v14.4a.8.8 0 0 0 1.2.7l11-7.2a.8.8 0 0 0 0-1.4l-11-7.2a.8.8 0 0 0-1.2.7z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  pause: '<path d="M9 5.5v13M15 5.5v13"/>',
  send: '<path d="M12 19.5v-15M6 10.5l6-6 6 6"/>',
  attach: '<path d="M20 11.5l-8.3 8.3a5 5 0 0 1-7.1-7.1L13 4.3a3.4 3.4 0 0 1 4.8 4.8l-8.2 8.2a1.7 1.7 0 0 1-2.4-2.4l7.4-7.4"/>',
  key: '<circle cx="8" cy="15.5" r="4"/><path d="M11 12.5l8.5-8.5M16.5 7l2.5 2.5M14 9.5l2 2"/>',
  cloud: '<path d="M7 18.5a4.5 4.5 0 0 1-.7-8.9A6 6 0 0 1 17.8 9a4.5 4.5 0 0 1-.8 9.5z"/>',
  chip: '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5" rx=".5"/><path d="M9.5 2.5V6M14.5 2.5V6M9.5 18v3.5M14.5 18v3.5M2.5 9.5H6M2.5 14.5H6M18 9.5h3.5M18 14.5h3.5"/>',
  person: '<circle cx="12" cy="8" r="4"/><path d="M4.5 20.5c0-4.1 3.4-7.5 7.5-7.5s7.5 3.4 7.5 7.5"/>',
  eyeoff: '<path d="M3 3l18 18M10.6 5.6A9.6 9.6 0 0 1 12 5.5c6 0 9.5 6.5 9.5 6.5a17 17 0 0 1-2.7 3.4M6.3 6.8A16 16 0 0 0 2.5 12S6 18.5 12 18.5a9 9 0 0 0 4.3-1.1"/><path d="M9.9 10a3 3 0 0 0 4.1 4.1"/>',
  pin: '<path d="M9 3.5h6l-1 5 3 3v1.5H7v-1.5l3-3z"/><path d="M12 13v7.5"/>',
  list: '<path d="M9 6.5h11M9 12h11M9 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01" />',
  dot: '<circle cx="12" cy="12" r="5" class="dotf"/>',
  // status
  success: '<circle cx="12" cy="12" r="9"/><path d="M8 12.4l2.8 2.8L16.2 9.8"/>',
  warning: '<path d="M10.3 4.3L2.9 17.5A2 2 0 0 0 4.6 20.5h14.8a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"/><path d="M12 9.5v4"/><path d="M12 16.8h.01"/>',
  error: '<circle cx="12" cy="12" r="9"/><path d="M15 9l-6 6M9 9l6 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5.5"/><path d="M12 7.6h.01"/>',
  star: '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
  checklist: '<path d="M4 7l2 2 3.5-3.5M4 15.5l2 2 3.5-3.5M13 7.5h7M13 16h7"/>',
  // views
  storyboard: '<rect x="3.5" y="4.5" width="7" height="6" rx="1.5"/><rect x="13.5" y="4.5" width="7" height="6" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="6" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="6" rx="1.5"/>',
  timeline: '<path d="M3.5 6.5h8M7 12h11M10 17.5h8.5"/><path d="M3.5 3.5v17" stroke-width="1.25"/>',
  screen: '<rect x="3.5" y="5" width="17" height="12" rx="2"/><path d="M8.5 20h7"/>',
  code: '<path d="M9 7.5L4.5 12 9 16.5M15 7.5l4.5 4.5-4.5 4.5"/>',
  table: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 9.5h17M3.5 14.5h17M9.5 4.5v15"/>',
  // things on a screen
  text: '<path d="M5.5 7V4.5h13V7M12 4.5v15M9 19.5h6"/>',
  image: '<rect x="3.5" y="5" width="17" height="14" rx="2"/><circle cx="9" cy="10" r="1.7"/><path d="M20.5 15.5l-4.5-4.5L7 19"/>',
  shape: '<rect x="3.5" y="10.5" width="9" height="9" rx="1.5"/><circle cx="15.5" cy="8.5" r="5"/>',
  fixation: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M12 8.5v7M8.5 12h7"/>',
  sound: '<path d="M4 9.5h3l4.5-4v13l-4.5-4H4z"/><path d="M15.5 9.2a4 4 0 0 1 0 5.6M18.2 6.6a7.6 7.6 0 0 1 0 10.8"/>',
  page: '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><path d="M3.5 8.5h17M7 12.5h10M7 15.5h6"/>',
  survey: '<rect x="5" y="4.5" width="14" height="16" rx="2"/><path d="M9 4.5V3.5h6v1"/><path d="M8.5 10l1.2 1.2 2-2M8.5 15l1.2 1.2 2-2M13.5 10.5h2.5M13.5 15.5h2.5"/>',
  keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6.5 10h.01M10 10h.01M14 10h.01M17.5 10h.01M7.5 14h9"/>',
  buttonbox: '<rect x="2.5" y="7" width="19" height="10" rx="3"/><circle cx="8" cy="12" r="2"/><circle cx="16" cy="12" r="2"/>',
  mouse: '<rect x="6.5" y="3" width="11" height="18" rx="5.5"/><path d="M12 7v3"/>',
  rating: '<path d="M4 12h16M4 9v6M20 9v6"/><circle cx="14.5" cy="12" r="2.5" class="fillbg"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  gazefollow: '<circle cx="8.5" cy="12" r="5.5"/><circle cx="8.5" cy="12" r="2"/><path d="M15.5 12h6M18.5 9l3 3-3 3"/>',
  calibrate: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="1.5"/><path d="M12 2.5V6M12 18v3.5M2.5 12H6M18 12h3.5"/>',
  marker: '<path d="M5.5 21V4M5.5 4.5h11l-2.2 4 2.2 4h-11"/>',
  variable: '<path d="M4.5 8l6 7M10.5 8l-6 7"/><path d="M14 10h6M14 14h6"/>',
  pause_blank: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  // flow
  loop: '<path d="M4 11.5V9.5a3 3 0 0 1 3-3h12.5M16.5 3.5l3 3-3 3"/><path d="M20 12.5v2a3 3 0 0 1-3 3H4.5M7.5 20.5l-3-3 3-3"/>',
  branch: '<circle cx="6" cy="5.5" r="2"/><circle cx="6" cy="18.5" r="2"/><circle cx="18" cy="7.5" r="2"/><path d="M6 7.5v9M18 9.5c0 4.5-12 2.5-12 7"/>',
  workflow: '<rect x="3" y="4" width="7.5" height="6" rx="1.5"/><rect x="13.5" y="14" width="7.5" height="6" rx="1.5"/><path d="M10.5 7h4a2.8 2.8 0 0 1 2.8 2.8V14"/><path d="M15 11.8l2.3 2.2 2.2-2.2"/>',
  // devices
  device: '<path d="M9 3v5M15 3v5M6.5 8h11v3a5.5 5.5 0 0 1-11 0z"/><path d="M12 16.5V21"/>',
  eeg: '<path d="M2.5 12h3l2-5.5 3 11 3-8.5 2 5 1.8-2h4.2"/>',
  eyetracker: '<rect x="2.5" y="14" width="19" height="4.5" rx="1.5"/><path d="M6 16.2h.01M18 16.2h.01"/><path d="M5 10S7.8 5.5 12 5.5 19 10 19 10"/><circle cx="12" cy="9.2" r="1.6"/>',
  trigger: '<path d="M13 3L5 13.5h6L10 21l8-10.5h-6z"/>',
};
EDGE_ICONS.clock = EDGE_ICONS.pause_blank;   // aliases
EDGE_ICONS.rules = EDGE_ICONS.trigger;

/* The sprite: one hidden <svg> with a <symbol> per icon, injected once at load (scripts sit at the end of <body>). */
(function injectIconSprite() {
  if (document.getElementById("edge-icon-sprite")) return;
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("id", "edge-icon-sprite");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.style.cssText = "position:absolute;width:0;height:0;overflow:hidden";
  const symbols = Object.entries(EDGE_ICONS).map(([k, v]) => `<symbol id="i-${k}" viewBox="0 0 24 24">${v}</symbol>`).join("");
  svg.innerHTML = `<style>.dotf{fill:currentColor;stroke:none}.fillbg{fill:var(--surface-1)}</style>${symbols}`;
  document.body.prepend(svg);
})();

const _iconWarned = new Set();
function _iconName(name) {
  if (EDGE_ICONS[name]) return name;
  if (!_iconWarned.has(name)) { _iconWarned.add(name); console.warn(`EDGE icons: no icon called "${name}", showing "info"`); }
  return "info";
}

/* icon(name, cls) -> SVGSVGElement (decorative: aria-hidden; the button carrying it has a label). */
function icon(name, cls = "") {
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("class", ("ic " + (cls || "")).trim());
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const use = document.createElementNS(NS, "use");
  use.setAttribute("href", "#i-" + _iconName(name));
  svg.append(use);
  return svg;
}

/* ic(name, cls) -> the same icon as an HTML string (for templates that build markup). */
function ic(name, cls = "") {
  return `<svg class="${("ic " + (cls || "")).trim()}" aria-hidden="true" focusable="false"><use href="#i-${_iconName(name)}"/></svg>`;
}
