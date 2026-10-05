/* EDGE survey page. The question list arrives as JSON in #edge-survey; answers go to window.edge.submit().
 * No dependencies; works offline. Every question type builds a card and knows how to check itself. */
(function () {
"use strict";
var S = JSON.parse(document.getElementById('edge-survey').textContent);
var T = S.text, root = document.getElementById('survey'), ans = {}, page = 0, t0 = Date.now(), times = {};
var cards = [], pageTimers = [], clickLog = [];

/* ------------------------------------------------------------------ helpers */
function el(tag, attrs, kids) {
  var e = document.createElement(tag); attrs = attrs || {};
  for (var k in attrs) {
    var v = attrs[k];
    if (v === null || v === undefined || v === false) continue;
    if (k === 'html') e.innerHTML = v; else if (k === 'text') e.textContent = v;
    else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? '' : v);
  }
  (kids || []).forEach(function (c) { if (c !== null && c !== undefined && c !== false) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
  return e;
}
function empty(a) { if (a === undefined || a === null || a === '') return true; if (Array.isArray(a)) return !a.length;
  if (typeof a === 'object') { for (var k in a) return false; return true; } return false; }
function url(p) { if (!p) return ''; if (/^(https?:|data:|blob:|\/)/.test(p)) return p; return S.asset ? S.asset + encodeURIComponent(p) : p; }
function fmt(s, o) { s = String(s); for (var k in o) s = s.split('{' + k + '}').join(o[k]); return s; }
function clamp(x, a, b) { return Math.max(a, Math.min(b, x)); }
function ids(q) { return (q.items || []).map(function (i) { return i.id; }); }

/* ------------------------------------------------------------------ display logic (same rules as Python) */
function cmp(a, op, ref) {
  if (op === 'answered') return (!empty(a)) === !!ref;
  if (empty(a)) return op === '!=' || op === 'not_in';
  var vals = Array.isArray(a) ? a : [a], s = vals.map(String), refs = Array.isArray(ref) ? ref.map(String) : [String(ref)];
  if (op === '=' || op === '==' || op === 'contains') return s.indexOf(String(ref)) >= 0;
  if (op === '!=') return s.indexOf(String(ref)) < 0;
  if (op === 'in') return refs.some(function (r) { return s.indexOf(r) >= 0; });
  if (op === 'not_in') return !refs.some(function (r) { return s.indexOf(r) >= 0; });
  var x = parseFloat(vals[0]), y = parseFloat(ref); if (isNaN(x) || isNaN(y)) return false;
  return {'>': x > y, '>=': x >= y, '<': x < y, '<=': x <= y}[op];
}
function holds(c) {
  if (!c) return true;
  for (var k in c) {
    var v = c[k];
    if (k === 'any') { if (!v.some(holds)) return false; continue; }
    if (k === 'all') { if (!v.every(holds)) return false; continue; }
    var tests = (v !== null && typeof v === 'object' && !Array.isArray(v)) ? v : (Array.isArray(v) ? {'in': v} : {'=': v});
    for (var op in tests) if (!cmp(ans[k], op, tests[op])) return false;
  }
  return true;
}
function labelOf(id) {
  var v = ans[id]; if (empty(v)) return '…'; var out = [];
  S.flat.forEach(function (q) { (q.options || []).forEach(function (o) {
    if (q.id === id && (Array.isArray(v) ? v.map(String).indexOf(String(o.value)) >= 0 : String(o.value) === String(v))) out.push(o.label); }); });
  if (out.length) return out.join(', ');
  return Array.isArray(v) ? v.join(', ') : (typeof v === 'object' ? '…' : String(v));
}
function pipe(s) { return String(s || '').replace(/\{\{\s*answer\.([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g, function (_, id) { return labelOf(id).replace(/</g, '&lt;'); }); }
function setv(id, v) { ans[id] = v; refreshVisibility(); }

/* ------------------------------------------------------------------ building blocks */
function radioGroup(q, cls, name, getv, onset) {
  name = name || q.id; getv = getv || function () { return ans[q.id]; };
  onset = onset || function (o) { setv(q.id, o.value); };
  var box = el('div', {'class': cls || ''}), other = null;
  q.options.forEach(function (o) {
    var inp = el('input', {type: 'radio', name: name, value: String(o.value), onchange: function () {
      onset(o); if (other) other.style.display = (o.label === q.other_option) ? '' : 'none'; }});
    if (String(getv()) === String(o.value)) inp.checked = true;
    box.appendChild(el('label', {'class': 'opt'}, [inp, el('span', {html: o.label})]));
  });
  if (q.other_option && name === q.id) {
    other = el('input', {type: 'text', 'class': 'other', placeholder: T.other, value: ans[q.id + '_other'] || '', oninput: function () { ans[q.id + '_other'] = other.value; }});
    other.style.display = labelOf(q.id) === q.other_option ? '' : 'none'; box.appendChild(other);
  }
  return box;
}
function ends(labels) { var l = labels || []; return l.length ? el('div', {'class': 'ends'}, [el('span', {text: l[0] || ''}), el('span', {text: l[l.length - 1] || ''})]) : null; }
function rangeRow(q, id, stem) {
  var lo = +(q.min || 0), hi = +(q.max === undefined ? 100 : q.max), st = +(q.step || 1), wrap = el('div', {'class': 'untouched slider-row'});
  var val = el('span', {'class': 'sval', text: T.move});
  var rng = el('input', {type: 'range', min: lo, max: hi, step: st, value: q.start !== undefined ? q.start : (lo + hi) / 2, 'aria-label': stem || q.text,
    oninput: function () { wrap.classList.remove('untouched'); val.textContent = rng.value + (q.unit || ''); setv(id, +rng.value); }});
  if (!empty(ans[id])) { rng.value = ans[id]; wrap.classList.remove('untouched'); val.textContent = ans[id] + (q.unit || ''); }
  if (stem) wrap.appendChild(el('div', {'class': 'row-stem', html: pipe(stem)}));
  wrap.appendChild(rng); var e2 = ends(q.labels); if (e2) wrap.appendChild(e2);
  if (q.show_value !== false) wrap.appendChild(el('div', {}, [T.value, val]));
  return wrap;
}
function readFile(file, cb) { var r = new FileReader(); r.onload = function () { cb(r.result); }; r.readAsDataURL(file); }

/* ------------------------------------------------------------------ question types */
var BUILD = {
  text_block: function (q) {
    var kids = [];
    if (q.text) kids.push(el('div', {html: pipe(q.text)}));
    if (q.media) {
      var m = String(q.media).toLowerCase(), src = url(q.media), node;
      if (/\.(mp4|webm|ogv|mov)$/.test(m)) node = el('video', {'class': 'media', src: src, controls: true});
      else if (/\.(mp3|wav|ogg|m4a|flac)$/.test(m)) node = el('audio', {'class': 'media', src: src, controls: true});
      else node = el('img', {'class': 'media', src: src, alt: q.alt || ''});
      kids.push(node); if (q.caption) kids.push(el('div', {'class': 'caption', html: q.caption}));
    }
    return kids;
  },
  single: function (q) { return [radioGroup(q, q.layout === 'horizontal' ? 'horizontal' : '')]; },
  likert: function (q) { return [radioGroup(q, 'likert')]; },
  nps: function (q) { return [radioGroup(q, 'likert'), ends(q.labels || [T.nps_low, T.nps_high])]; },
  scale: function (q) {
    if (!q.items) return [radioGroup(q, 'likert'), ends(q.labels)];
    var out = [];
    q.items.forEach(function (it) { out.push(el('div', {'class': 'row-stem', html: pipe(it.text)}));
      out.push(radioGroup(q, 'likert', it.id, function () { return ans[it.id]; }, function (o) { setv(it.id, o.value); })); });
    out.push(ends(q.labels)); return out;
  },
  dropdown: function (q) {
    var sel = el('select', {onchange: function () { var o = q.options[sel.selectedIndex - 1]; setv(q.id, o ? o.value : ''); }}, [el('option', {value: '', text: T.choose})]);
    q.options.forEach(function (o) { sel.appendChild(el('option', {value: String(o.value), text: o.label})); });
    if (!empty(ans[q.id])) sel.value = String(ans[q.id]); return [sel];
  },
  multiple: function (q) {
    ans[q.id] = ans[q.id] || [];
    if (q.layout === 'listbox') {
      var lb = el('select', {multiple: true, size: Math.min(q.options.length, 8), onchange: function () {
        setv(q.id, [].filter.call(lb.options, function (o) { return o.selected; }).map(function (o) { return q.options[o.index].value; })); }});
      q.options.forEach(function (o) { var op = el('option', {value: String(o.value), text: o.label}); if (ans[q.id].map(String).indexOf(String(o.value)) >= 0) op.selected = true; lb.appendChild(op); });
      return [lb, el('div', {'class': 'help', style: 'margin:4px 0 0', text: T.listbox})];
    }
    var box = el('div', {'class': q.layout === 'horizontal' ? 'horizontal' : ''}), excl = (q.exclusive || []).map(String);
    q.options.forEach(function (o) {
      var inp = el('input', {type: 'checkbox', value: String(o.value), onchange: function () {
        var cur = (ans[q.id] || []).filter(function (x) { return String(x) !== String(o.value); });
        if (inp.checked) {
          if (excl.indexOf(String(o.value)) >= 0) { cur = []; box.querySelectorAll('input[type=checkbox]').forEach(function (c) { if (c !== inp) c.checked = false; }); }
          else { cur = cur.filter(function (x) { return excl.indexOf(String(x)) < 0; }); box.querySelectorAll('input[type=checkbox]').forEach(function (c) { if (excl.indexOf(c.value) >= 0) c.checked = false; }); }
          cur.push(o.value);
        }
        setv(q.id, cur); }});
      if (ans[q.id].map(String).indexOf(String(o.value)) >= 0) inp.checked = true;
      box.appendChild(el('label', {'class': 'opt'}, [inp, el('span', {html: o.label})]));
    });
    return [box];
  },
  matrix: function (q) {
    if (q.display === 'dropdown') {
      var t = el('table', {'class': 'grid'}), tb = el('tbody');
      q.items.forEach(function (it) { var sel = el('select', {'aria-label': it.text, onchange: function () { var o = q.options[sel.selectedIndex - 1]; setv(it.id, o ? o.value : ''); }}, [el('option', {value: '', text: T.choose})]);
        q.options.forEach(function (o) { sel.appendChild(el('option', {value: String(o.value), text: o.label})); }); if (!empty(ans[it.id])) sel.value = String(ans[it.id]);
        tb.appendChild(el('tr', {'data-item': it.id}, [el('td', {'class': 'stem', html: pipe(it.text)}), el('td', {}, [sel])])); });
      t.appendChild(tb); return [t];
    }
    var tb2 = el('tbody'), head = el('tr', {}, [el('th')]);
    q.options.forEach(function (o) { head.appendChild(el('th', {html: o.label})); });
    q.items.forEach(function (it) {
      var tr = el('tr', {'data-item': it.id}, [el('td', {'class': 'stem', html: pipe(it.text)})]);
      if (q.multi) ans[it.id] = ans[it.id] || [];
      q.options.forEach(function (o) {
        var inp = q.multi ? el('input', {type: 'checkbox', value: String(o.value), 'aria-label': o.label, onchange: function () {
            var cur = (ans[it.id] || []).filter(function (x) { return String(x) !== String(o.value); }); if (inp.checked) cur.push(o.value); tr.classList.remove('miss'); setv(it.id, cur); }})
          : el('input', {type: 'radio', name: it.id, value: String(o.value), 'aria-label': o.label, onchange: function () { tr.classList.remove('miss'); setv(it.id, o.value); }});
        if (q.multi ? ans[it.id].map(String).indexOf(String(o.value)) >= 0 : String(ans[it.id]) === String(o.value)) inp.checked = true;
        tr.appendChild(el('td', {'class': 'cell', 'data-label': o.label}, [inp]));
      });
      tb2.appendChild(tr);
    });
    return [el('table', {'class': 'grid'}, [el('thead', {}, [head]), tb2])];
  },
  semantic: function (q) {
    return q.items.map(function (it) {
      var pts = el('div', {'class': 'pts'});
      q.options.forEach(function (o) { var r = el('input', {type: 'radio', name: it.id, value: String(o.value), 'aria-label': it.left + ' ' + o.label + ' ' + it.right, onchange: function () { setv(it.id, o.value); }});
        if (String(ans[it.id]) === String(o.value)) r.checked = true; pts.appendChild(r); });
      return el('div', {'class': 'sem', 'data-item': it.id}, [el('span', {'class': 'l', text: it.left}), pts, el('span', {text: it.right})]);
    });
  },
  side_by_side: function (q) {
    var h1 = el('tr', {}, [el('th')]), h2 = el('tr', {}, [el('th')]), tb = el('tbody');
    q.columns.forEach(function (c) {
      var multi = (c.type === 'single' || c.type === 'multiple');
      h1.appendChild(el('th', {'class': 'group', colspan: multi ? c.options.length : 1, html: c.label}));
      if (multi) c.options.forEach(function (o) { h2.appendChild(el('th', {html: o.label})); }); else h2.appendChild(el('th'));
    });
    q.items.forEach(function (it) {
      var tr = el('tr', {'data-item': it.id}, [el('td', {'class': 'stem', html: pipe(it.text)})]);
      q.columns.forEach(function (c) {
        var key = it.id + '_' + c.id;
        if (c.type === 'single' || c.type === 'multiple') {
          if (c.type === 'multiple') ans[key] = ans[key] || [];
          c.options.forEach(function (o) {
            var inp = c.type === 'single' ? el('input', {type: 'radio', name: key, value: String(o.value), 'aria-label': c.label + ': ' + o.label, onchange: function () { setv(key, o.value); }})
              : el('input', {type: 'checkbox', value: String(o.value), 'aria-label': c.label + ': ' + o.label, onchange: function () {
                  var cur = (ans[key] || []).filter(function (x) { return String(x) !== String(o.value); }); if (inp.checked) cur.push(o.value); setv(key, cur); }});
            if (c.type === 'single' ? String(ans[key]) === String(o.value) : ans[key].map(String).indexOf(String(o.value)) >= 0) inp.checked = true;
            tr.appendChild(el('td', {'class': 'cell', 'data-label': c.label + ': ' + o.label}, [inp]));
          });
        } else if (c.type === 'dropdown') {
          var sel = el('select', {'aria-label': c.label, onchange: function () { var o = c.options[sel.selectedIndex - 1]; setv(key, o ? o.value : ''); }}, [el('option', {value: '', text: T.choose})]);
          c.options.forEach(function (o) { sel.appendChild(el('option', {value: String(o.value), text: o.label})); }); if (!empty(ans[key])) sel.value = String(ans[key]);
          tr.appendChild(el('td', {'class': 'cell', 'data-label': c.label}, [sel]));
        } else {
          var inp2 = el('input', {type: c.type === 'number' ? 'number' : 'text', 'aria-label': c.label, value: ans[key] || '', oninput: function () { ans[key] = inp2.value; }, onchange: function () { setv(key, inp2.value); }});
          tr.appendChild(el('td', {'class': 'cell', 'data-label': c.label}, [inp2]));
        }
      });
      tb.appendChild(tr);
    });
    return [el('div', {style: 'overflow-x:auto'}, [el('table', {'class': 'grid'}, [el('thead', {}, [h1, h2]), tb])])];
  },
  slider: function (q) {
    if (!q.items) return [rangeRow(q, q.id)];
    return q.items.map(function (it) { return rangeRow(q, it.id, it.text); });
  },
  graphic_slider: function (q) {
    var n = +(q.points || 5), style = q.style || 'faces';
    if (style === 'stars' || style === 'hearts') {
      var box = el('div', {'class': 'stars', role: 'radiogroup'}), sym = style === 'hearts' ? '♥' : '★';
      function paint(v) { [].forEach.call(box.children, function (b, i) { b.classList.toggle('on', i < v); }); }
      for (var i = 1; i <= n; i++) (function (v) {
        box.appendChild(el('button', {type: 'button', 'aria-label': v + ' / ' + n, onclick: function () { setv(q.id, v); paint(v); },
          onmouseenter: function () { paint(v); }, onmouseleave: function () { paint(+ans[q.id] || 0); }}, [sym]));
      })(i);
      paint(+ans[q.id] || 0); return [box, ends(q.labels)];
    }
    var faces = ['😣', '🙁', '😕', '😐', '🙂', '😀', '😄'], face = el('div', {'class': 'face', text: '😶'});
    var qq = {min: 1, max: n, step: 1, labels: q.labels, start: Math.ceil(n / 2), show_value: q.show_value, text: q.text};
    var row = rangeRow(qq, q.id);
    function upd() { var v = ans[q.id]; if (!empty(v)) face.textContent = faces[Math.round((v - 1) / Math.max(n - 1, 1) * (faces.length - 1))]; }
    row.querySelector('input').addEventListener('input', upd); upd();
    return [face, row];
  },
  text: function (q) {
    var ty = q.secret ? 'password' : (q.validate === 'email' ? 'email' : 'text');
    var inp = el('input', {type: ty, maxlength: q.max_length, placeholder: q.placeholder, autocomplete: q.secret ? 'off' : null, value: ans[q.id] || '',
      oninput: function () { ans[q.id] = inp.value; }, onchange: function () { setv(q.id, inp.value); }});
    return [inp];
  },
  autocomplete: function (q) {
    var listId = 'dl_' + q.id, dl = el('datalist', {id: listId});
    q.options.forEach(function (o) { dl.appendChild(el('option', {value: o.label})); });
    var inp = el('input', {type: 'text', list: listId, placeholder: q.placeholder || T.typesearch, value: ans[q.id + '__label'] || '', autocomplete: 'off',
      oninput: function () { ans[q.id + '__label'] = inp.value; var o = q.options.filter(function (x) { return x.label.toLowerCase() === inp.value.trim().toLowerCase(); })[0];
        ans[q.id] = o ? o.value : (q.free_text ? inp.value : ''); }, onchange: function () { setv(q.id, ans[q.id]); }});
    return [inp, dl];
  },
  essay: function (q) {
    var ta = el('textarea', {rows: q.rows || 5, maxlength: q.max_length, placeholder: q.placeholder, oninput: function () { ans[q.id] = ta.value; cnt.textContent = ta.value.length + (q.max_length ? ' / ' + q.max_length : ''); }, onchange: function () { setv(q.id, ta.value); }});
    var cnt = el('div', {'class': 'help', style: 'margin:4px 0 0;text-align:end'}); if (!empty(ans[q.id])) ta.value = ans[q.id]; return [ta, cnt];
  },
  number: function (q) {
    var inp = el('input', {type: 'number', min: q.min, max: q.max, step: q.step || 'any', value: ans[q.id] === undefined ? '' : ans[q.id], oninput: function () { ans[q.id] = inp.value; }, onchange: function () { setv(q.id, inp.value); }});
    return q.unit ? [el('div', {}, [inp, el('span', {'class': 'unit', text: q.unit})])] : [inp];
  },
  date: function (q) {
    var inp = el('input', {type: 'date', min: q.min, max: q.max, value: ans[q.id] || '', onchange: function () { setv(q.id, inp.value); }});
    return [inp];
  },
  form: function (q) {
    var g = el('div', {'class': 'form'});
    q.fields.forEach(function (f) {
      var ty = {email: 'email', number: 'number', tel: 'tel', date: 'date', password: 'password', url: 'url'}[f.type] || 'text';
      var inp = el('input', {type: ty, id: 'f_' + f.id, placeholder: f.placeholder, maxlength: f.max_length, value: ans[f.id] || '', autocomplete: f.autocomplete || null,
        oninput: function () { ans[f.id] = inp.value; }, onchange: function () { setv(f.id, inp.value); }});
      g.appendChild(el('label', {'for': 'f_' + f.id, html: f.label + (f.required ? '<span class="req">*</span>' : '')}));
      g.appendChild(inp); g.appendChild(el('div', {'class': 'ferr', 'data-field': f.id}));
    });
    return [g];
  },
  rank: function (q) {
    var method = q.method || 'drag';
    if (method === 'select' || method === 'text') {
      var g = el('div', {'class': 'csum'}), n = q.options.length; ans[q.id + '__ranks'] = ans[q.id + '__ranks'] || {};
      q.options.forEach(function (o) {
        var cur = ans[q.id + '__ranks'][String(o.value)];
        var inp = method === 'select' ? el('select', {onchange: function () { ans[q.id + '__ranks'][String(o.value)] = inp.value === '' ? '' : +inp.value; syncRank(q); }}, [el('option', {value: '', text: '–'})])
          : el('input', {type: 'number', min: 1, max: n, step: 1, value: cur === undefined ? '' : cur, oninput: function () { ans[q.id + '__ranks'][String(o.value)] = inp.value === '' ? '' : +inp.value; syncRank(q); }});
        if (method === 'select') { for (var i = 1; i <= n; i++) inp.appendChild(el('option', {value: i, text: String(i)})); if (cur !== undefined) inp.value = cur; }
        g.appendChild(el('span', {html: o.label})); g.appendChild(inp);
      });
      return [g, el('div', {'class': 'help', style: 'margin:6px 0 0', text: fmt(T.rankn, {n: n})})];
    }
    var ol = el('ol', {'class': 'rank'}), drag = null;
    function save() { ans[q.id] = [].map.call(ol.children, function (li) { return q.options[+li.dataset.i].value; }); }
    var prev = (ans[q.id] || []).map(String), idx = q.options.map(function (o, i) { return i; });
    if (prev.length) idx.sort(function (a, b) { return prev.indexOf(String(q.options[a].value)) - prev.indexOf(String(q.options[b].value)); });
    idx.forEach(function (i) {
      var o = q.options[i];
      var li = el('li', {draggable: 'true', 'data-i': i}, [el('span', {html: o.label}),
        el('button', {type: 'button', 'class': 'mini', 'aria-label': T.up, onclick: function () { if (li.previousElementSibling) ol.insertBefore(li, li.previousElementSibling); save(); }}, ['↑']),
        el('button', {type: 'button', 'class': 'mini', 'aria-label': T.down, onclick: function () { if (li.nextElementSibling) ol.insertBefore(li.nextElementSibling, li); save(); }}, ['↓'])]);
      li.addEventListener('dragstart', function () { drag = li; li.classList.add('drag'); });
      li.addEventListener('dragend', function () { li.classList.remove('drag'); save(); });
      li.addEventListener('dragover', function (e) { e.preventDefault(); if (drag && drag !== li) { var r = li.getBoundingClientRect(); ol.insertBefore(drag, (e.clientY - r.top) > r.height / 2 ? li.nextSibling : li); } });
      ol.appendChild(li);
    });
    save(); return [ol, el('div', {'class': 'help', style: 'margin:6px 0 0', text: T.rank})];
  },
  constant_sum: function (q) {
    var total = +(q.total || 100), grid = el('div', {'class': 'csum'}), tot = el('span', {'class': 'ctotal'}); ans[q.id] = ans[q.id] || {};
    function upd() { var s = 0; for (var k in ans[q.id]) s += (+ans[q.id][k] || 0); tot.textContent = s + (q.unit || '') + ' / ' + total + (q.unit || ''); tot.classList.toggle('bad', !sumOk(q, s)); }
    q.options.forEach(function (o) {
      var inp = el('input', {type: 'number', min: 0, max: total, step: q.step || 1, value: ans[q.id][String(o.value)] === undefined ? '' : ans[q.id][String(o.value)],
        oninput: function () { ans[q.id][String(o.value)] = inp.value === '' ? '' : +inp.value; upd(); }});
      grid.appendChild(el('span', {html: o.label})); grid.appendChild(el('div', {}, [inp, q.unit ? el('span', {'class': 'unit', text: q.unit}) : null]));
    });
    grid.appendChild(el('span', {'class': 'help', style: 'margin:0', text: T.total})); grid.appendChild(tot); upd(); return [grid];
  },
  group: function (q) {
    ans[q.id] = ans[q.id] || {};
    var where = {}; for (var g in ans[q.id]) ans[q.id][g].forEach(function (v) { where[String(v)] = g; });
    var bank = el('div', {'class': 'bucket', 'data-group': ''}, [el('h4', {text: q.bank_label || T.items})]);
    var boxes = {'': bank}, wrap = el('div', {'class': 'groups'}, [bank]);
    q.groups.forEach(function (gr) { var b = el('div', {'class': 'bucket', 'data-group': gr.id}, [el('h4', {html: gr.label})]); boxes[gr.id] = b; wrap.appendChild(b); });
    var drag = null;
    function save() { var out = {}; q.groups.forEach(function (gr) { out[gr.id] = [].map.call(boxes[gr.id].querySelectorAll('.chip'), function (c) { return q.items[+c.dataset.i].value; }); }); ans[q.id] = out; }
    function chip(i) {
      var it = q.items[i], sel = el('select', {'aria-label': T.moveto, onchange: function () { boxes[sel.value].appendChild(c); save(); }}, [el('option', {value: '', text: q.bank_label || T.items})]);
      q.groups.forEach(function (gr) { sel.appendChild(el('option', {value: gr.id, text: gr.label.replace(/<[^>]+>/g, '')})); });
      var c = el('div', {'class': 'chip', draggable: 'true', 'data-i': i}, [el('span', {html: it.label}), sel]);
      c.addEventListener('dragstart', function () { drag = c; c.classList.add('drag'); });
      c.addEventListener('dragend', function () { c.classList.remove('drag'); sel.value = c.parentNode.dataset.group || ''; save(); });
      c.addEventListener('dragover', function (e) { e.preventDefault(); if (q.rank_within && drag && drag !== c) { var r = c.getBoundingClientRect(); c.parentNode.insertBefore(drag, (e.clientY - r.top) > r.height / 2 ? c.nextSibling : c); } });
      sel.value = where[String(it.value)] || ''; return c;
    }
    for (var k in boxes) (function (b) {
      b.addEventListener('dragover', function (e) { e.preventDefault(); b.classList.add('over'); });
      b.addEventListener('dragleave', function () { b.classList.remove('over'); });
      b.addEventListener('drop', function (e) { e.preventDefault(); b.classList.remove('over'); if (drag && drag.parentNode !== b && !(q.rank_within && e.target.closest('.chip'))) b.appendChild(drag); save(); });
    })(boxes[k]);
    var order = q.items.map(function (it, i) { return i; });
    q.groups.forEach(function (gr) { (ans[q.id][gr.id] || []).forEach(function (v) { var i = q.items.map(function (x) { return String(x.value); }).indexOf(String(v)); if (i >= 0) boxes[gr.id].appendChild(chip(i)); }); });
    order.forEach(function (i) { if (!where[String(q.items[i].value)]) bank.appendChild(chip(i)); });
    save();
    return [wrap, el('div', {'class': 'help', style: 'margin:6px 0 0', text: q.rank_within ? T.group_rank : T.group})];
  },
  hot_spot: function (q) {
    ans[q.id] = ans[q.id] || {};
    var box = el('div', {'class': 'imgbox'}, [el('img', {src: url(q.image), alt: q.alt || '', draggable: 'false'})]);
    q.regions.forEach(function (r) {
      var b = el('button', {type: 'button', 'class': 'spot', title: r.label || r.id, 'aria-label': r.label || r.id,
        style: 'inset-inline-start:' + r.x + '%;top:' + r.y + '%;width:' + r.w + '%;height:' + r.h + '%', onclick: function () {
          var cur = ans[q.id][r.id] || 0, next;
          if (q.mode === 'rate') next = cur === 0 ? 1 : (cur === 1 ? -1 : 0);
          else { next = cur ? 0 : 1; if (next && q.max_select) { var n = 0; for (var k in ans[q.id]) n += ans[q.id][k] ? 1 : 0; if (n >= q.max_select) return; } }
          ans[q.id][r.id] = next; paint(); refreshVisibility(); }}, [q.show_labels ? (r.label || '') : '']);
      box.appendChild(b);
      function paint() { var v = ans[q.id][r.id] || 0; b.className = 'spot' + (q.mode === 'rate' ? (v === 1 ? ' like' : v === -1 ? ' dislike' : '') : (v ? ' on' : '')); }
      paint();
    });
    return [box, el('div', {'class': 'help', style: 'margin:6px 0 0', text: q.mode === 'rate' ? T.hotspot_rate : T.hotspot})];
  },
  heat_map: function (q) {
    ans[q.id] = ans[q.id] || [];
    var img = el('img', {src: url(q.image), alt: q.alt || '', draggable: 'false'}), box = el('div', {'class': 'imgbox heat'}, [img]);
    function draw() { box.querySelectorAll('.dot').forEach(function (d) { d.remove(); });
      ans[q.id].forEach(function (p) { box.appendChild(el('span', {'class': 'dot', style: 'left:' + (p[0] * 100) + '%;top:' + (p[1] * 100) + '%'})); }); }
    box.addEventListener('click', function (e) { var r = img.getBoundingClientRect();
      var p = [clamp((e.clientX - r.left) / r.width, 0, 1), clamp((e.clientY - r.top) / r.height, 0, 1)].map(function (x) { return Math.round(x * 10000) / 10000; });
      var list = ans[q.id].slice(); list.push(p); while (list.length > (q.max_clicks || 1)) list.shift(); setv(q.id, list); draw(); });
    draw();
    return [box, el('div', {'class': 'tools'}, [el('span', {'class': 'help', style: 'margin:0', text: fmt(T.heat, {n: q.max_clicks || 1})}),
      el('button', {type: 'button', 'class': 'mini', onclick: function () { setv(q.id, []); draw(); }}, [T.clear])])];
  },
  location: function (q) {
    ans[q.id] = ans[q.id] || {};
    var out = [], info = el('div', {'class': 'help', style: 'margin:6px 0 0'});
    function show() { var a = ans[q.id]; info.textContent = empty(a) ? T.loc_none : (a.lat !== undefined ? fmt(T.loc_at, {lat: a.lat.toFixed(5), lon: a.lon.toFixed(5)}) : T.loc_marked); }
    if (q.image) {
      var img = el('img', {src: url(q.image), alt: q.alt || '', draggable: 'false'}), box = el('div', {'class': 'imgbox heat'}, [img]);
      var dot = null;
      function draw() { if (dot) dot.remove(); var a = ans[q.id]; if (a.x !== undefined) { dot = el('span', {'class': 'dot', style: 'left:' + (a.x * 100) + '%;top:' + (a.y * 100) + '%'}); box.appendChild(dot); } }
      box.addEventListener('click', function (e) { var r = img.getBoundingClientRect(), x = clamp((e.clientX - r.left) / r.width, 0, 1), y = clamp((e.clientY - r.top) / r.height, 0, 1);
        var a = {x: Math.round(x * 10000) / 10000, y: Math.round(y * 10000) / 10000, source: 'map'};
        if (q.bounds) { var b = q.bounds; a.lat = b.north - y * (b.north - b.south); a.lon = b.west + x * (b.east - b.west); }
        setv(q.id, a); draw(); show(); });
      draw(); out.push(box);
    }
    if (q.allow_geolocation && navigator.geolocation) out.push(el('div', {'class': 'tools'}, [el('button', {type: 'button', 'class': 'mini', onclick: function () {
      info.textContent = T.loc_wait;
      navigator.geolocation.getCurrentPosition(function (p) { setv(q.id, {lat: p.coords.latitude, lon: p.coords.longitude, accuracy: Math.round(p.coords.accuracy), source: 'gps'}); show(); },
        function () { info.textContent = T.loc_fail; }, {enableHighAccuracy: true, timeout: 15000}); }}, [T.loc_here])]));
    out.push(info); show(); return out;
  },
  drill_down: function (q) {
    ans[q.id] = ans[q.id] || [];
    var box = el('div', {}), sels = [];
    function opts(level) { var node = q.tree; for (var i = 0; i < level; i++) { if (!node || Array.isArray(node)) return []; node = node[ans[q.id][i]]; }
      if (!node) return []; return Array.isArray(node) ? node : Object.keys(node); }
    function render() {
      box.innerHTML = '';
      q.levels.forEach(function (lab, i) {
        var choices = i === 0 || !empty(ans[q.id][i - 1]) ? opts(i) : [];
        var sel = el('select', {disabled: !choices.length, 'aria-label': lab, onchange: function () { var a = ans[q.id].slice(0, i); if (sel.value) a[i] = sel.value; setv(q.id, a); render(); }},
          [el('option', {value: '', text: lab + ' …'})]);
        choices.forEach(function (c) { sel.appendChild(el('option', {value: String(c), text: String(c)})); });
        if (ans[q.id][i] !== undefined) sel.value = ans[q.id][i];
        box.appendChild(el('div', {style: 'margin:0 0 8px'}, [el('label', {'class': 'help', style: 'margin:0;display:block', text: lab}), sel]));
      });
    }
    render(); return [box];
  },
  highlight: function (q) {
    ans[q.id] = ans[q.id] || {};
    var cats = q.categories, cur = cats[0].id, catBox = el('div', {'class': 'hl-cats'}), txt = el('div', {'class': 'hl-text'}), dragging = false;
    function color(id) { var c = cats.filter(function (x) { return x.id === id; })[0]; return c ? c.color : ''; }
    cats.forEach(function (c) { catBox.appendChild(el('button', {type: 'button', style: 'background:' + c.color, 'class': c.id === cur ? 'sel' : '', onclick: function (e) {
      cur = c.id; [].forEach.call(catBox.children, function (b) { b.classList.remove('sel'); }); e.target.classList.add('sel'); }}, [c.label])); });
    var tokens = String(q.passage || '').split(/(\s+)/);
    tokens.forEach(function (tk, i) {
      if (/^\s+$/.test(tk) || tk === '') { txt.appendChild(document.createTextNode(tk)); return; }
      var w = el('span', {'class': 'w', 'data-i': i, text: tk});
      function apply(toggle) { var v = ans[q.id][i]; if (toggle && v === cur) delete ans[q.id][i]; else ans[q.id][i] = cur; w.style.background = color(ans[q.id][i]) || ''; }
      w.addEventListener('mousedown', function (e) { e.preventDefault(); dragging = true; apply(true); refreshVisibility(); });
      w.addEventListener('mouseenter', function () { if (dragging) { ans[q.id][i] = cur; w.style.background = color(cur); } });
      w.style.background = color(ans[q.id][i]) || '';
      txt.appendChild(w);
    });
    document.addEventListener('mouseup', function () { dragging = false; });
    ans[q.id + '__tokens'] = tokens;
    return [catBox, txt, el('div', {'class': 'help', style: 'margin:6px 0 0', text: T.highlight})];
  },
  signature: function (q) {
    var cv = el('canvas', {'class': 'sign', width: 560, height: 180, 'aria-label': T.sign}), ctx = cv.getContext('2d'), down = false, drawn = false;
    function pos(e) { var r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; }
    ctx.lineWidth = 2.5; ctx.lineCap = 'round'; ctx.strokeStyle = '#111';
    cv.addEventListener('pointerdown', function (e) { down = true; cv.setPointerCapture(e.pointerId); var p = pos(e); ctx.beginPath(); ctx.moveTo(p[0], p[1]); });
    cv.addEventListener('pointermove', function (e) { if (!down) return; var p = pos(e); ctx.lineTo(p[0], p[1]); ctx.stroke(); drawn = true; });
    cv.addEventListener('pointerup', function () { down = false; if (drawn) setv(q.id, cv.toDataURL('image/png')); });
    if (ans[q.id]) { var im = new Image(); im.onload = function () { ctx.drawImage(im, 0, 0); drawn = true; }; im.src = ans[q.id]; }
    return [cv, el('div', {'class': 'tools'}, [el('span', {'class': 'help', style: 'margin:0', text: T.sign}),
      el('button', {type: 'button', 'class': 'mini', onclick: function () { ctx.clearRect(0, 0, cv.width, cv.height); drawn = false; setv(q.id, ''); }}, [T.clear])])];
  },
  file_upload: function (q) {
    var info = el('div', {'class': 'help', style: 'margin:6px 0 0', text: ans[q.id] ? fmt(T.file_ok, {name: ans[q.id].name}) : fmt(T.file_max, {mb: q.max_mb || 10})});
    var inp = el('input', {type: 'file', accept: q.accept || null, onchange: function () {
      var f = inp.files[0]; if (!f) return;
      if (f.size > (q.max_mb || 10) * 1048576) { info.textContent = fmt(T.file_big, {mb: q.max_mb || 10}); inp.value = ''; return; }
      readFile(f, function (data) { setv(q.id, {name: f.name, size: f.size, type: f.type, data: data}); info.textContent = fmt(T.file_ok, {name: f.name}); }); }});
    return [inp, info];
  },
  video_response: function (q) {
    var video = el('video', {'class': 'rec', playsinline: true, muted: true}), status = el('div', {'class': 'help', style: 'margin:6px 0 0'}), stream = null, rec = null, chunks = [], started = 0, timer = null;
    if (q.audio_only) video.style.display = 'none';
    var bStart = el('button', {type: 'button', 'class': 'mini'}, [T.rec_start]), bStop = el('button', {type: 'button', 'class': 'mini', disabled: true}, [T.rec_stop]);
    function stopAll() { if (rec && rec.state !== 'inactive') rec.stop(); clearInterval(timer); }
    bStart.onclick = function () {
      if (!navigator.mediaDevices || !window.MediaRecorder) { status.textContent = T.rec_unsupported; return; }
      navigator.mediaDevices.getUserMedia({audio: true, video: !q.audio_only}).then(function (s) {
        stream = s; video.srcObject = s; video.muted = true; video.play(); chunks = []; rec = new MediaRecorder(s);
        rec.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
        rec.onstop = function () { s.getTracks().forEach(function (t) { t.stop(); }); var blob = new Blob(chunks, {type: rec.mimeType || 'video/webm'}), dur = (Date.now() - started) / 1000;
          video.srcObject = null; video.src = URL.createObjectURL(blob); video.muted = false; video.controls = true; if (q.audio_only) { video.style.display = ''; video.style.height = '50px'; }
          readFile(blob, function (data) { setv(q.id, {data: data, type: blob.type, duration: Math.round(dur * 10) / 10, name: q.id + (q.audio_only ? '.webm' : '.webm')}); });
          status.textContent = fmt(T.rec_done, {s: Math.round(dur)}); bStart.disabled = false; bStart.textContent = T.rec_again; bStop.disabled = true; };
        rec.start(); started = Date.now(); bStart.disabled = true; bStop.disabled = false;
        timer = setInterval(function () { var s2 = (Date.now() - started) / 1000; status.innerHTML = '<span class="recdot">●</span> ' + Math.floor(s2) + ' s' + (q.max_seconds ? ' / ' + q.max_seconds + ' s' : '');
          if (q.max_seconds && s2 >= q.max_seconds) stopAll(); }, 250);
      }, function () { status.textContent = T.rec_denied; });
    };
    bStop.onclick = function () { var s2 = (Date.now() - started) / 1000; if (q.min_seconds && s2 < q.min_seconds) { status.textContent = fmt(T.rec_short, {s: q.min_seconds}); return; } stopAll(); };
    if (ans[q.id]) { video.src = ans[q.id].data; video.controls = true; video.muted = false; status.textContent = fmt(T.rec_done, {s: Math.round(ans[q.id].duration || 0)}); }
    return [video, el('div', {'class': 'tools'}, [bStart, bStop]), status];
  },
  screen_capture: function (q) {
    var cv = el('canvas', {'class': 'shot'}), ctx = cv.getContext('2d'), status = el('div', {'class': 'help', style: 'margin:6px 0 0', text: T.shot_hint}), base = null, boxes = [], drag = null;
    cv.style.display = 'none';
    function redraw() { if (!base) return; ctx.drawImage(base, 0, 0); ctx.fillStyle = '#000'; boxes.forEach(function (b) { ctx.fillRect(b[0], b[1], b[2], b[3]); });
      if (drag) ctx.fillRect(drag[0], drag[1], drag[2], drag[3]); }
    function save() { setv(q.id, {data: cv.toDataURL('image/png'), name: q.id + '.png', boxes: boxes.length}); }
    function pos(e) { var r = cv.getBoundingClientRect(); return [(e.clientX - r.left) * cv.width / r.width, (e.clientY - r.top) * cv.height / r.height]; }
    cv.addEventListener('pointerdown', function (e) { var p = pos(e); drag = [p[0], p[1], 0, 0]; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener('pointermove', function (e) { if (!drag) return; var p = pos(e); drag[2] = p[0] - drag[0]; drag[3] = p[1] - drag[1]; redraw(); });
    cv.addEventListener('pointerup', function () { if (drag && Math.abs(drag[2]) > 3 && Math.abs(drag[3]) > 3) boxes.push(drag); drag = null; redraw(); save(); });
    var bCap = el('button', {type: 'button', 'class': 'mini', onclick: function () {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) { status.textContent = T.shot_unsupported; return; }
      navigator.mediaDevices.getDisplayMedia({video: true}).then(function (s) {
        var v = el('video', {muted: true, playsinline: true}); v.srcObject = s;
        v.onloadedmetadata = function () { v.play(); setTimeout(function () {
          cv.width = v.videoWidth; cv.height = v.videoHeight; ctx.drawImage(v, 0, 0); s.getTracks().forEach(function (t) { t.stop(); });
          base = new Image(); base.onload = function () { boxes = []; redraw(); save(); cv.style.display = ''; status.textContent = T.shot_black; }; base.src = cv.toDataURL('image/png'); }, 300); };
      }, function () { status.textContent = T.shot_denied; }); }}, [T.shot_take]);
    var bUndo = el('button', {type: 'button', 'class': 'mini', onclick: function () { boxes.pop(); redraw(); if (base) save(); }}, [T.undo]);
    return [el('div', {'class': 'tools'}, [bCap, bUndo]), cv, status];
  },
  captcha: function (q) {
    var cv = el('canvas', {'class': 'captcha', width: 220, height: 70, 'aria-label': T.captcha}), code = '', tries = 0;
    var chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
    function make() { code = ''; for (var i = 0; i < (q.length || 5); i++) code += chars[Math.floor(Math.random() * chars.length)];
      var c = cv.getContext('2d'); c.fillStyle = '#f2f4f7'; c.fillRect(0, 0, 220, 70);
      for (var j = 0; j < 7; j++) { c.strokeStyle = 'hsl(' + Math.random() * 360 + ',40%,60%)'; c.beginPath(); c.moveTo(Math.random() * 220, Math.random() * 70); c.lineTo(Math.random() * 220, Math.random() * 70); c.stroke(); }
      for (var k = 0; k < code.length; k++) { c.save(); c.translate(22 + k * 38, 45 + Math.random() * 8); c.rotate((Math.random() - .5) * .6);
        c.font = 'bold ' + (28 + Math.random() * 8) + 'px monospace'; c.fillStyle = 'hsl(' + Math.random() * 360 + ',50%,30%)'; c.fillText(code[k], 0, 0); c.restore(); }
      ans[q.id] = ''; }
    var inp = el('input', {type: 'text', autocomplete: 'off', style: 'max-width:200px;letter-spacing:3px;text-transform:uppercase', 'aria-label': T.captcha,
      oninput: function () { ans[q.id + '__typed'] = inp.value; }});
    make();
    q.__check = function () { tries++; ans[q.id + '_attempts'] = tries;
      if (inp.value.trim().toUpperCase() === code) { ans[q.id] = 1; return ''; }
      make(); inp.value = ''; return T.captcha_wrong; };
    return [cv, el('div', {'class': 'tools'}, [inp, el('button', {type: 'button', 'class': 'mini', onclick: make}, ['↻ ' + T.captcha_new])])];
  },
  tree_test: function (q) {
    ans[q.id] = ans[q.id] || {clicks: 0, visited: []};
    var a = ans[q.id], shown = Date.now(), chosen = el('div', {'class': 'chosen'});
    function build(node, path) {
      var ul = el('ul', {'class': path.length ? '' : 'tree'});
      var keys = Array.isArray(node) ? node : Object.keys(node);
      keys.forEach(function (k) {
        var child = Array.isArray(node) ? null : node[k], p = path.concat([String(k)]), leaf = !child || (Array.isArray(child) && !child.length) || (typeof child === 'object' && !Array.isArray(child) && !Object.keys(child).length);
        var li = el('li'), sub = null;
        var btn = el('button', {type: 'button', 'class': 'node', onclick: function () {
          a.clicks++; a.visited.push(p.join(' > '));
          if (!leaf && !q.select_any) { if (!sub) { sub = build(child, p); li.appendChild(sub); } else { sub.style.display = sub.style.display === 'none' ? '' : 'none'; } return; }
          if (!leaf && q.select_any && !sub) { sub = build(child, p); li.appendChild(sub); }
          root.querySelectorAll('.tree button.node.sel').forEach(function (b) { b.classList.remove('sel'); }); btn.classList.add('sel');
          a.path = p; a.time = Math.round((Date.now() - shown)) / 1000; chosen.textContent = T.tree_answer + ' ' + p.join(' › '); refreshVisibility(); }},
          [el('span', {'class': 'caret', text: leaf ? '' : '›'}), String(k)]);
        li.appendChild(btn); ul.appendChild(li);
      });
      return ul;
    }
    if (a.path) chosen.textContent = T.tree_answer + ' ' + a.path.join(' › ');
    return [el('div', {'class': 'task', html: pipe(q.task || '')}), build(q.tree, []), chosen];
  },
  timing: function (q) { return []; },
  meta_info: function (q) { return []; },
  page_break: function () { return []; },
};

/* ------------------------------------------------------------------ checks */
function sumOk(q, s) { var t = +(q.total || 100), m = q.must_total || 'exact'; return m === 'exact' ? s === t : m === 'at_most' ? s <= t : s >= t; }
function syncRank(q) { var r = ans[q.id + '__ranks'], order = Object.keys(r).filter(function (k) { return r[k] !== ''; }).sort(function (a, b) { return r[a] - r[b]; });
  ans[q.id] = order.map(function (k) { var o = q.options.filter(function (x) { return String(x.value) === k; })[0]; return o ? o.value : k; }); refreshVisibility(); }
function problem(q, card) {
  var t = q.type, a = ans[q.id];
  if (t === 'matrix' || t === 'semantic' || (t === 'scale' && q.items) || (t === 'slider' && q.items)) {
    var miss = q.items.filter(function (it) { return empty(ans[it.id]); });
    card.querySelectorAll('tr[data-item],div[data-item]').forEach(function (r) { r.classList.toggle('miss', !!q.required && empty(ans[r.dataset.item])); });
    if (q.required && miss.length) return miss.length === q.items.length ? (t === 'slider' ? T.slider : T.required) : fmt(T.rows, {n: miss.length});
    if (q.multi && (q.min_choices || q.max_choices)) for (var i = 0; i < q.items.length; i++) { var n = (ans[q.items[i].id] || []).length;
      if (n && q.min_choices && n < q.min_choices) return fmt(T.min, {n: q.min_choices}); if (q.max_choices && n > q.max_choices) return fmt(T.max, {n: q.max_choices}); }
    return '';
  }
  if (t === 'side_by_side') { if (!q.required) return ''; var missing = 0;
    q.items.forEach(function (it) { q.columns.forEach(function (c) { if (empty(ans[it.id + '_' + c.id])) missing++; }); });
    return missing ? fmt(T.cells, {n: missing}) : ''; }
  if (t === 'form') { var bad = '';
    q.fields.forEach(function (f) { var v = ans[f.id], m = '';
      if (empty(v)) m = f.required ? T.required_short : '';
      else if (f.type === 'email' && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) m = T.email;
      else if (f.type === 'url' && !/^https?:\/\/\S+\.\S+/.test(v)) m = T.url;
      else if (f.type === 'tel' && !/^[+()\d\s.\/-]{5,}$/.test(v)) m = T.tel;
      else if (f.type === 'number' && isNaN(Number(v))) m = T.number;
      else if (f.min_length && String(v).length < f.min_length) m = fmt(T.short, {n: f.min_length});
      else if (f.pattern && !(new RegExp('^(?:' + f.pattern + ')$')).test(v)) m = f.pattern_message || T.format;
      var box = card.querySelector('.ferr[data-field="' + f.id + '"]'); if (box) box.textContent = m; if (m && !bad) bad = T.fix_fields; });
    return bad; }
  if (t === 'constant_sum') { var s = 0, any = false; for (var k in a) { if (a[k] !== '') { any = true; s += +a[k]; } }
    if (!any) return q.required ? T.required : ''; return sumOk(q, s) ? '' : fmt({exact: T.sum, at_most: T.sum_max, at_least: T.sum_min}[q.must_total || 'exact'], {total: q.total || 100}); }
  if (t === 'rank') { if (q.method === 'select' || q.method === 'text') { var r = ans[q.id + '__ranks'] || {}, vals = [], n2 = q.options.length;
      for (var kk in r) if (r[kk] !== '') vals.push(r[kk]);
      if (!vals.length) return q.required ? T.required : '';
      if (vals.length < n2 || vals.some(function (v) { return v < 1 || v > n2 || Math.round(v) !== v; }) || new Set(vals).size !== vals.length) return fmt(T.rank_bad, {n: n2}); }
    return ''; }
  if (t === 'group') { var placed = 0; for (var g in a) placed += a[g].length;
    if (q.required && !placed) return T.required;
    if (q.require_all && placed < q.items.length) return T.group_all; return ''; }
  if (t === 'hot_spot') { var on = 0; for (var h in a) on += a[h] ? 1 : 0; if (q.required && !on) return T.required;
    if (q.min_select && on < q.min_select) return fmt(T.min, {n: q.min_select}); return ''; }
  if (t === 'highlight') { if (q.required && empty(a)) return T.hl_required; return ''; }
  if (t === 'tree_test') return q.required && !(a && a.path) ? T.tree_required : '';
  if (t === 'captcha') return q.__check ? q.__check() : '';
  if (t === 'timing' || t === 'meta_info') return '';
  if (t === 'location') return q.required && empty(a) ? T.loc_required : '';
  if (t === 'drill_down') return q.required && (a || []).length < q.levels.length ? T.required : '';
  if (empty(a)) return q.required ? ({slider: T.slider, graphic_slider: T.required, signature: T.sign_required, file_upload: T.file_required, video_response: T.rec_required, screen_capture: T.shot_required}[t] || T.required) : '';
  if (t === 'multiple') { if (q.min_choices && a.length < q.min_choices) return fmt(T.min, {n: q.min_choices}); if (q.max_choices && a.length > q.max_choices) return fmt(T.max, {n: q.max_choices}); }
  if (t === 'number' || (t === 'text' && (q.validate === 'number' || q.validate === 'integer'))) { var x = Number(a); if (isNaN(x) || (q.validate === 'integer' && Math.round(x) !== x)) return T.number;
    if (q.min !== undefined && x < q.min) return fmt(T.low, {n: q.min}); if (q.max !== undefined && x > q.max) return fmt(T.high, {n: q.max}); }
  if (t === 'date') { if (q.min && a < q.min) return fmt(T.date_min, {d: q.min}); if (q.max && a > q.max) return fmt(T.date_max, {d: q.max}); }
  if (t === 'text' && q.validate === 'email' && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(a)) return T.email;
  if ((t === 'text' || t === 'essay') && q.min_length && String(a).length < q.min_length) return fmt(T.short, {n: q.min_length});
  if (t === 'text' && q.pattern && !(new RegExp('^(?:' + q.pattern + ')$')).test(a)) return q.pattern_message || T.format;
  if (t === 'autocomplete' && !q.free_text && empty(a)) return T.pick_list;
  if (q.other_option && labelOf(q.id) === q.other_option && empty(ans[q.id + '_other'])) return T.other_missing;
  return '';
}

/* ------------------------------------------------------------------ pages */
function build(q) {
  var make = BUILD[q.type]; if (!make) return el('div', {'class': 'q', text: 'Unknown question type: ' + q.type});
  var body = make(q) || [];
  if (q.type === 'text_block') return el('div', {'class': 'q block', 'data-q': q.id || ''}, body);
  if (q.type === 'timing' || q.type === 'meta_info') return el('div', {'class': 'timing', 'data-q': q.id || ''});
  return el('div', {'class': 'q', 'data-q': q.id || ''}, [el('div', {'class': 'qt', html: pipe(q.text)}, [q.required ? el('span', {'class': 'req', text: '*'}) : null]),
    q.help ? el('div', {'class': 'help', html: q.help}) : null].concat(body).concat([el('div', {'class': 'msg', role: 'alert'})]));
}
function refreshVisibility() {
  cards.forEach(function (c) { var show = holds(c.q.show_if); c.el.style.display = show ? '' : 'none';
    if (c.q.type === 'timing' || c.q.type === 'meta_info') c.el.style.display = 'none';
    var qt = c.el.querySelector('.qt');
    if (qt && c.q.text && c.q.text.indexOf('{{answer.') >= 0) { var req = qt.querySelector('.req'); qt.innerHTML = pipe(c.q.text); if (req) qt.appendChild(req); } });
}
function check(err) {
  var bad = null;
  cards.forEach(function (c) { var visible = c.el.style.display !== 'none' || c.q.type === 'timing' || c.q.type === 'meta_info';
    if (!holds(c.q.show_if)) visible = false;
    var m = visible ? problem(c.q, c.el) : ''; c.el.classList.toggle('err', !!m); var box = c.el.querySelector('.msg'); if (box) box.textContent = m; if (m && !bad) bad = c.el; });
  err.textContent = bad ? T.fix : ''; if (bad) bad.scrollIntoView({behavior: 'smooth', block: 'center'}); return !bad;
}
function leave() {
  var k = 'page' + (page + 1) + '_time'; times[k] = (times[k] || 0) + (Date.now() - t0) / 1000;
  pageTimers.forEach(clearInterval); pageTimers = [];
  cards.forEach(function (c) { if (c.q.type === 'timing') { var lg = clickLog;
    ans[c.q.id] = {first_click: lg.length ? lg[0] : null, last_click: lg.length ? lg[lg.length - 1] : null, submit: Math.round(Date.now() - t0) / 1000, clicks: lg.length}; } });
}
function show(p) {
  page = p; root.innerHTML = ''; cards = []; clickLog = [];
  if (S.title && p === 0) root.appendChild(el('h1', {'class': 'title', html: S.title}));
  if (S.intro && p === 0) root.appendChild(el('p', {'class': 'intro', html: pipe(S.intro)}));
  if (S.progress && S.pages.length > 1) root.appendChild(el('div', {'class': 'progress', role: 'progressbar', 'aria-valuenow': Math.round(100 * p / S.pages.length)}, [el('div', {style: 'width:' + Math.round(100 * p / S.pages.length) + '%'})]));
  S.pages[p].forEach(function (q) { var c = build(q); cards.push({q: q, el: c}); root.appendChild(c); });
  refreshVisibility();
  var last = p === S.pages.length - 1, err = el('div', {'class': 'pageerr', role: 'alert'});
  var next = el('button', {type: 'button', 'class': 'primary', onclick: function () { go(true); }}, [last ? T.submit : T.next]);
  function go(validate) { if (validate && !check(err)) return; leave(); if (last) finish(); else show(p + 1); }
  var nav = el('div', {'class': 'nav'}, [(p > 0 && S.back) ? el('button', {type: 'button', onclick: function () { leave(); show(p - 1); }}, [T.back]) : null, next]);
  root.appendChild(nav); root.appendChild(err); window.scrollTo(0, 0); t0 = Date.now();
  // timing questions: minimum time before Next, automatic advance after a maximum
  cards.forEach(function (c) { var q = c.q; if (q.type !== 'timing') return;
    if (q.min_seconds) { next.disabled = true; var lab = next.textContent;
      pageTimers.push(setInterval(function () { var left = Math.ceil(q.min_seconds - (Date.now() - t0) / 1000);
        if (left <= 0) { next.disabled = false; next.textContent = lab; } else if (q.show_countdown !== false) next.textContent = lab + ' (' + left + ')'; }, 200)); }
    if (q.max_seconds) pageTimers.push(setInterval(function () { if ((Date.now() - t0) / 1000 >= q.max_seconds) go(false); }, 200)); });
}
document.addEventListener('click', function () { clickLog.push(Math.round(Date.now() - t0) / 1000); }, true);
function meta() {
  var ua = navigator.userAgent, br = /Edg\//.test(ua) ? 'Edge' : /OPR\//.test(ua) ? 'Opera' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome' : /Safari\//.test(ua) ? 'Safari' : 'other';
  var ver = (ua.match(/(Edg|OPR|Firefox|Chrome|Version)\/([\d.]+)/) || [])[2] || '';
  var os = /Windows/.test(ua) ? 'Windows' : /Mac OS X/.test(ua) && !/Mobile/.test(ua) ? 'macOS' : /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iOS' : /Linux/.test(ua) ? 'Linux' : 'other';
  var tz = ''; try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch (e) {}
  return {browser: br + (ver ? ' ' + ver : ''), os: os, screen: screen.width + 'x' + screen.height, viewport: innerWidth + 'x' + innerHeight,
          pixel_ratio: window.devicePixelRatio || 1, language: navigator.language || '', timezone: tz, touch: ('ontouchstart' in window) ? 1 : 0, user_agent: ua};
}
function finish() {
  var out = {};
  S.flat.forEach(function (q) {
    if (q.type === 'meta_info') { out[q.id] = meta(); return; }
    if (!holds(q.show_if)) return;
    var keys = [];
    if (q.items && ['matrix', 'semantic', 'scale', 'slider'].indexOf(q.type) >= 0) keys = ids(q);
    else if (q.type === 'side_by_side') q.items.forEach(function (it) { q.columns.forEach(function (c) { keys.push(it.id + '_' + c.id); }); });
    else if (q.type === 'form') keys = q.fields.map(function (f) { return f.id; });
    else if (q.id) keys = [q.id];
    keys.forEach(function (id) { if (id in ans) out[id] = ans[id]; });
    if (q.other_option && ans[q.id + '_other']) out[q.id + '_other'] = ans[q.id + '_other'];
    if (q.type === 'captcha') out[q.id + '_attempts'] = ans[q.id + '_attempts'] || 0;
    if (q.type === 'highlight' && ans[q.id]) { var words = ans[q.id + '__tokens'], hl = {};
      for (var i in ans[q.id]) (hl[ans[q.id][i]] = hl[ans[q.id][i]] || []).push(words[i]); out[q.id] = hl; }
  });
  for (var k in times) out[k] = Math.round(times[k] * 100) / 100;
  window.edge.submit(out);
}
show(0);
})();
