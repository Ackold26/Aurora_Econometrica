"""
aurora_html.interactive — JS bundle composer.

M2 minimal bootstrap: theme resolution + TOC scroll-spy + modal toggles +
copy-link + skeleton hide after init. Full interactivity (drill-down,
sortable table, scenario switcher, budget what-if, animated counters,
keyboard shortcuts) lands in M3.

All JS is composed as a single block so CSP can hash it once.
"""
from __future__ import annotations

import json


def bootstrap_js(
    initial_theme: str,
    chart_data_json: str,
    model_context_json: str,
    strings: dict,
) -> str:
    """Compose M2 bootstrap JS.

    Keeps payload self-contained (no globals leak) via IIFE. Reads user
    theme preference from localStorage with sessionStorage + URL fallback.
    """
    # M2: minimal feature set.
    # Safe-embed strings + data.
    strings_json = json.dumps({
        'toasts':     strings.get('ui', {}).get('toasts', {}),
        'search':     strings.get('ui', {}).get('search', {}),
        'theme':      strings.get('ui', {}).get('theme', {}),
    }, ensure_ascii=True)

    return f"""
(function() {{
  'use strict';

  // ─── Constants (frozen) ───────────────────────────────────────────
  var CHART_DATA = {chart_data_json};
  var MODEL_CTX  = {model_context_json};
  var STRINGS    = {strings_json};
  var THEMES     = ['light', 'dark', 'fun'];
  var THEME_STORAGE_KEY = 'aurora-html-theme';

  // ─── Storage wrappers (Safari file:// tolerance) ──────────────────
  function storageGet(key) {{
    try {{ return localStorage.getItem(key); }} catch (e) {{}}
    try {{ return sessionStorage.getItem(key); }} catch (e) {{}}
    return null;
  }}
  function storageSet(key, val) {{
    try {{ localStorage.setItem(key, val); return; }} catch (e) {{}}
    try {{ sessionStorage.setItem(key, val); }} catch (e) {{}}
  }}

  // ─── Theme ────────────────────────────────────────────────────────
  function resolveInitialTheme() {{
    var urlTheme = new URLSearchParams(location.search).get('theme');
    if (THEMES.indexOf(urlTheme) >= 0) return urlTheme;
    var stored = storageGet(THEME_STORAGE_KEY);
    if (THEMES.indexOf(stored) >= 0) return stored;
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {{
      return 'dark';
    }}
    return '{initial_theme}';
  }}

  function applyTheme(name) {{
    if (THEMES.indexOf(name) < 0) name = 'light';
    document.documentElement.setAttribute('data-theme', name);
    storageSet(THEME_STORAGE_KEY, name);
    var btn = document.getElementById('btn-theme-toggle');
    if (btn) {{
      var icons = {{ light: '☼', dark: '☾', fun: '✦' }};
      btn.textContent = icons[name] || '☼';
      btn.setAttribute('data-current-theme', name);
    }}
    // Re-theme ECharts (if initialized)
    if (window.AURORA_CHARTS && window.AURORA_THEMES && window.AURORA_THEMES[name]) {{
      Object.values(window.AURORA_CHARTS).forEach(function(chart) {{
        try {{ chart.setOption({{ color: window.AURORA_THEMES[name].palette }}); }} catch (e) {{}}
      }});
    }}
  }}

  function cycleTheme() {{
    var current = document.documentElement.getAttribute('data-theme') || 'light';
    var next = THEMES[(THEMES.indexOf(current) + 1) % THEMES.length];
    applyTheme(next);
  }}

  // ─── TOC scroll-spy ───────────────────────────────────────────────
  function setupTocSpy() {{
    var links = document.querySelectorAll('.toc-list a[data-toc-target]');
    if (!('IntersectionObserver' in window) || links.length === 0) return;
    var linkByTarget = {{}};
    links.forEach(function(a) {{ linkByTarget[a.getAttribute('data-toc-target')] = a; }});
    var io = new IntersectionObserver(function(entries) {{
      entries.forEach(function(entry) {{
        if (entry.isIntersecting) {{
          links.forEach(function(a) {{ a.classList.remove('active'); }});
          var target = linkByTarget[entry.target.id];
          if (target) target.classList.add('active');
        }}
      }});
    }}, {{ rootMargin: '-30% 0% -60% 0%', threshold: 0 }});
    document.querySelectorAll('.section[id]').forEach(function(s) {{ io.observe(s); }});
  }}

  // ─── Scroll progress bar ──────────────────────────────────────────
  function setupScrollProgress() {{
    var bar = document.getElementById('scroll-progress');
    if (!bar) return;
    function update() {{
      var st = document.documentElement.scrollTop || document.body.scrollTop;
      var sh = (document.documentElement.scrollHeight || document.body.scrollHeight) - document.documentElement.clientHeight;
      var pct = sh > 0 ? (st / sh * 100) : 0;
      bar.style.width = pct + '%';
    }}
    window.addEventListener('scroll', update, {{ passive: true }});
    update();
  }}

  // ─── Modal management ─────────────────────────────────────────────
  function openModal(id) {{
    var m = document.getElementById(id);
    if (m) m.setAttribute('aria-hidden', 'false');
  }}
  function closeModal(m) {{ if (m) m.setAttribute('aria-hidden', 'true'); }}
  function closeAllModals() {{
    document.querySelectorAll('.modal[aria-hidden="false"]').forEach(closeModal);
  }}
  function setupModals() {{
    document.querySelectorAll('[data-close-modal]').forEach(function(el) {{
      el.addEventListener('click', function() {{ closeModal(el.closest('.modal')); }});
    }});
    var shortcutsBtn = document.getElementById('btn-shortcuts');
    if (shortcutsBtn) shortcutsBtn.addEventListener('click', function() {{ openModal('shortcuts-modal'); }});
    var searchBtn = document.getElementById('btn-search');
    if (searchBtn) searchBtn.addEventListener('click', function() {{
      openModal('search-modal');
      setTimeout(function() {{ var s = document.getElementById('search-input'); if (s) s.focus(); }}, 50);
    }});
  }}

  // ─── Toasts ───────────────────────────────────────────────────────
  function toast(msg) {{
    var c = document.getElementById('toast-container');
    if (!c) return;
    var t = document.createElement('div');
    t.className = 'toast';
    t.textContent = msg;
    c.appendChild(t);
    requestAnimationFrame(function() {{ t.classList.add('show'); }});
    setTimeout(function() {{
      t.classList.remove('show');
      setTimeout(function() {{ t.remove(); }}, 400);
    }}, 2000);
  }}

  // ─── Copy link ────────────────────────────────────────────────────
  function copyLink() {{
    var url = location.href;
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(url).then(function() {{
        toast((STRINGS.toasts && STRINGS.toasts.link_copied) || 'Ссылка скопирована');
      }}).catch(function() {{ toast('Не удалось скопировать'); }});
    }} else {{
      toast('Clipboard API недоступен');
    }}
  }}

  // ─── TOC toggle (mobile) ──────────────────────────────────────────
  function setupTocToggle() {{
    var btn = document.getElementById('btn-toc-toggle');
    var sidebar = document.getElementById('toc-sidebar');
    if (!btn || !sidebar) return;
    btn.addEventListener('click', function() {{
      var isOpen = sidebar.classList.toggle('toc-open');
      btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    }});
    sidebar.querySelectorAll('a').forEach(function(a) {{
      a.addEventListener('click', function() {{ sidebar.classList.remove('toc-open'); }});
    }});
  }}

  // ─── Keyboard shortcuts (minimal in M2) ───────────────────────────
  function setupKeyboard() {{
    document.addEventListener('keydown', function(e) {{
      // Ignore if typing in input/textarea
      var t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {{
        if (e.key === 'Escape') {{
          t.blur(); closeAllModals();
        }}
        return;
      }}
      if (e.key === 'Escape') {{ closeAllModals(); }}
      else if (e.key === 't' || e.key === 'T') {{ cycleTheme(); }}
      else if (e.key === '?') {{ openModal('shortcuts-modal'); }}
      else if (e.key === 'c' || e.key === 'C') {{ copyLink(); }}
      else if ((e.ctrlKey || e.metaKey) && e.key === 'k') {{
        e.preventDefault();
        openModal('search-modal');
        setTimeout(function() {{ var s = document.getElementById('search-input'); if (s) s.focus(); }}, 50);
      }}
      else if (/^[1-9]$/.test(e.key)) {{
        var n = parseInt(e.key, 10) - 1;
        var secs = document.querySelectorAll('.section[id]');
        if (secs[n]) secs[n].scrollIntoView({{ behavior: 'smooth' }});
      }}
    }});
  }}

  // ─── Button bindings ──────────────────────────────────────────────
  function setupButtons() {{
    var themeBtn = document.getElementById('btn-theme-toggle');
    if (themeBtn) themeBtn.addEventListener('click', cycleTheme);
    var copyBtn = document.getElementById('btn-copy-link');
    if (copyBtn) copyBtn.addEventListener('click', copyLink);
  }}

  // ─── Hide chart skeletons (M2 stub - M3 initializes real charts) ──
  function hideSkeletonsForEmptyCharts() {{
    // When CHART_DATA has actual content (M3), charts initialize and call
    // their own skeleton-hide. For M2 placeholder, hide skeleton so user
    // isn't stuck watching shimmer forever.
    setTimeout(function() {{
      document.querySelectorAll('.chart-skeleton').forEach(function(s) {{
        s.classList.add('hidden');
      }});
    }}, 500);
  }}

  // ─── Error boundary ───────────────────────────────────────────────
  window.addEventListener('error', function(e) {{
    console.error('Aurora HTML error:', e.error || e.message);
  }});

  // ─── Boot ─────────────────────────────────────────────────────────
  function boot() {{
    applyTheme(resolveInitialTheme());
    setupTocSpy();
    setupScrollProgress();
    setupModals();
    setupTocToggle();
    setupKeyboard();
    setupButtons();
    hideSkeletonsForEmptyCharts();
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', boot);
  }} else {{
    boot();
  }}

  // Expose hooks for M3 extensions
  window.AURORA_APP = {{
    toast: toast,
    copyLink: copyLink,
    cycleTheme: cycleTheme,
    applyTheme: applyTheme,
    data: CHART_DATA,
    modelContext: MODEL_CTX,
  }};
}})();
"""
