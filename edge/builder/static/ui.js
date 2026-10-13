/* ui.js: the in-app replacements for native dialogs and the small interactive widgets (SPEC §7.5.3).
 * Owner: P1 (written by P0); every package uses it. Never call the browser's prompt/confirm/alert: use these.
 *   ui.dialog({title, icon, body, size, buttons, dismissible, initialFocus, onOpen}) -> Promise<value>
 *   ui.confirm({title, message, ok, cancel, danger})                               -> Promise<boolean>
 *   ui.prompt({title, label, value, help, placeholder, ok, validate, transform})   -> Promise<string|null>
 *   ui.menu(anchorOrEvent, items, {placement})                                      -> {close}
 *   ui.popover(anchor, content, {placement, onClose})                               -> {el, close}
 *   ui.toast(msg, {action: {label, run}, ms, tone})                                 -> {close}
 *   ui.seg(options, value, onChange, {ariaLabel, size})                             -> element
 *   ui.switch(checked, onChange, {label, caption, id})                              -> element
 *   ui.announce(text, {assertive}) · ui.trapFocus(container) -> release() · ui.slug(name)
 * Extensions beyond the contract (reported to the lead): ui.menu() also accepts an existing static .menu element
 * as `items` (the Experiment menu in index.html keeps its ids for tutorials and tests), and ui.wireSeg(el, value,
 * onChange) gives static segmented markup (role=radio buttons) the same keyboard and aria behaviour as ui.seg().
 * Loaded after icons.js and before app.js: it uses icon() and no other global at load time.
 */
"use strict";

const ui = (() => {
  const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), ' +
    'textarea:not([disabled]), [tabindex]:not([tabindex="-1"]), [contenteditable="true"]';
  let seq = 0;
  const openMenus = [];

  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = String(text);
    return e;
  };
  const visible = (e) => !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length));
  const focusables = (root) => [...root.querySelectorAll(FOCUSABLE)].filter((e) => visible(e) && !e.closest("[inert]"));
  const asNode = (content) => content instanceof Node ? content : (() => { const p = el("p", null, content ?? ""); return p; })();
  const layerFor = (anchor) => {
    // menus and popovers opened from inside a dialog must sit above that dialog
    const inDialog = anchor instanceof Element && anchor.closest(".scrim, #modal");
    // above the tutorial coach too: an open menu is what the step asks to use (the coach never covers its items)
    return inDialog || document.querySelector(".scrim") ? "calc(var(--z-coach) + 1)" : "";
  };

  /* ---------------------------------------------------------------- focus */
  function trapFocus(container) {
    const onKey = (e) => {
      if (e.key !== "Tab") return;
      const f = focusables(container);
      if (!f.length) { e.preventDefault(); return; }
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && (document.activeElement === first || !container.contains(document.activeElement))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (document.activeElement === last || !container.contains(document.activeElement))) { e.preventDefault(); first.focus(); }
    };
    container.addEventListener("keydown", onKey);
    return () => container.removeEventListener("keydown", onKey);
  }

  /* ---------------------------------------------------------------- live regions */
  function announce(text, {assertive = false} = {}) {
    let region = document.getElementById(assertive ? "sr-live-assertive" : "sr-live");
    if (!region) {
      region = el("div", "sr-only");
      region.id = assertive ? "sr-live-assertive" : "sr-live";
      region.setAttribute("aria-live", assertive ? "assertive" : "polite");
      document.body.append(region);
    }
    region.textContent = "";
    setTimeout(() => { region.textContent = String(text ?? ""); }, 30);
  }

  /* ---------------------------------------------------------------- dialogs */
  function openDialog(opts, intercept) {
    const {title = "", icon: iconName, body, size = "md", buttons = [{label: "Close", value: null}], dismissible = true,
      initialFocus, onOpen} = opts || {};
    return new Promise((resolve) => {
      const opener = document.activeElement;
      const openerId = opener?.id || "", openerKey = opener?.dataset?.fkey || "";
      const host = document.getElementById("dialogs") || document.body;
      const scrim = el("div", "scrim");
      const dlg = el("div", "dialog " + size);
      const titleId = "dlg-title-" + (++seq);
      dlg.setAttribute("role", "dialog");
      dlg.setAttribute("aria-modal", "true");
      dlg.setAttribute("aria-labelledby", titleId);
      const head = el("header");
      if (iconName) head.append(icon(iconName, "m"));
      const h2 = el("h2", null, title);
      h2.id = titleId;
      head.append(h2);
      let done = false;
      const close = (value) => {
        if (done) return;
        done = true;
        release();
        scrim.remove();
        if (typeof opts.returnFocus === "function") { const t = opts.returnFocus(); if (t && t.focus) { t.focus(); resolve(value); return; } }
        if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
        else setTimeout(() => {       // the opener was re-rendered meanwhile: the same control again, by its id or focus key
          const a = document.activeElement;
          if (a && a !== document.body && a.isConnected) return;
          const t = (openerId && document.getElementById(openerId)) || (openerKey && document.querySelector(`[data-fkey="${CSS.escape(openerKey)}"]`));
          if (t && typeof t.focus === "function") t.focus();
        }, 0);
        resolve(value);
      };
      if (dismissible) {
        const x = el("button", "btn ghost icon sm");
        x.type = "button";
        x.setAttribute("aria-label", "Close");
        x.append(icon("close"));
        x.onclick = () => close(null);
        head.append(x);
      }
      const bodyEl = el("div", "body");
      if (body !== undefined && body !== null) bodyEl.append(asNode(body));
      dlg.append(head, bodyEl);
      const btnEls = [];
      if (buttons && buttons.length) {
        const foot = el("footer");
        for (const b of buttons) {
          const kind = b.kind && b.kind !== "default" ? " " + b.kind : "";
          const be = el("button", "btn" + kind + (b.left ? " left" : ""), b.label);
          be.type = "button";
          if (b.disabled) be.disabled = true;
          be.onclick = async () => {
            if (intercept) {
              const r = await intercept(b.value, close, dlg);
              if (r === false) return;
            }
            close(b.value);
          };
          btnEls.push(be);
          foot.append(be);
        }
        dlg.append(foot);
      }
      dlg.bodyEl = bodyEl;
      scrim.append(dlg);
      let downOnScrim = false;
      scrim.addEventListener("mousedown", (e) => { downOnScrim = e.target === scrim; });
      scrim.addEventListener("click", (e) => { if (dismissible && downOnScrim && e.target === scrim) close(null); });
      dlg.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { e.stopPropagation(); e.preventDefault(); if (dismissible) close(null); }
      });
      host.append(scrim);
      const release = trapFocus(dlg);
      if (typeof onOpen === "function") onOpen(dlg, close);
      let target = null;
      if (initialFocus instanceof Element) target = initialFocus;
      else if (typeof initialFocus === "string") target = dlg.querySelector(initialFocus);
      if (!target) target = focusables(bodyEl)[0] || btnEls.find((b) => b.classList.contains("primary")) || btnEls[btnEls.length - 1] || focusables(dlg)[0];
      if (target) setTimeout(() => target.focus(), 0);
    });
  }
  const dialog = (opts) => openDialog(opts, null);

  const confirmDialog = ({title, message, ok = "OK", cancel = "Cancel", danger = false} = {}) =>
    openDialog({title, body: message, size: "sm", initialFocus: danger ? "footer .btn:not(.danger)" : undefined, buttons: [
      {label: cancel, value: false},
      {label: ok, value: true, kind: danger ? "danger" : "primary"}]}, null).then((v) => v === true);

  function promptDialog({title, label, value = "", help, placeholder, ok = "OK", validate, transform} = {}) {
    const wrap = el("div", "field");
    const id = "dlg-input-" + (++seq);
    const lab = el("label", null, label || "");
    lab.htmlFor = id;
    const input = el("input", "input");
    input.id = id;
    input.value = value ?? "";
    input.autocomplete = "off";
    input.spellcheck = false;
    if (placeholder) input.placeholder = placeholder;
    const hint = el("div", "help");
    const err = el("div", "err");
    err.id = id + "-err";
    err.setAttribute("role", "alert");
    err.hidden = true;
    const helpEl = help ? el("div", "help", help) : null;
    if (label) wrap.append(lab);
    wrap.append(input, err, hint);
    if (helpEl) wrap.append(helpEl);
    const finalValue = () => (typeof transform === "function" ? transform(input.value) : input.value);
    const refresh = () => {
      const v = finalValue();
      hint.textContent = typeof transform === "function" && v && v !== input.value ? `Saved as ${v}` : "";
      hint.hidden = !hint.textContent;
    };
    const showError = (msg) => {
      err.replaceChildren();
      if (msg) { err.append(icon("error"), document.createTextNode(String(msg))); }
      err.hidden = !msg;
      input.setAttribute("aria-invalid", msg ? "true" : "false");
      if (msg) input.setAttribute("aria-describedby", err.id); else input.removeAttribute("aria-describedby");
    };
    input.addEventListener("input", () => { refresh(); showError(null); });
    refresh();
    let result = null;
    const check = async (val, close) => {
      if (val !== true) return true;              // Cancel
      const v = finalValue();
      const msg = typeof validate === "function" ? await validate(v) : null;
      if (msg) { showError(msg); input.focus(); return false; }
      result = v;
      return true;
    };
    return openDialog({title, body: wrap, size: "sm", initialFocus: input,
      buttons: [{label: "Cancel", value: false}, {label: ok, value: true, kind: "primary"}],
      onOpen: (dlg) => {
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); dlg.querySelector("footer .btn.primary").click(); }
        });
        setTimeout(() => input.select(), 0);
      }}, check).then((v) => (v === true ? result : null));
  }

  /* ---------------------------------------------------------------- positioning */
  function place(box, anchor, placement = "bottom-start") {
    box.style.left = "0px"; box.style.top = "0px";
    const r = box.getBoundingClientRect();
    const vw = innerWidth, vh = innerHeight, m = 8;
    let x, y;
    if (anchor && typeof anchor.clientX === "number" && !(anchor instanceof Element)) {
      x = anchor.clientX; y = anchor.clientY;
      if (x + r.width > vw - m) x = Math.max(m, x - r.width);
      if (y + r.height > vh - m) y = Math.max(m, vh - m - r.height);
    } else {
      const a = (anchor instanceof Element ? anchor : document.body).getBoundingClientRect();
      const [side, align] = placement.split("-");
      if (side === "top") { y = a.top - r.height - 4; if (y < m) y = a.bottom + 4; }
      else if (side === "right") { x = a.right + 2; y = a.top - 4; }
      else { y = a.bottom + 4; if (y + r.height > vh - m) y = a.top - r.height - 4 >= m ? a.top - r.height - 4 : Math.max(m, vh - m - r.height); }
      if (side !== "right") x = align === "end" ? a.right - r.width : a.left;
      if (side === "right" && x + r.width > vw - m) x = Math.max(m, a.left - r.width - 2);
      if (y + r.height > vh - m) y = Math.max(m, vh - m - r.height);
    }
    x = Math.min(Math.max(m, x), Math.max(m, vw - m - r.width));
    y = Math.max(m, y);
    box.style.left = Math.round(x) + "px"; box.style.top = Math.round(y) + "px";
  }

  /* ---------------------------------------------------------------- menus (APG menu pattern) */
  function closeAllMenus() { while (openMenus.length) openMenus[openMenus.length - 1].close(); }

  function menu(anchorOrEvent, items, {placement = "bottom-start", parent = null} = {}) {
    if (!parent) closeAllMenus();
    const anchorEl = anchorOrEvent instanceof Element ? anchorOrEvent
      : (anchorOrEvent && anchorOrEvent.currentTarget instanceof Element && typeof anchorOrEvent.clientX !== "number" ? anchorOrEvent.currentTarget : null);
    const point = !(anchorOrEvent instanceof Element) && anchorOrEvent && typeof anchorOrEvent.clientX === "number"
      && (anchorOrEvent.clientX || anchorOrEvent.clientY) ? anchorOrEvent : null;
    const keyboardAnchor = !point && anchorOrEvent && anchorOrEvent.currentTarget instanceof Element ? anchorOrEvent.currentTarget : null;
    const opener = document.activeElement;
    const isStatic = items instanceof Element;
    let box;
    let sub = null;
    if (isStatic) {
      box = items;
      box.hidden = false;
    } else {
      box = el("div", "menu");
      box.setAttribute("role", "menu");
      for (const it of items || []) {
        if (!it) continue;
        if (it.sep || it === "-") { const hr = el("hr"); hr.setAttribute("role", "separator"); box.append(hr); continue; }
        if (it.head) {
          const hd = el("div", "head", it.head); hd.setAttribute("role", "presentation");
          if (it.name) { const nm = el("span", "head-name", `“${it.name}”`); hd.append(" ", nm); }   // a quoted name keeps its own case
          box.append(hd); continue;
        }
        const b = el("button", "item" + (it.danger ? " danger" : ""));
        b.type = "button";
        b.tabIndex = -1;
        b.setAttribute("role", it.checked !== undefined ? "menuitemcheckbox" : "menuitem");
        if (it.checked !== undefined) {
          b.setAttribute("aria-checked", it.checked ? "true" : "false");
          const chk = el("span", "chk");
          if (it.checked) chk.append(icon("check"));
          b.append(chk);
        }
        if (it.icon) b.append(icon(it.icon));
        b.append(el("span", "lbl", it.label));
        if (it.shortcut) b.append(el("span", "sc", it.shortcut));
        if (it.items) { b.setAttribute("aria-haspopup", "menu"); b.setAttribute("aria-expanded", "false"); b.append(icon("chev-right")); }
        if (it.title) b.title = it.title;
        if (it.disabled) b.setAttribute("aria-disabled", "true");
        b._item = it;
        box.append(b);
      }
      document.body.append(box);
    }
    const z = layerFor(anchorEl || keyboardAnchor || opener);
    if (z) box.style.zIndex = z;
    const itemsOf = () => [...box.querySelectorAll('[role^="menuitem"]')].filter((b) => visible(b));
    const enabled = () => itemsOf().filter((b) => b.getAttribute("aria-disabled") !== "true" && !b.disabled);
    itemsOf().forEach((b) => { b.tabIndex = -1; });
    place(box, point || anchorEl || keyboardAnchor, placement);
    const ctlAnchor = anchorEl || keyboardAnchor;
    if (ctlAnchor && ctlAnchor.hasAttribute("aria-haspopup")) ctlAnchor.setAttribute("aria-expanded", "true");

    const closeSub = () => { if (sub) { const s = sub; sub = null; s.close(true); } };
    const openSub = (b) => {
      closeSub();
      b.setAttribute("aria-expanded", "true");
      sub = menu(b, b._item.items, {placement: "right-start", parent: handle});
      sub.onClosed = () => b.setAttribute("aria-expanded", "false");
    };
    const activate = async (b) => {
      if (!b || b.getAttribute("aria-disabled") === "true" || b.disabled) return;
      const it = b._item;
      if (it && it.items) { openSub(b); return; }
      handle.close(false, true);
      if (it && typeof it.run === "function") await it.run();
    };
    const onKey = (e) => {
      const list = enabled();
      const i = list.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); (list[(i + 1) % list.length] || list[0])?.focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); (list[(i - 1 + list.length) % list.length] || list[list.length - 1])?.focus(); }
      else if (e.key === "Home") { e.preventDefault(); list[0]?.focus(); }
      else if (e.key === "End") { e.preventDefault(); list[list.length - 1]?.focus(); }
      else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); handle.close(); }
      else if (e.key === "Tab") { handle.close(false); }
      else if (e.key === "ArrowRight" && document.activeElement?._item?.items) { e.preventDefault(); openSub(document.activeElement); }
      else if (e.key === "ArrowLeft" && parent) { e.preventDefault(); handle.close(); }
      else if ((e.key === "Enter" || e.key === " ") && list.includes(document.activeElement)) {
        e.preventDefault();
        if (isStatic) document.activeElement.click(); else activate(document.activeElement);
      } else if (e.key.length === 1 && /\S/.test(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
        const k = e.key.toLowerCase();
        const order = [...list.slice(i + 1), ...list.slice(0, i + 1)];
        const hit = order.find((b) => (b.textContent || "").trim().toLowerCase().startsWith(k));
        if (hit) hit.focus();
      }
    };
    const onClick = (e) => {
      const b = e.target.closest('[role^="menuitem"]');
      if (!b || !box.contains(b)) return;
      if (isStatic) { if (b.getAttribute("aria-disabled") !== "true") setTimeout(() => handle.close(false, true), 0); return; }
      e.preventDefault();
      activate(b);
    };
    const onHover = (e) => {
      const b = e.target.closest('[role^="menuitem"]');
      if (b && box.contains(b) && b.getAttribute("aria-disabled") !== "true") {
        if (document.activeElement !== b) b.focus({preventScroll: true});
        if (!isStatic && b._item?.items) openSub(b); else if (sub && b !== sub.anchor) closeSub();
      }
    };
    const onOutside = (e) => {
      if (box.contains(e.target) || (ctlAnchor && ctlAnchor.contains(e.target))) return;
      if (openMenus.some((m) => m !== handle && m.el.contains(e.target))) return;
      handle.close(false);
    };
    const onResize = () => handle.close(false);
    box.addEventListener("keydown", onKey);
    box.addEventListener("click", onClick);
    box.addEventListener("mousemove", onHover);
    setTimeout(() => { document.addEventListener("mousedown", onOutside, true); }, 0);
    window.addEventListener("resize", onResize);
    let closed = false;
    const handle = {
      el: box, anchor: ctlAnchor,
      close(fromParent = false, activated = false, restoreFocus = true) {
        if (closed) return;
        closed = true;
        closeSub();
        box.removeEventListener("keydown", onKey);
        box.removeEventListener("click", onClick);
        box.removeEventListener("mousemove", onHover);
        document.removeEventListener("mousedown", onOutside, true);
        window.removeEventListener("resize", onResize);
        if (isStatic) { box.hidden = true; box.style.zIndex = ""; } else box.remove();
        if (ctlAnchor && ctlAnchor.hasAttribute("aria-haspopup")) ctlAnchor.setAttribute("aria-expanded", "false");
        const k = openMenus.indexOf(handle);
        if (k >= 0) openMenus.splice(k, 1);
        if (typeof handle.onClosed === "function") handle.onClosed();
        if (parent && !fromParent && !activated) { ctlAnchor?.focus(); return; }
        if (parent && activated) { parent.close(false, true); return; }
        if (!parent && restoreFocus) {
          // give focus back to whatever opened the menu (the chosen action may then move it, e.g. into a dialog)
          const back = ctlAnchor || opener;
          const lost = !document.activeElement || document.activeElement === document.body || box.contains(document.activeElement);
          if (lost && back && back.isConnected && typeof back.focus === "function") back.focus({preventScroll: true});
        }
      },
    };
    openMenus.push(handle);
    const first = enabled()[0];
    if (first) setTimeout(() => first.focus({preventScroll: true}), 0);
    return {close: (...a) => handle.close(...a), el: box, set onClosed(fn) { handle.onClosed = fn; }, get anchor() { return ctlAnchor; }};
  }

  /* ---------------------------------------------------------------- popover */
  function popover(anchor, content, {placement = "bottom-start", onClose} = {}) {
    const box = el("div", "popover");
    box.append(asNode(content));
    const z = layerFor(anchor);
    if (z) box.style.zIndex = z;
    document.body.append(box);
    place(box, anchor, placement);
    const opener = document.activeElement;
    let closed = false;
    const close = () => {
      if (closed) return;
      closed = true;
      document.removeEventListener("mousedown", onOutside, true);
      document.removeEventListener("keydown", onKey, true);
      window.removeEventListener("resize", close);
      box.remove();
      if (anchor instanceof Element && anchor.hasAttribute("aria-expanded")) anchor.setAttribute("aria-expanded", "false");
      if (box.contains(document.activeElement) || document.activeElement === document.body) opener?.focus?.();
      if (typeof onClose === "function") onClose();
    };
    const onOutside = (e) => { if (!box.contains(e.target) && !(anchor instanceof Element && anchor.contains(e.target))) close(); };
    const onKey = (e) => { if (e.key === "Escape" && (box.contains(document.activeElement) || document.activeElement === anchor)) { e.stopPropagation(); close(); } };
    setTimeout(() => document.addEventListener("mousedown", onOutside, true), 0);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", close);
    if (anchor instanceof Element && anchor.hasAttribute("aria-expanded")) anchor.setAttribute("aria-expanded", "true");
    const f = focusables(box)[0];
    if (f) setTimeout(() => f.focus({preventScroll: true}), 0);
    return {el: box, close};
  }

  /* ---------------------------------------------------------------- toasts */
  function toast(msg, {action, ms, tone} = {}) {
    let host = document.getElementById("toast");
    if (!host) { host = el("div"); host.id = "toast"; host.setAttribute("role", "status"); host.setAttribute("aria-live", "polite"); document.body.append(host); }
    const t = el("div", "toast" + (tone ? " " + tone : ""));
    t.append(el("span", "msg", msg));
    let timer = null, closed = false;
    const close = () => {
      if (closed) return;
      closed = true;
      clearTimeout(timer);
      t.remove();
    };
    if (action && action.label) {
      const b = el("button", "act", action.label);
      b.type = "button";
      b.onclick = async () => { close(); if (typeof action.run === "function") await action.run(); };
      t.append(b);
    }
    const dur = typeof ms === "number" ? ms : (action ? 8000 : 5000);
    const start = () => { clearTimeout(timer); timer = setTimeout(close, dur); };
    t.addEventListener("mouseenter", () => clearTimeout(timer));
    t.addEventListener("mouseleave", start);
    t.addEventListener("focusin", () => clearTimeout(timer));
    t.addEventListener("focusout", start);
    host.append(t);
    while (host.querySelectorAll(".toast").length > 3) host.querySelector(".toast").remove();
    start();
    return {close};
  }

  /* ---------------------------------------------------------------- segmented control (radiogroup) */
  function wireSeg(group, value, onChange) {
    group.setAttribute("role", "radiogroup");
    const radios = () => [...group.querySelectorAll('[role="radio"]')].filter((b) => !b.hidden && getComputedStyle(b).display !== "none");
    const valueOf = (b) => b.dataset.value ?? b.dataset.mode ?? b.dataset.view ?? b.dataset.side ?? b.dataset.ctab ?? b.textContent.trim();
    const setValue = (v) => {
      for (const b of group.querySelectorAll('[role="radio"]')) {
        const on = valueOf(b) === String(v);
        b.setAttribute("aria-checked", on ? "true" : "false");
        b.tabIndex = on ? 0 : -1;
      }
      if (!radios().some((b) => b.tabIndex === 0) && radios()[0]) radios()[0].tabIndex = 0;
      group.dataset.value = v ?? "";
    };
    const pick = (b) => {
      if (!b || b.disabled) return;
      const v = valueOf(b);
      const changed = group.dataset.value !== v;
      setValue(v);
      if (changed && typeof onChange === "function") onChange(v);
    };
    if (!group._segWired) {
      group._segWired = true;
      group.addEventListener("click", (e) => { const b = e.target.closest('[role="radio"]'); if (b && group.contains(b)) pick(b); });
      group.addEventListener("keydown", (e) => {
        const list = radios();
        const i = list.indexOf(document.activeElement);
        if (i < 0) return;
        let j = null;
        if (e.key === "ArrowRight" || e.key === "ArrowDown") j = (i + 1) % list.length;
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp") j = (i - 1 + list.length) % list.length;
        else if (e.key === "Home") j = 0;
        else if (e.key === "End") j = list.length - 1;
        if (j === null) return;
        e.preventDefault();
        list[j].focus();
        pick(list[j]);
      });
    }
    setValue(value);
    group.setValue = setValue;
    return group;
  }

  function seg(options, value, onChange, {ariaLabel, size} = {}) {
    const group = el("div", "seg" + (size ? " " + size : ""));
    if (ariaLabel) group.setAttribute("aria-label", ariaLabel);
    for (const o of options || []) {
      const b = el("button");
      b.type = "button";
      b.setAttribute("role", "radio");
      b.dataset.value = String(o.value);
      if (o.icon) b.append(icon(o.icon));
      if (o.label) b.append(document.createTextNode(o.label));
      else if (o.title) b.setAttribute("aria-label", o.title);
      if (o.title) b.title = o.title;
      group.append(b);
    }
    return wireSeg(group, value === undefined || value === null ? "" : String(value), onChange);
  }

  /* ---------------------------------------------------------------- switch */
  function switchEl(checked, onChange, {label, caption, id} = {}) {
    const b = el("button", "switch");
    b.type = "button";
    b.setAttribute("role", "switch");
    if (id) b.id = id;
    const set = (v) => { b.setAttribute("aria-checked", v ? "true" : "false"); };
    set(!!checked);
    b.addEventListener("click", () => {
      const v = b.getAttribute("aria-checked") !== "true";
      set(v);
      if (typeof onChange === "function") onChange(v);
    });
    if (!label) { b.setChecked = set; return b; }
    const row = el("label", "switch-row");
    const txt = el("span", "txt");
    const lbl = el("span", "lbl", label);
    lbl.id = (id || "sw-" + (++seq)) + "-label";
    b.setAttribute("aria-labelledby", lbl.id);
    txt.append(lbl);
    if (caption) {
      const cap = el("span", "cap", caption);
      cap.id = lbl.id.replace(/-label$/, "-cap");
      b.setAttribute("aria-describedby", cap.id);
      txt.append(cap);
    }
    row.append(b, txt);
    row.setChecked = set;
    row.switchButton = b;
    return row;
  }

  /* ---------------------------------------------------------------- names */
  function slug(name) {
    let s = String(name ?? "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
    s = s.replace(/[^a-z0-9_]+/g, "_").replace(/_+/g, "_").replace(/^_+|_+$/g, "");
    if (/^\d/.test(s)) s = "_" + s;
    return s;
  }

  return {
    dialog,
    confirm: confirmDialog,
    prompt: promptDialog,
    menu,
    popover,
    toast,
    seg,
    switch: switchEl,
    announce,
    trapFocus,
    slug,
    wireSeg,
    closeMenus: closeAllMenus,
  };
})();
