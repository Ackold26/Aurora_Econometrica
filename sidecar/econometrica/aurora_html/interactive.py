"""
aurora_html.interactive - JS bundle composer.

M3 full interactivity: chart initialization (5 ECharts with SVG renderer),
sortable table, drill-down side-panel, scenario switcher, budget what-if
slider (Hill saturation formula), animated number counters, search filter,
skeleton hide on ready, plus M2 basics (theme, TOC, shortcuts, modals).

All composed into one IIFE so CSP hashes it once.
"""
from __future__ import annotations

import json


def bootstrap_js(
    initial_theme: str,
    chart_data_json: str,
    model_context_json: str,
    strings: dict,
) -> str:
    """Compose M3 bootstrap JS."""
    strings_json = json.dumps({
        'toasts':    strings.get('ui', {}).get('toasts', {}),
        'search':    strings.get('ui', {}).get('search', {}),
        'theme':     strings.get('ui', {}).get('theme', {}),
        'empty':     strings.get('empty_states', {}),
        'buttons':   strings.get('ui', {}).get('buttons', {}),
        'verdicts':  strings.get('verdicts', {}),
    }, ensure_ascii=True)

    return f"""
(function() {{
  'use strict';

  // ─── Frozen payloads from Python ──────────────────────────────────
  var CHART_DATA = {chart_data_json};
  var MODEL_CTX  = {model_context_json};
  var STRINGS    = {strings_json};
  var THEMES     = ['light', 'dark', 'fun'];
  var THEME_STORAGE_KEY = 'aurora-html-theme';
  var SORT_STORAGE_KEY  = 'aurora-html-sort';

  var AURORA_CHARTS = {{}};  // {{ chartId: echartsInstance }}
  window.AURORA_CHARTS = AURORA_CHARTS;

  var PREFERS_REDUCED_MOTION = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ─── Haptic feedback (mobile/trackpad with haptic support) ────────
  // Respect prefers-reduced-motion; `navigator.vibrate` is a no-op on
  // desktop browsers without haptic hardware, so guard is just taste.
  function haptic(duration) {{
    if (PREFERS_REDUCED_MOTION) return;
    try {{
      if (navigator.vibrate) navigator.vibrate(duration || 8);
    }} catch (e) {{}}
  }}

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

  function currentTheme() {{
    return document.documentElement.getAttribute('data-theme') || 'light';
  }}

  function applyTheme(name, opts) {{
    opts = opts || {{}};
    if (THEMES.indexOf(name) < 0) name = 'light';
    document.documentElement.setAttribute('data-theme', name);
    storageSet(THEME_STORAGE_KEY, name);
    var btn = document.getElementById('btn-theme-toggle');
    if (btn) {{
      var icons = {{ light: '☼', dark: '☾', fun: '✦' }};
      btn.textContent = icons[name] || '☼';
      btn.setAttribute('data-current-theme', name);
      btn.setAttribute('aria-label', 'Тема: ' + name + ' (нажмите T для смены)');
      // Subtle icon rotation on change (CSS handles transition)
      if (opts.animated && !PREFERS_REDUCED_MOTION) {{
        btn.style.transform = 'rotate(180deg) scale(1.1)';
        setTimeout(function() {{ btn.style.transform = ''; }}, 320);
      }}
    }}
    // Re-theme all active charts - smooth via ECharts animation
    var pal = window.AURORA_THEMES && window.AURORA_THEMES[name];
    if (pal) {{
      Object.keys(AURORA_CHARTS).forEach(function(id) {{
        var ch = AURORA_CHARTS[id];
        if (!ch) return;
        try {{
          ch.setOption(themeOptionOverrides(pal), {{ notMerge: false }});
        }} catch (e) {{}}
      }});
    }}
  }}

  function cycleTheme() {{
    var next = THEMES[(THEMES.indexOf(currentTheme()) + 1) % THEMES.length];
    applyTheme(next, {{ animated: true }});
    haptic(10);
    // Flash theme name briefly
    var label = (STRINGS.theme && STRINGS.theme[next]) || next;
    toast('Тема: ' + label);
  }}

  function themeOptionOverrides(pal) {{
    return {{
      textStyle: {{ color: pal.textColor, fontFamily: 'Inter, sans-serif' }},
      tooltip: {{
        backgroundColor: pal.tooltipBg,
        borderColor: pal.tooltipBorder,
        textStyle: {{ color: pal.tooltipText }}
      }}
    }};
  }}

  // ─── Chart helpers ────────────────────────────────────────────────
  function currentPalette() {{
    return (window.AURORA_THEMES && window.AURORA_THEMES[currentTheme()]) ||
           (window.AURORA_THEMES && window.AURORA_THEMES.light) || {{}};
  }}

  function baseAxisStyle(pal) {{
    return {{
      axisLine:  {{ lineStyle: {{ color: pal.gridColor, width: 1 }} }},
      axisLabel: {{ color: pal.textMutedColor, fontSize: 11 }},
      axisTick:  {{ show: false }},
      splitLine: {{ lineStyle: {{ color: pal.gridColor, type: 'dashed', opacity: 0.5 }} }},
    }};
  }}

  function baseTooltip(pal) {{
    return {{
      trigger: 'axis',
      backgroundColor: pal.tooltipBg,
      borderColor: pal.tooltipBorder,
      borderWidth: 1,
      textStyle: {{ color: pal.tooltipText, fontSize: 12, fontFamily: 'Inter, sans-serif' }},
      axisPointer: {{ type: 'shadow', shadowStyle: {{ color: 'rgba(197, 164, 109, 0.08)' }} }},
    }};
  }}

  function buildMroasOption(data) {{
    if (!data || !data.names || !data.names.length) return null;
    var pal = currentPalette();
    // Reverse for horizontal bar (ECharts puts first category at bottom)
    var names  = data.names.slice().reverse();
    var values = data.values.slice().reverse();
    var heroIdx = names.indexOf(data.hero);
    return {{
      animation: !PREFERS_REDUCED_MOTION,
      animationDuration: 600,
      textStyle: {{ color: pal.textColor, fontFamily: 'Inter, sans-serif' }},
      grid: {{ left: 8, right: 40, bottom: 8, top: 8, containLabel: true }},
      tooltip: Object.assign(baseTooltip(pal), {{
        formatter: function(ps) {{
          var p = Array.isArray(ps) ? ps[0] : ps;
          return '<b>' + p.name + '</b><br/>mROAS: ' + p.value.toFixed(2) + '×';
        }}
      }}),
      xAxis: Object.assign({{ type: 'value' }}, baseAxisStyle(pal), {{
        axisLabel: Object.assign({{}}, baseAxisStyle(pal).axisLabel, {{ formatter: '{{value}}×' }})
      }}),
      yAxis: Object.assign({{ type: 'category', data: names }}, baseAxisStyle(pal)),
      series: [{{
        type: 'bar',
        data: values.map(function(v, i) {{
          return {{
            value: v,
            itemStyle: {{
              color: (i === heroIdx) ? pal.heroColor : pal.mutedColor,
              borderRadius: [0, 4, 4, 0]
            }}
          }};
        }}),
        label: {{
          show: true, position: 'right',
          color: pal.textColor, fontSize: 11, fontWeight: 600,
          formatter: function(p) {{ return p.value.toFixed(2) + '×'; }}
        }},
        barMaxWidth: 22,
      }}]
    }};
  }}

  function buildShareOption(data) {{
    if (!data || !data.names || !data.names.length) return null;
    var pal = currentPalette();
    return {{
      animation: !PREFERS_REDUCED_MOTION,
      animationDuration: 600,
      textStyle: {{ color: pal.textColor, fontFamily: 'Inter, sans-serif' }},
      legend: {{
        top: 0,
        textStyle: {{ color: pal.textMutedColor, fontSize: 11 }},
        itemWidth: 10, itemHeight: 10, itemGap: 18,
      }},
      grid: {{ left: 8, right: 8, bottom: 8, top: 40, containLabel: true }},
      tooltip: baseTooltip(pal),
      xAxis: Object.assign({{ type: 'category', data: data.names }}, baseAxisStyle(pal), {{
        axisLabel: Object.assign({{}}, baseAxisStyle(pal).axisLabel, {{ rotate: data.names.length > 6 ? 25 : 0 }})
      }}),
      yAxis: Object.assign({{ type: 'value' }}, baseAxisStyle(pal), {{
        axisLabel: Object.assign({{}}, baseAxisStyle(pal).axisLabel, {{ formatter: '{{value}}%' }})
      }}),
      series: [
        {{ name: '% бюджета', type: 'bar', data: data.spend_pct,
          itemStyle: {{ color: pal.mutedColor, borderRadius: [3, 3, 0, 0] }}, barMaxWidth: 22 }},
        {{ name: '% эффекта', type: 'bar', data: data.effect_pct,
          itemStyle: {{ color: pal.heroColor, borderRadius: [3, 3, 0, 0] }}, barMaxWidth: 22 }}
      ]
    }};
  }}

  function buildTimelineOption(data) {{
    if (!data || !data.weeks || !data.weeks.length) return null;
    var pal = currentPalette();
    var series = [];
    if (data.baseline && data.baseline.length) {{
      series.push({{
        name: 'Baseline', type: 'line', stack: 'total', smooth: 0.3, showSymbol: false,
        data: data.baseline, lineStyle: {{ width: 0 }},
        itemStyle: {{ color: pal.baselineColor }},
        areaStyle: {{ color: pal.baselineColor, opacity: 0.85 }},
      }});
    }}
    (data.channel_order || []).forEach(function(name, i) {{
      if (!data.channels || !data.channels[name]) return;
      var color = pal.palette[i % pal.palette.length];
      series.push({{
        name: name, type: 'line', stack: 'total', smooth: 0.3, showSymbol: false,
        data: data.channels[name], lineStyle: {{ width: 0 }},
        itemStyle: {{ color: color }},
        areaStyle: {{ color: color, opacity: 0.85 }},
      }});
    }});
    return {{
      animation: !PREFERS_REDUCED_MOTION,
      animationDuration: 800,
      textStyle: {{ color: pal.textColor, fontFamily: 'Inter, sans-serif' }},
      legend: {{ top: 0, textStyle: {{ color: pal.textMutedColor, fontSize: 11 }}, itemWidth: 10, itemHeight: 10 }},
      tooltip: baseTooltip(pal),
      grid: {{ left: 8, right: 8, bottom: 56, top: 40, containLabel: true }},
      dataZoom: [
        {{ type: 'inside', start: 0, end: 100 }},
        {{ type: 'slider', height: 20, bottom: 16, borderColor: pal.gridColor,
          backgroundColor: 'transparent',
          fillerColor: 'rgba(197, 164, 109, 0.15)',
          handleStyle: {{ color: pal.heroColor }},
          textStyle: {{ color: pal.textMutedColor, fontSize: 10 }} }}
      ],
      xAxis: Object.assign({{ type: 'category', data: data.weeks }}, baseAxisStyle(pal)),
      yAxis: Object.assign({{ type: 'value' }}, baseAxisStyle(pal)),
      series: series
    }};
  }}

  function buildWaterfallOption(data) {{
    if (!data || !data.labels || !data.labels.length) return null;
    var pal = currentPalette();
    return {{
      animation: !PREFERS_REDUCED_MOTION,
      animationDuration: 600,
      textStyle: {{ color: pal.textColor, fontFamily: 'Inter, sans-serif' }},
      grid: {{ left: 8, right: 8, bottom: 8, top: 8, containLabel: true }},
      tooltip: baseTooltip(pal),
      xAxis: Object.assign({{ type: 'category', data: data.labels }}, baseAxisStyle(pal), {{
        axisLabel: Object.assign({{}}, baseAxisStyle(pal).axisLabel, {{ rotate: data.labels.length > 6 ? 25 : 0 }})
      }}),
      yAxis: Object.assign({{ type: 'value' }}, baseAxisStyle(pal)),
      series: [{{
        type: 'bar',
        data: data.values.map(function(v, i) {{
          var isBase = /base/i.test(data.labels[i] || '');
          return {{
            value: v,
            itemStyle: {{
              color: isBase ? pal.baselineColor : pal.palette[i % pal.palette.length],
              borderRadius: [3, 3, 0, 0]
            }}
          }};
        }}),
        barMaxWidth: 32
      }}]
    }};
  }}

  function buildOptimizeOption(data) {{
    if (!data || !data.names || !data.names.length) return null;
    var pal = currentPalette();
    return {{
      animation: !PREFERS_REDUCED_MOTION,
      animationDuration: 600,
      textStyle: {{ color: pal.textColor, fontFamily: 'Inter, sans-serif' }},
      legend: {{ top: 0, textStyle: {{ color: pal.textMutedColor, fontSize: 11 }}, itemWidth: 10, itemHeight: 10 }},
      grid: {{ left: 8, right: 8, bottom: 8, top: 40, containLabel: true }},
      tooltip: Object.assign(baseTooltip(pal), {{
        formatter: function(ps) {{
          if (!Array.isArray(ps)) ps = [ps];
          return ps.map(function(p) {{
            return '<b>' + p.name + '</b><br/>' + p.seriesName + ': ' + p.value.toFixed(0) + ' млн';
          }}).join('<br/>');
        }}
      }}),
      xAxis: Object.assign({{ type: 'category', data: data.names }}, baseAxisStyle(pal), {{
        axisLabel: Object.assign({{}}, baseAxisStyle(pal).axisLabel, {{ rotate: data.names.length > 6 ? 25 : 0 }})
      }}),
      yAxis: Object.assign({{ type: 'value' }}, baseAxisStyle(pal), {{
        axisLabel: Object.assign({{}}, baseAxisStyle(pal).axisLabel, {{ formatter: '{{value}} млн' }})
      }}),
      series: [
        {{ name: 'Текущий', type: 'bar', data: data.current,
          itemStyle: {{ color: pal.mutedColor, borderRadius: [3, 3, 0, 0] }}, barMaxWidth: 22 }},
        {{ name: 'Оптимальный', type: 'bar', data: data.optimal,
          itemStyle: {{ color: pal.heroColor, borderRadius: [3, 3, 0, 0] }}, barMaxWidth: 22 }}
      ]
    }};
  }}

  function initChart(id, builder, dataKey) {{
    var host = document.getElementById(id);
    if (!host || !window.echarts) return null;
    var opt = builder(CHART_DATA[dataKey]);
    if (!opt) {{
      // No data: show empty state instead of skeleton
      host.innerHTML = '<div style="padding:40px;text-align:center;color:var(--text-muted);font-size:13px;">' +
                       (STRINGS.empty.no_data || 'Нет данных') + '</div>';
      return null;
    }}
    var ch = echarts.init(host, null, {{ renderer: 'svg' }});
    ch.setOption(opt);
    AURORA_CHARTS[id] = ch;
    // Hide skeleton
    var sk = host.querySelector('.chart-skeleton');
    if (sk) sk.remove();
    return ch;
  }}

  function initAllCharts() {{
    initChart('chart-mroas',    buildMroasOption,    'mroas');
    initChart('chart-share',    buildShareOption,    'share');
    initChart('chart-timeline', buildTimelineOption, 'timeline');
    // Optimize + waterfall chart hosts are currently only rendered in
    // sections that reference them; skip gracefully if absent.
    initChart('chart-optimize', buildOptimizeOption, 'optimize');
    initChart('chart-waterfall', buildWaterfallOption, 'waterfall');

    // Resize handler (debounced)
    var resizeTimer;
    window.addEventListener('resize', function() {{
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function() {{
        Object.values(AURORA_CHARTS).forEach(function(c) {{
          try {{ c.resize(); }} catch (e) {{}}
        }});
      }}, 120);
    }});
  }}

  // ─── Drill-down side-panel ────────────────────────────────────────
  function openDrillPanel(title, contentHtml) {{
    var panel = document.getElementById('drill-panel');
    var titleEl = document.getElementById('drill-panel-title');
    var body = document.getElementById('drill-panel-body');
    if (!panel || !body) return;
    if (titleEl) titleEl.textContent = title;
    body.innerHTML = contentHtml;
    panel.setAttribute('aria-hidden', 'false');
    haptic(8);
    // Focus first actionable element for keyboard accessibility
    var closeBtn = document.getElementById('btn-close-drill');
    if (closeBtn) setTimeout(function() {{ closeBtn.focus(); }}, 300);
  }}
  function closeDrillPanel() {{
    var p = document.getElementById('drill-panel');
    if (p) p.setAttribute('aria-hidden', 'true');
  }}
  function setupDrillPanel() {{
    var closeBtn = document.getElementById('btn-close-drill');
    if (closeBtn) closeBtn.addEventListener('click', closeDrillPanel);
  }}
  function channelDrillContent(name) {{
    var d = (CHART_DATA.mroas && CHART_DATA.mroas.details && CHART_DATA.mroas.details[name]) || null;
    if (!d) return '<p style="color:var(--text-muted);">Нет детализации</p>';
    function row(lbl, val) {{
      return '<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--rule-subtle);font-size:13px;">' +
             '<span style="color:var(--text-muted);">' + lbl + '</span>' +
             '<span style="color:var(--text);font-weight:600;">' + val + '</span></div>';
    }}
    var verdictText = (STRINGS.verdicts && STRINGS.verdicts[d.verdict]) || d.verdict;
    return '<div>' +
      '<div style="font-family:var(--font-serif);font-size:26px;margin-bottom:4px;">' + name + '</div>' +
      '<div><span class="verdict-badge verdict-' + d.verdict + '">' + verdictText + '</span></div>' +
      '<div style="margin-top:20px;">' +
        row('Бюджет, млн ₽',       d.spend_mln.toFixed(1)) +
        row('Вклад, млн ₽',         d.contrib_mln.toFixed(1)) +
        row('mROAS',                d.mroas.toFixed(2) + '×') +
        (d.current_spend_mln ? row('Текущий spend, млн',   d.current_spend_mln.toFixed(1)) : '') +
        (d.optimal_spend_mln ? row('Оптимальный spend, млн', d.optimal_spend_mln.toFixed(1)) : '') +
      '</div>' +
    '</div>';
  }}
  function setupChannelDrilldowns() {{
    // Click table row → drill-down
    var rows = document.querySelectorAll('#action-table tbody tr[data-channel]');
    rows.forEach(function(row) {{
      row.style.cursor = 'pointer';
      row.addEventListener('click', function(e) {{
        if (e.target && e.target.closest('input, button, a')) return;
        var name = row.getAttribute('data-channel');
        openDrillPanel(name, channelDrillContent(name));
      }});
    }});
    // Click mROAS chart bar → drill-down (reads from ECharts event)
    var chart = AURORA_CHARTS['chart-mroas'];
    if (chart) {{
      chart.on('click', function(params) {{
        if (params && params.name) {{
          openDrillPanel(params.name, channelDrillContent(params.name));
        }}
      }});
    }}
  }}

  // ─── Sortable action table ────────────────────────────────────────
  function setupSortableTable() {{
    var table = document.getElementById('action-table');
    if (!table) return;
    var tbody = table.querySelector('tbody');
    if (!tbody) return;

    // Load persisted sort
    var stored = storageGet(SORT_STORAGE_KEY);
    if (stored) {{
      try {{
        var s = JSON.parse(stored);
        if (s && typeof s.col === 'number' && (s.dir === 'asc' || s.dir === 'desc')) {{
          sortTable(s.col, s.dir);
        }}
      }} catch (e) {{}}
    }}

    table.querySelectorAll('th[data-col]').forEach(function(th) {{
      th.addEventListener('click', function() {{
        var col = parseInt(th.getAttribute('data-col'), 10);
        var current = th.getAttribute('aria-sort');
        var newDir = (current === 'ascending') ? 'desc' : 'asc';
        sortTable(col, newDir);
        storageSet(SORT_STORAGE_KEY, JSON.stringify({{ col: col, dir: newDir }}));
      }});
    }});
  }}

  function sortTable(col, dir) {{
    var table = document.getElementById('action-table');
    if (!table) return;
    var tbody = table.querySelector('tbody');
    // Preserve totals-row always at bottom
    var rows = Array.from(tbody.querySelectorAll('tr')).filter(function(r) {{
      return !r.classList.contains('totals-row');
    }});
    var totalsRow = tbody.querySelector('tr.totals-row');

    rows.sort(function(a, b) {{
      var aCell = a.children[col];
      var bCell = b.children[col];
      if (!aCell || !bCell) return 0;
      var aSort = aCell.getAttribute('data-sort');
      var bSort = bCell.getAttribute('data-sort');
      var aVal = aSort !== null ? parseFloat(aSort) : aCell.textContent.trim();
      var bVal = bSort !== null ? parseFloat(bSort) : bCell.textContent.trim();
      if (typeof aVal === 'number' && typeof bVal === 'number' && !isNaN(aVal) && !isNaN(bVal)) {{
        return dir === 'asc' ? aVal - bVal : bVal - aVal;
      }}
      var cmp = String(aVal).localeCompare(String(bVal), 'ru');
      return dir === 'asc' ? cmp : -cmp;
    }});

    rows.forEach(function(r) {{ tbody.appendChild(r); }});
    if (totalsRow) tbody.appendChild(totalsRow);

    table.querySelectorAll('th[data-col]').forEach(function(th) {{
      var thCol = parseInt(th.getAttribute('data-col'), 10);
      th.setAttribute('aria-sort', thCol === col ? (dir === 'asc' ? 'ascending' : 'descending') : 'none');
    }});
  }}

  // ─── Table search filter ──────────────────────────────────────────
  function setupTableSearch() {{
    var input = document.getElementById('table-search');
    var table = document.getElementById('action-table');
    if (!input || !table) return;
    var tbody = table.querySelector('tbody');
    var rows = Array.from(tbody.querySelectorAll('tr[data-channel]'));
    input.addEventListener('input', function() {{
      var q = input.value.trim().toLowerCase();
      rows.forEach(function(r) {{
        var name = (r.getAttribute('data-channel') || '').toLowerCase();
        if (!q || name.indexOf(q) >= 0) r.classList.remove('hidden');
        else r.classList.add('hidden');
      }});
    }});
  }}

  // ─── Copy table as CSV ────────────────────────────────────────────
  function setupCopyCsv() {{
    var btn = document.getElementById('btn-copy-csv');
    var table = document.getElementById('action-table');
    if (!btn || !table) return;
    btn.addEventListener('click', function() {{
      var rows = Array.from(table.querySelectorAll('tr')).map(function(tr) {{
        return Array.from(tr.children).map(function(td) {{
          var text = (td.textContent || '').replace(/\\s+/g, ' ').trim();
          if (text.indexOf(',') >= 0 || text.indexOf('"') >= 0) {{
            return '"' + text.replace(/"/g, '""') + '"';
          }}
          return text;
        }}).join(',');
      }}).join('\\n');
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(rows).then(function() {{
          toast((STRINGS.toasts && STRINGS.toasts.csv_copied) || 'Таблица скопирована');
        }});
      }}
    }});
  }}

  // ─── Copy chart as PNG ────────────────────────────────────────────
  function setupCopyPng() {{
    document.querySelectorAll('[data-copy-chart]').forEach(function(btn) {{
      btn.addEventListener('click', function() {{
        var chartId = btn.getAttribute('data-copy-chart');
        var chart = AURORA_CHARTS[chartId];
        if (!chart) {{ toast('График не готов'); return; }}
        var url = chart.getDataURL({{ type: 'png', pixelRatio: 2, backgroundColor: '#ffffff' }});
        // Download via anchor
        var a = document.createElement('a');
        a.href = url;
        a.download = chartId + '-aurora.png';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        toast((STRINGS.toasts && STRINGS.toasts.png_saved) || 'График сохранён');
      }});
    }});
  }}

  // ─── Animated number counters ─────────────────────────────────────
  function animateCounter(el, target, duration) {{
    duration = duration || 1200;
    if (PREFERS_REDUCED_MOTION) {{
      el.textContent = formatCounterValue(target, el.textContent);
      return;
    }}
    var suffix = '';
    var orig = el.textContent || '';
    // Preserve suffix like "%" or "×" or " пп"
    var m = orig.match(/[^0-9+\\-\\.,\\s].*$/);
    if (m) suffix = m[0];
    // Preserve leading "+" for positive numbers
    var prefix = /^\\+/.test(orig) ? '+' : '';
    var start = 0;
    var startTime = null;
    function step(ts) {{
      if (!startTime) startTime = ts;
      var elapsed = ts - startTime;
      var pct = Math.min(elapsed / duration, 1);
      // easeOutQuart
      pct = 1 - Math.pow(1 - pct, 4);
      var v = start + (target - start) * pct;
      el.textContent = prefix + Math.round(v) + suffix;
      if (pct < 1) requestAnimationFrame(step);
      else el.textContent = prefix + Math.round(target) + suffix;
    }}
    requestAnimationFrame(step);
  }}
  function formatCounterValue(target, orig) {{
    var prefix = /^\\+/.test(orig) ? '+' : '';
    var suffix = '';
    var m = (orig || '').match(/[^0-9+\\-\\.,\\s].*$/);
    if (m) suffix = m[0];
    return prefix + Math.round(target) + suffix;
  }}
  function setupCounters() {{
    var nodes = document.querySelectorAll('[data-counter-end]');
    if (!nodes.length || !('IntersectionObserver' in window)) return;
    var io = new IntersectionObserver(function(entries) {{
      entries.forEach(function(entry) {{
        if (entry.isIntersecting) {{
          var el = entry.target;
          var target = parseFloat(el.getAttribute('data-counter-end'));
          if (!isNaN(target)) animateCounter(el, target);
          io.unobserve(el);
        }}
      }});
    }}, {{ threshold: 0.3 }});
    nodes.forEach(function(n) {{ io.observe(n); }});
  }}

  // ─── Budget what-if slider (Hill saturation formula) ──────────────
  // MODEL_CTX.enabled tells us whether params + normalization are available.
  // If not, slider UI is silently skipped. When available, we add a
  // "Budget what-if" expander above the action table and compute delta KPI
  // in real time using the same formula the backend optimizer uses.
  function setupBudgetWhatIf() {{
    if (!MODEL_CTX || !MODEL_CTX.enabled) return;
    var table = document.getElementById('action-table');
    if (!table) return;

    var params = MODEL_CTX.channel_params || {{}};
    var norm   = MODEL_CTX.normalization || {{}};
    var mediaMeans = norm.media_means || {{}};
    var yStd    = norm.y_std || 1;
    var yMean   = norm.y_mean || 0;
    var baseline = MODEL_CTX.baseline_sum || 0;
    var currentSpends = MODEL_CTX.current_spends_mln || {{}};

    // Baseline KPI with current spends
    function predictKPI(spendsMln) {{
      var total_norm_contrib = 0;
      Object.keys(params).forEach(function(ch) {{
        var p = params[ch] || {{}};
        var mean = mediaMeans[ch] || 1;
        var spend = (spendsMln[ch] || 0) * 1e6;
        var z = spend / mean;
        if (z <= 0 || !p.alpha || !p.gamma) return;
        var sat = Math.pow(z, p.alpha) / (Math.pow(z, p.alpha) + Math.pow(p.gamma, p.alpha));
        total_norm_contrib += (p.beta || 0) * sat;
      }});
      // Denormalize: contribution is in normalized units; multiply by y_std
      // and add baseline (already in rubles domain) for absolute KPI.
      return baseline + total_norm_contrib * yStd;
    }}

    var currentKPI = predictKPI(currentSpends);

    // Inject what-if panel above table
    var panel = document.createElement('details');
    panel.className = 'whatif-panel';
    panel.style.cssText = 'margin-bottom:16px;padding:12px 16px;background:var(--surface);' +
                          'border:1px solid var(--rule);border-radius:var(--radius-md);';
    var channelRows = Object.keys(currentSpends).map(function(ch) {{
      var cur = currentSpends[ch] || 0;
      var maxVal = Math.max(cur * 2, 100).toFixed(0);
      return '<div style="display:grid;grid-template-columns:130px 1fr 70px;gap:12px;align-items:center;padding:6px 0;">' +
        '<span style="font-size:13px;color:var(--text);">' + ch + '</span>' +
        '<input type="range" min="0" max="' + maxVal + '" value="' + cur.toFixed(0) + '" step="1" ' +
          'data-whatif-ch="' + ch + '" style="accent-color:var(--accent);" aria-label="Бюджет ' + ch + '">' +
        '<span class="whatif-val" data-whatif-val="' + ch + '" style="font-variant-numeric:tabular-nums;text-align:right;font-size:12px;color:var(--text-muted);">' +
          cur.toFixed(0) + ' млн</span>' +
      '</div>';
    }}).join('');

    panel.innerHTML =
      '<summary style="cursor:pointer;font-weight:600;color:var(--text);padding:4px 0;font-size:14px;">' +
        '🎚 Бюджет what-if (Hill saturation model)' +
      '</summary>' +
      '<div style="padding-top:12px;">' +
        '<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">' +
          'Перетаскивайте ползунки для моделирования реаллокации. KPI пересчитывается по формуле модели.' +
        '</div>' +
        channelRows +
        '<div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--rule-subtle);display:flex;justify-content:space-between;align-items:center;gap:16px;">' +
          '<button class="btn-inline" id="btn-whatif-reset">Сбросить</button>' +
          '<div style="text-align:right;">' +
            '<div style="font-size:11px;color:var(--text-muted);">Изменение KPI</div>' +
            '<div id="whatif-delta" style="font-family:var(--font-serif);font-size:22px;color:var(--text);">0%</div>' +
          '</div>' +
        '</div>' +
      '</div>';
    table.parentNode.insertBefore(panel, table);

    var spendState = Object.assign({{}}, currentSpends);
    var sliders = panel.querySelectorAll('input[type="range"][data-whatif-ch]');
    var valEls = {{}};
    panel.querySelectorAll('[data-whatif-val]').forEach(function(el) {{
      valEls[el.getAttribute('data-whatif-val')] = el;
    }});
    var deltaEl = document.getElementById('whatif-delta');

    var updateTimer;
    function scheduleUpdate() {{
      clearTimeout(updateTimer);
      updateTimer = setTimeout(function() {{
        var newKPI = predictKPI(spendState);
        var pct = currentKPI > 0 ? ((newKPI - currentKPI) / currentKPI * 100) : 0;
        var sign = pct >= 0 ? '+' : '';
        deltaEl.textContent = sign + pct.toFixed(1) + '%';
        deltaEl.style.color = pct > 0.1 ? 'var(--success)'
                           : (pct < -0.1 ? 'var(--danger)' : 'var(--text)');
      }}, 120);
    }}

    sliders.forEach(function(sl) {{
      sl.addEventListener('input', function() {{
        var ch = sl.getAttribute('data-whatif-ch');
        var v = parseFloat(sl.value);
        spendState[ch] = v;
        if (valEls[ch]) valEls[ch].textContent = v.toFixed(0) + ' млн';
        scheduleUpdate();
      }});
    }});

    var resetBtn = document.getElementById('btn-whatif-reset');
    if (resetBtn) {{
      resetBtn.addEventListener('click', function() {{
        sliders.forEach(function(sl) {{
          var ch = sl.getAttribute('data-whatif-ch');
          var orig = currentSpends[ch] || 0;
          sl.value = orig;
          spendState[ch] = orig;
          if (valEls[ch]) valEls[ch].textContent = orig.toFixed(0) + ' млн';
        }});
        scheduleUpdate();
      }});
    }}

    scheduleUpdate();
  }}

  // ─── Scenario switcher ────────────────────────────────────────────
  function setupScenarioSwitcher() {{
    var scenarios = CHART_DATA.scenarios || [];
    if (scenarios.length < 2) return;  // hide entirely
    var target = document.getElementById('recommend');
    if (!target) return;

    var wrap = document.createElement('div');
    wrap.style.cssText = 'margin-top:20px;padding:14px 18px;background:var(--surface);' +
                         'border:1px solid var(--rule);border-radius:var(--radius-md);' +
                         'display:flex;align-items:center;gap:16px;flex-wrap:wrap;';
    var options = scenarios.map(function(s, i) {{
      return '<option value="' + i + '">' + s.name + '</option>';
    }}).join('');
    wrap.innerHTML =
      '<label for="scenario-select" style="font-size:12px;color:var(--text-muted);font-weight:600;' +
        'text-transform:uppercase;letter-spacing:0.08em;">Сценарий</label>' +
      '<select id="scenario-select" class="search-inline" style="max-width:240px;">' + options + '</select>' +
      '<div id="scenario-info" style="font-size:13px;color:var(--text);margin-left:auto;"></div>';
    target.appendChild(wrap);

    var select = document.getElementById('scenario-select');
    var info = document.getElementById('scenario-info');
    function updateInfo(idx) {{
      var s = scenarios[idx];
      if (!s) return;
      info.innerHTML = '<span style="color:var(--text-muted);">KPI:</span> <b>' +
                       (s.kpi ? Math.round(s.kpi).toLocaleString('ru-RU') : '-') + '</b> · ' +
                       '<span style="color:var(--text-muted);">Лифт:</span> ' +
                       '<b style="color:var(--success);">+' + (s.lift || 0).toFixed(1) + '%</b>';
    }}
    updateInfo(0);
    select.addEventListener('change', function() {{
      updateInfo(parseInt(select.value, 10));
    }});
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

  // ─── Modals ───────────────────────────────────────────────────────
  function openModal(id) {{
    var m = document.getElementById(id);
    if (m) m.setAttribute('aria-hidden', 'false');
  }}
  function closeModal(m) {{ if (m) m.setAttribute('aria-hidden', 'true'); }}
  function closeAllModals() {{
    document.querySelectorAll('.modal[aria-hidden="false"]').forEach(closeModal);
    closeDrillPanel();
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

  // ─── Fuzzy search (sections + channels) ───────────────────────────
  function setupSearch() {{
    var input = document.getElementById('search-input');
    var results = document.getElementById('search-results');
    if (!input || !results) return;

    var items = [];
    // Index sections
    document.querySelectorAll('.section[id]').forEach(function(s) {{
      var id = s.id;
      var tocLink = document.querySelector('.toc-list a[data-toc-target="' + id + '"]');
      var label = tocLink ? tocLink.textContent.trim() : id;
      items.push({{ kind: 'section', label: label, target: id }});
    }});
    // Index channels (from chart data)
    (CHART_DATA.mroas && CHART_DATA.mroas.names || []).forEach(function(name) {{
      items.push({{ kind: 'channel', label: name, target: 'table' }});
    }});

    function render(q) {{
      q = (q || '').toLowerCase().trim();
      if (!q) {{
        results.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">Начните ввод для поиска</div>';
        return;
      }}
      var matches = items.filter(function(i) {{ return i.label.toLowerCase().indexOf(q) >= 0; }}).slice(0, 8);
      if (!matches.length) {{
        results.innerHTML = '<div style="color:var(--text-muted);font-size:12px;padding:8px;">' +
                            ((STRINGS.search && STRINGS.search.no_results) || 'Ничего не найдено') + '</div>';
        return;
      }}
      results.innerHTML = matches.map(function(m, i) {{
        return '<div class="search-result' + (i === 0 ? ' active' : '') + '" data-target="' + m.target + '" data-channel="' + (m.kind === 'channel' ? m.label : '') + '">' +
          '<div class="search-result-kind">' + (m.kind === 'section' ? 'Раздел' : 'Канал') + '</div>' +
          '<div>' + m.label + '</div>' +
        '</div>';
      }}).join('');
      results.querySelectorAll('.search-result').forEach(function(r) {{
        r.addEventListener('click', function() {{
          var tgt = r.getAttribute('data-target');
          var el = document.getElementById(tgt);
          if (el) el.scrollIntoView({{ behavior: PREFERS_REDUCED_MOTION ? 'auto' : 'smooth' }});
          closeAllModals();
          // If channel, also highlight row
          var ch = r.getAttribute('data-channel');
          if (ch) {{
            var row = document.querySelector('#action-table tr[data-channel="' + ch + '"]');
            if (row) {{
              row.style.transition = 'background 300ms';
              var prev = row.style.background;
              row.style.background = 'rgba(204, 255, 0, 0.2)';
              setTimeout(function() {{ row.style.background = prev; }}, 1200);
            }}
          }}
        }});
      }});
    }}
    input.addEventListener('input', function() {{ render(input.value); }});
    render('');
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
        haptic(12);
      }}).catch(function() {{ toast('Не удалось скопировать'); }});
    }} else {{
      toast('Clipboard API недоступен');
    }}
  }}

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

  // ─── Keyboard shortcuts ───────────────────────────────────────────
  function setupKeyboard() {{
    document.addEventListener('keydown', function(e) {{
      var t = e.target;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) {{
        if (e.key === 'Escape') {{ t.blur(); closeAllModals(); }}
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
        if (secs[n]) secs[n].scrollIntoView({{ behavior: PREFERS_REDUCED_MOTION ? 'auto' : 'smooth' }});
      }}
    }});
  }}

  function setupButtons() {{
    var themeBtn = document.getElementById('btn-theme-toggle');
    if (themeBtn) themeBtn.addEventListener('click', cycleTheme);
    var copyBtn = document.getElementById('btn-copy-link');
    if (copyBtn) copyBtn.addEventListener('click', copyLink);
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
    initAllCharts();
    setupSortableTable();
    setupTableSearch();
    setupCopyCsv();
    setupCopyPng();
    setupDrillPanel();
    setupChannelDrilldowns();
    setupCounters();
    setupBudgetWhatIf();
    setupScenarioSwitcher();
    setupSearch();
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', boot);
  }} else {{
    boot();
  }}

  // Expose hooks
  window.AURORA_APP = {{
    toast: toast,
    copyLink: copyLink,
    cycleTheme: cycleTheme,
    applyTheme: applyTheme,
    data: CHART_DATA,
    modelContext: MODEL_CTX,
    charts: AURORA_CHARTS,
  }};
}})();
"""
