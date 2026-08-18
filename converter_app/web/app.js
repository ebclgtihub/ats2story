'use strict';

const $ = (id) => document.getElementById(id);
let slidesList = [];   // Folien der Großansicht (ohne Fragen), s. openLightbox
let lbPos = 0;         // aktuelle Position in der Großansicht

function errMsg(e) {
  return e instanceof Error ? e.message : String(e);
}

// --- Theme (hell/dunkel, persistent) --------------------------------------
const THEME_KEY = 'ats-theme';
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  $('btnTheme').textContent = t === 'dark' ? '☀' : '☾';
}
function initTheme() {
  let t = 'light';
  try { t = localStorage.getItem(THEME_KEY) || 'light'; } catch (e) { /* ignore */ }
  applyTheme(t);
}
$('btnTheme').addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* ignore */ }
});
initTheme();

// --- Inhaltsbaum + Bühne ---------------------------------------------------
// Der Kurs IST ein Baum: Kapitel mit Folien, dazu das Depot mit den Fragen
// (imc zeigt es genauso). Links wird ausgewählt, in der Mitte steht die
// Vorschau — Folien als Bild, Fragen als Text, weil dort Frage und Optionen
// mehr sagen als das Vorschaubild.
let entries = [];      // flache Liste in Anzeigereihenfolge (für Blättern)
let current = -1;      // Position in `entries`


function renderNav(list) {
  const nav = $('nav');
  nav.textContent = '';
  entries = [];

  const content = list.filter((t) => !t.quiz);
  const quiz = list.filter((t) => t.quiz);

  if (content.length) {
    nav.appendChild(navSection('Inhalt', groupByScene(content), false));
  }
  if (quiz.length) {
    nav.appendChild(navSection('Fragen-Depot', groupDepot(quiz), true, quiz.length));
  }
  if (entries.length) select(0);
}

function groupByScene(list) {
  const out = [];
  for (const t of list) {
    const last = out[out.length - 1];
    if (last && last.name === t.scene) last.items.push(t);
    else out.push({ name: t.scene, items: [t] });
  }
  return out;
}

// Depot-Ordner wie in imc: „Buch / Test Übung 1" -> Buch > Test Übung 1
function groupDepot(list) {
  const tops = new Map();
  for (const t of list) {
    const parts = String(t.scene).split(' / ');
    const top = parts.length > 1 ? parts[0] : 'Ohne Ordner';
    const sub = parts.length > 1 ? parts.slice(1).join(' / ') : parts[0];
    if (!tops.has(top)) tops.set(top, new Map());
    const m = tops.get(top);
    if (!m.has(sub)) m.set(sub, []);
    m.get(sub).push(t);
  }
  const out = [];
  for (const [top, subs] of tops) {
    for (const [sub, items] of subs) {
      out.push({ name: sub, group: top, items });
    }
  }
  return out;
}

function navSection(title, groups, isQuiz, total) {
  const sec = document.createElement('section');
  sec.className = 'nav-sec' + (isQuiz ? ' is-quiz' : '');

  const h = document.createElement('div');
  h.className = 'nav-sec-head';
  const label = document.createElement('span');
  label.textContent = title;
  h.appendChild(label);
  if (total) {
    const n = document.createElement('span');
    n.className = 'nav-n num';
    n.textContent = total;
    h.appendChild(n);
  }
  sec.appendChild(h);

  if (isQuiz) {
    const note = document.createElement('p');
    note.className = 'nav-note';
    note.textContent = 'Geht als Excel-Datei heraus — in Storyline über '
      + 'Datei › Import › Fragen aus Datei einlesen.';
    sec.appendChild(note);
  }

  let lastGroup = null;
  for (const g of groups) {
    if (g.group && g.group !== lastGroup) {
      lastGroup = g.group;
      const gh = document.createElement('div');
      gh.className = 'nav-group';
      gh.textContent = g.group;
      sec.appendChild(gh);
    }
    const det = document.createElement('details');
    det.className = 'nav-folder';
    det.open = groups.length <= 3;
    const sum = document.createElement('summary');
    const nm = document.createElement('span');
    nm.textContent = g.name;
    const n = document.createElement('span');
    n.className = 'nav-n num';
    n.textContent = g.items.length;
    sum.append(nm, n);
    det.appendChild(sum);

    const ul = document.createElement('ul');
    for (const t of g.items) {
      const pos = entries.length;
      entries.push(t);
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.className = 'nav-item';
      btn.dataset.pos = pos;
      const num = document.createElement('span');
      num.className = 'nav-idx num';
      num.textContent = t.index;
      const nam = document.createElement('span');
      nam.className = 'nav-name';
      nam.textContent = t.name;
      btn.append(num, nam);
      if (t.q) {
        const tag = document.createElement('span');
        tag.className = 'nav-tag';
        tag.textContent = t.q.type;
        btn.appendChild(tag);
      }
      btn.addEventListener('click', () => select(pos));
      li.appendChild(btn);
      ul.appendChild(li);
    }
    det.appendChild(ul);
    sec.appendChild(det);
  }
  return sec;
}

function select(pos) {
  if (pos < 0 || pos >= entries.length) return;
  current = pos;
  const t = entries[pos];

  for (const b of document.querySelectorAll('.nav-item')) {
    b.classList.toggle('is-sel', Number(b.dataset.pos) === pos);
  }
  const sel = document.querySelector('.nav-item.is-sel');
  if (sel) {
    const det = sel.closest('details');
    if (det && !det.open) det.open = true;
    sel.scrollIntoView({ block: 'nearest' });
  }

  $('stageCap').textContent = `${t.index}. ${t.name}`;
  $('stagePrev').disabled = pos === 0;
  $('stageNext').disabled = pos === entries.length - 1;
  const img = $('stageImg');
  const empty = $('stageEmpty');
  const old = document.querySelector('.stage-text');
  if (old) old.remove();

  if (t.q) {
    // Fragen: Textvorschau statt Bild — Frage und Optionen sagen mehr.
    img.classList.add('hidden');
    empty.classList.add('hidden');
    $('stageZoom').disabled = true;
    document.querySelector('.stage-frame').appendChild(questionView(t.q));
  } else {
    $('stageZoom').disabled = false;
    empty.classList.add('hidden');
    img.classList.remove('hidden');
    img.src = `/full/${t.index}`;
    // Der Fehler-Handler feuert ASYNCHRON. Ohne diese Prüfung blendet er die
    // Meldung auch dann wieder ein, wenn längst eine Frage ausgewählt ist.
    img.onerror = () => {
      if (current !== pos) return;
      img.classList.add('hidden');
      empty.classList.remove('hidden');
    };
  }
}

const TYPE_LABEL = { MC: 'Einfachauswahl', MR: 'Mehrfachauswahl', TF: 'Wahr/Falsch',
                     FIB: 'Lückentext', SD: 'Reihenfolge' };

function questionView(q) {
  const box = document.createElement('div');
  box.className = 'stage-text';

  const tag = document.createElement('span');
  tag.className = 'q-type';
  tag.textContent = (TYPE_LABEL[q.type] || q.type) + ' · ' + q.type;
  box.appendChild(tag);

  const h = document.createElement('p');
  h.className = 'q-text';
  h.textContent = q.text;
  box.appendChild(h);

  const ul = document.createElement('ul');
  ul.className = 'q-opts' + (q.type === 'SD' ? ' is-seq' : '');
  q.options.forEach(([text, correct], i) => {
    const li = document.createElement('li');
    if (correct) li.className = 'is-correct';
    const mark = document.createElement('span');
    mark.className = 'q-mark num';
    mark.textContent = q.type === 'SD' ? (i + 1) + '.' : (correct ? '✓' : '');
    const tx = document.createElement('span');
    tx.textContent = text;
    li.append(mark, tx);
    ul.appendChild(li);
  });
  box.appendChild(ul);
  return box;
}

$('stagePrev').addEventListener('click', () => select(current - 1));
$('stageNext').addEventListener('click', () => select(current + 1));
$('stageZoom').addEventListener('click', () => {
  const t = entries[current];
  if (t && !t.q) openLightbox(t.index);
});
document.addEventListener('keydown', (e) => {
  if ($('work').classList.contains('hidden')) return;
  if (!$('lightbox').classList.contains('hidden')) return;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName)) return;
  if (e.key === 'ArrowDown' || e.key === 'ArrowRight') { e.preventDefault(); select(current + 1); }
  if (e.key === 'ArrowUp' || e.key === 'ArrowLeft') { e.preventDefault(); select(current - 1); }
});

// --- Kurs wählen ----------------------------------------------------------
// pywebview ist erst nach diesem Event bereit.
window.addEventListener('pywebviewready', init);
if (window.pywebview && window.pywebview.api) init();

let inited = false;
async function init() {
  if (inited) return;
  inited = true;
  try {
    renderStatus(await window.pywebview.api.status());
  } catch (e) { /* pywebview noch nicht bereit */ }
}

function renderStatus(st) {
  const lang = (st.ocr_lang || '').toLowerCase();
  const ok = (lang === 'deu' || lang === 'pol' || lang === 'eng');
  $('ocrHint').textContent = ok
    ? 'Texterkennung bereit. Text, den imc als Bild abgelegt hat, wird auf Wunsch wieder editierbar.'
    : '\u26a0\ufe0f Texterkennung nicht verf\u00fcgbar \u2014 Text, den imc als Bild abgelegt hat, '
      + 'bleibt Bild. Alles andere wird normal umgewandelt.';
  $('ocrHint').style.color = ok ? 'var(--ink-soft)' : 'var(--warn)';

  // Ohne Texterkennung blieb der Schalter angehakt und tat still nichts. Er
  // wird jetzt abgeschaltet und gesperrt, und der Grund steht daneben — sonst
  // wartet man auf editierbaren Text, der nie kommt.
  const box = $('optOcr');
  box.disabled = !ok;
  if (!ok) box.checked = false;
  box.closest('.chip').title = ok
    ? box.closest('.chip').title
    : 'Nicht verfügbar: die Texterkennung fehlt in dieser Installation.';
  const warn = $('ocrWarn');
  warn.textContent = ok ? '' : 'Texterkennung fehlt — Bild-Text bleibt Bild';
  warn.classList.toggle('hidden', ok);
  syncLangField();
}

$('btnPick').addEventListener('click', pickFile);
$('btnPick2').addEventListener('click', pickFile);

function pickFile() {
  // Nicht-blockierend: Python öffnet Dialog + analysiert in einem Thread und
  // ruft window.onPicked(data) auf (Windows/WebView2-Deadlock-Fix).
  try { window.pywebview.api.pick_ats(); }
  catch (e) { alert('Datei konnte nicht geladen werden: ' + errMsg(e)); }
}

// von Python gepusht, sobald Dialog + Analyse fertig sind
window.onPicked = (data) => {
  if (!data) return;                 // abgebrochen
  if (data.error) { alert(data.error); return; }
  if (!Array.isArray(data.list)) { alert('Unerwartete Antwort vom Konverter.'); return; }
  showWork(data);
};

function showWork(d) {
  $('opener').classList.add('hidden');
  $('work').classList.remove('hidden');
  $('fileName').textContent = d.file;
  $('badgeScenes').textContent = d.scenes;
  $('badgeSlides').textContent = d.slides;
  if (d.canvas) {
    $('statCanvas').innerHTML = '<b>' + d.canvas + '</b>imc-Maße';
    $('statCanvas').hidden = false;
    // Der Folienrahmen soll die Proportion DIESES Kurses haben, nicht die
    // fest verdrahteten 1024:748 aus dem Stylesheet.
    const m = /^(\d+)×(\d+)$/.exec(d.canvas);
    if (m) {
      const st = document.documentElement.style;
      st.setProperty('--slide-ratio', m[1] + '/' + m[2]);
      st.setProperty('--slide-w', m[1] + 'px');
    }
  }
  renderNav(d.list);
  $('result').classList.add('hidden');
  $('progressWrap').classList.add('hidden');
}

// --- OCR-Sprache an die OCR-Checkbox koppeln ------------------------------
function syncLangField() {
  const on = $('optOcr').checked && !$('optOcr').disabled;
  $('langField').classList.toggle('is-disabled', !on);
  $('optLang').disabled = !on;
}
$('optOcr').addEventListener('change', syncLangField);
syncLangField();

// --- Export ---------------------------------------------------------------
$('btnExport').addEventListener('click', async () => {
  const opts = {
    ocr: $('optOcr').checked,
    audio: $('optAudio').checked,
    clean_bg: $('optCleanBg').checked,
    course_bg: $('optCourseBg').checked,
    geometry: $('optGeometry').value,
    single_scene: $('optSingle').checked,
    no_exams: $('optNoExams').checked,
    quiz_bank: $('optQuizBank').checked,
    quiz_font_pt: Number($('optQuizFont').value),
    quiz_export: $('optQuizExport').checked,
    quiz_slides: $('optQuizSlides').checked,
    ocr_lang: $('optLang').value,
  };
  setBusy(true);
  $('result').classList.add('hidden');
  $('progressWrap').classList.remove('hidden');
  setProgress(0, 'Starte…');
  // Nicht-blockierend: Python pusht das Ergebnis via window.onExported.
  try { window.pywebview.api.export_story(opts); }
  catch (e) { setBusy(false); showResult({ ok: false, msg: 'Unerwarteter Fehler: ' + errMsg(e) }); }
});

// von Python gepusht
window.onProgress = (frac, msg) => setProgress(frac, msg);
window.onExported = (r) => { setBusy(false); showResult(r); };

function setProgress(frac, msg) {
  $('progFill').style.width = Math.round((frac || 0) * 100) + '%';
  if (msg) $('progMsg').textContent = msg;
}

function setBusy(b) {
  $('btnExport').disabled = b;
  $('btnExport').textContent = b ? 'Konvertiere…' : 'Als .story exportieren';
}

function showResult(r) {
  const el = $('result');
  el.classList.remove('hidden', 'ok', 'err');
  el.textContent = '';
  setTimeout(() => el.scrollIntoView({ block: 'nearest', behavior: 'smooth' }), 30);
  const h = document.createElement('h4');
  if (r && r.ok) {
    el.classList.add('ok');
    // Die Fortschrittsanzeige hat ihren Zweck erfüllt. Blieb sie stehen, las
    // man dort weiter die Rohmeldung des Konverters („testzip=None" …), die
    // im Ergebnisfeld ohnehin aufbereitet steht.
    $('progressWrap').classList.add('hidden');
    h.textContent = '✓ Export fertig';
    const mb = (Number(r.size) / 1e6).toFixed(1);
    const lines = [`${r.slides} Folien · ${r.scenes} Szenen · ${r.media} Medien · ${mb} MB`];
    if (r.ocr_replaced) lines.push(`${r.ocr_replaced} Text-Bilder editierbar gemacht (Ø ${r.ocr_conf}%)`);
    // Die Fragenbank steckt IN der .story und ist von aussen nicht zu sehen —
    // ohne diese Zeile bleibt offen, ob der Haken etwas bewirkt hat.
    if (r.bank_slides) {
      const miss = r.bank_skipped && Object.keys(r.bank_skipped).length
        ? ' — ' + Object.entries(r.bank_skipped).map(([k, v]) => `${v}× ${k} nicht baubar`).join(', ')
        : '';
      lines.push(`${r.bank_slides} Fragen als Fragenbank in der .story${miss}`);
    }
    const sk = [];
    if (r.skipped_slides) sk.push(`${r.skipped_slides} Folien`);
    if (r.skipped_imgs) sk.push(`${r.skipped_imgs} Bilder`);
    if (r.skipped_audio) sk.push(`${r.skipped_audio} Audio`);
    if (r.ocr_errors) sk.push(`${r.ocr_errors} OCR-Fehler`);
    if (sk.length) lines.push(`⚠️ übersprungen: ${sk.join(', ')}`);
    el.appendChild(h);
    for (const line of lines) {
      const p = document.createElement('div');
      p.className = 'rline';
      p.textContent = line;
      el.appendChild(p);
    }
    const path = document.createElement('div');
    path.className = 'path';
    path.textContent = r.out;
    el.appendChild(path);
    // Die Fragen liegen NEBEN der .story — ohne diesen Hinweis übersieht man
    // sie, und der halbe Kurs fehlte in Storyline.
    if (Array.isArray(r.quiz_files) && r.quiz_files.length) {
      const q = document.createElement('div');
      q.className = 'rline quiz';
      const names = r.quiz_files.map((f) => f.split(/[\\/]/).pop()).join(' · ');
      q.textContent = 'Fragen als Excel: ' + names
        + ' — in Storyline über Datei › Import › Fragen aus Datei einlesen.';
      el.appendChild(q);
    }
    // Zeigt die Datei im Dateimanager — Finder, Explorer, was auch immer.
    // Stand vorher „Im Finder zeigen", was auf Windows niemandem hilft.
    const reveal = document.createElement('button');
    reveal.className = 'reveal';
    reveal.textContent = '📂 Anzeigen';
    reveal.title = 'Die Datei im Dateimanager zeigen';
    reveal.addEventListener('click', async () => {
      try { await window.pywebview.api.reveal(r.out); } catch (e) { /* ignore */ }
    });
    el.appendChild(reveal);
    // Detail: was konkret nicht übernommen wurde (Folie xy …)
    if (Array.isArray(r.skipped_detail) && r.skipped_detail.length) {
      const det = document.createElement('details');
      det.className = 'skipped';
      const sum = document.createElement('summary');
      sum.textContent = `⚠️ ${r.skipped_detail.length} Folie(n) mit nicht übernommenem Inhalt — Details anzeigen`;
      det.appendChild(sum);
      const ul = document.createElement('ul');
      for (const line of r.skipped_detail) {
        const li = document.createElement('li');
        li.textContent = line;
        ul.appendChild(li);
      }
      det.appendChild(ul);
      el.appendChild(det);
    }
  } else {
    el.classList.add('err');
    h.textContent = '✗ Nicht exportiert';
    el.appendChild(h);
    const p = document.createElement('div');
    p.className = 'rline';
    p.textContent = (r && r.msg) || 'Unbekannter Fehler';
    el.appendChild(p);
    $('progressWrap').classList.add('hidden');
  }
}

// --- Lightbox (Großansicht mit Blättern) ----------------------------------
function openLightbox(index) {
  // Nur Folien: Fragen haben kein Vorschaubild, ein Sprung dorthin zeigte
  // ein kaputtes Bild.
  slidesList = entries.filter((t) => !t.q);
  lbPos = slidesList.findIndex((t) => t.index === index);
  if (lbPos < 0) lbPos = 0;
  showLb();
  $('lightbox').classList.remove('hidden');
}

function showLb() {
  const t = slidesList[lbPos];
  if (!t) return;
  $('lbImg').src = `/full/${t.index}`;
  $('lbCap').textContent = `${t.index}. ${t.name}   (${lbPos + 1}/${slidesList.length})`;
}

function lbStep(delta) {
  if (!slidesList.length) return;
  lbPos = Math.min(slidesList.length - 1, Math.max(0, lbPos + delta));
  showLb();
}

function closeLb() { $('lightbox').classList.add('hidden'); }

$('lightbox').addEventListener('click', closeLb);          // Klick auf Hintergrund schließt
$('lbImg').addEventListener('click', (e) => e.stopPropagation());
$('lbPrev').addEventListener('click', (e) => { e.stopPropagation(); lbStep(-1); });
$('lbNext').addEventListener('click', (e) => { e.stopPropagation(); lbStep(1); });
$('lbClose').addEventListener('click', (e) => { e.stopPropagation(); closeLb(); });

document.addEventListener('keydown', (e) => {
  if ($('lightbox').classList.contains('hidden')) return;
  if (e.key === 'Escape') closeLb();
  else if (e.key === 'ArrowLeft') lbStep(-1);
  else if (e.key === 'ArrowRight') lbStep(1);
});
