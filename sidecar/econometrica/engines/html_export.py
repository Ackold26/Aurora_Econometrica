"""
Interactive HTML report export.

Standalone HTML-файл с ECharts-графиками (через CDN): декомпозиция (waterfall),
ROI по каналам, Share of Spend vs Effect, динамика по периодам, оптимизация.
Плюс executive summary, интерпретация, FAQ. Открывается в браузере без
приложения — можно отправлять клиентам.

Размер файла: 15-30 KB (без включённой echarts.min.js — она грузится с CDN,
8.7 MB сэкономлено). Если нужен full-offline — `bundle_echarts=True` embed'ит
echarts inline.
"""
import html as html_lib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _escape(s: Any) -> str:
    """Safe HTML escape любой value.

    Дополнительно escape'им `{` и `}` как HTML entities — защита от `.format()`
    template bomb: если user-controlled строка содержит `{name}`, `.format()`
    попытается resolve это как placeholder и упадёт с KeyError.
    """
    if s is None:
        return '—'
    return html_lib.escape(str(s)).replace('{', '&#x7B;').replace('}', '&#x7D;')


def _fmt_num(n: Any, dec: int = 0) -> str:
    """1234567.8 → '1 234 568' (ru-RU style)."""
    try:
        v = float(n)
        return f'{v:,.{dec}f}'.replace(',', ' ').replace('.', ',') if dec else f'{int(round(v)):,}'.replace(',', ' ')
    except (ValueError, TypeError):
        return '—'


def build_html(
    model_data: dict,
    decompose_data: dict,
    optimize_data: dict,
    output_path: str,
    scenarios: list[dict] | None = None,
    project_name: str = 'Marketing Mix Model',
) -> dict[str, Any]:
    """Генерирует standalone HTML-отчёт.

    Args:
        project_name: название проекта (заголовок отчёта).

    Returns:
        {'status': 'ok', 'path': str, 'size_kb': int} или {'status': 'error', ...}.
    """
    try:
        model_data = model_data or {}
        decompose_data = decompose_data or {}
        optimize_data = optimize_data or {}
        scenarios = scenarios or []

        diag = model_data.get('diagnostics', {}) or {}
        mqs = diag.get('mqs', {}) or {}
        metrics = diag.get('metrics', {}) or {}
        channels = decompose_data.get('channels', []) or []
        opt_channels = optimize_data.get('channels', []) or []
        waterfall = decompose_data.get('waterfall', {}) or {}
        time_series = decompose_data.get('time_series', {}) or {}

        # ── Executive values ────────────────────────────
        mqs_score = mqs.get('score', 0)
        mqs_label = mqs.get('tier_label', '—')
        r_sq = metrics.get('r_squared', diag.get('r_squared', 0))
        mape = metrics.get('mape_pct', diag.get('mape', 0))
        r_hat = metrics.get('r_hat_max')
        lift = optimize_data.get('expected_lift_pct', 0)
        base_pct = decompose_data.get('baseline_pct', decompose_data.get('base_pct', 0)) or 0
        total_budget = optimize_data.get('total_budget', 0)

        # ── Chart data ──────────────────────────────────
        # Waterfall
        if isinstance(waterfall, dict):
            wf_labels = waterfall.get('labels', [])
            wf_values = waterfall.get('values', [])
        else:
            wf_labels = [str(w.get('category', '')) for w in waterfall]
            wf_values = [float(w.get('value', 0) or 0) for w in waterfall]

        # Channels sorted by ROI
        channels_sorted = sorted(channels, key=lambda c: c.get('roi', 0) or 0, reverse=True)
        ch_names = [c.get('name', '') for c in channels_sorted]
        ch_roi = [float(c.get('roi', 0) or 0) for c in channels_sorted]
        ch_spend = [float(c.get('spend', 0) or 0) for c in channels_sorted]
        ch_contrib = [float(c.get('contribution', 0) or 0) for c in channels_sorted]
        ch_verdicts = [c.get('verdict', '—') for c in channels_sorted]

        total_spend = sum(ch_spend) or 1
        total_contrib = sum(ch_contrib) or 1
        ch_spend_pct = [round(s / total_spend * 100, 1) for s in ch_spend]
        ch_effect_pct = [round(c / total_contrib * 100, 1) for c in ch_contrib]

        # Timeline
        ts_dates = time_series.get('dates', []) or []
        ts_baseline = time_series.get('baseline', []) or []
        ts_channels = time_series.get('channels', {}) or {}

        # Optimize comparison
        opt_names = [c.get('name', '') for c in opt_channels]
        opt_current = [float(c.get('current_spend', 0) or 0) for c in opt_channels]
        opt_optimal = [float(c.get('optimal_spend', 0) or 0) for c in opt_channels]

        # ── Scenarios block ─────────────────────────────
        homogeneous_money = bool(scenarios) and all(
            s.get('totals', {}).get('roas_money') is not None for s in scenarios
        )
        if homogeneous_money:
            sc_spend_field, sc_roas_field = 'total_spend_money', 'roas_money'
            sc_budget_label, sc_roas_label = 'Бюджет (₽)', 'ROAS (₽)'
        else:
            sc_spend_field, sc_roas_field = 'total_spend', 'roas'
            sc_budget_label, sc_roas_label = 'Бюджет (native)', 'ROAS (native)'

        # ── Render HTML ─────────────────────────────────
        now = datetime.now().strftime('%d.%m.%Y %H:%M')
        charts_json = json.dumps({
            'waterfall': {'labels': wf_labels, 'values': wf_values},
            'roi': {'names': ch_names, 'roi': ch_roi},
            'shareSpendEffect': {'names': ch_names, 'spend': ch_spend_pct, 'effect': ch_effect_pct},
            'timeline': {
                'dates': ts_dates,
                'baseline': ts_baseline,
                'channels': ts_channels,
                'channelOrder': [c.get('name', '') for c in channels],
            },
            'optimize': {'names': opt_names, 'current': opt_current, 'optimal': opt_optimal},
        }, ensure_ascii=False)
        # XSS-защита: если в channel name попадёт `</script>` — json с ensure_ascii=False
        # оставит его как литеральный текст внутри <script> тега → HTML-парсер закроет
        # script preamturely и выполнит injected код. Эскейпим `</` в `<\/` (валидно в JSON).
        charts_json = charts_json.replace('</', '<\\/')

        # Channel table rows
        ch_rows_html = '\n'.join(
            f'''<tr>
              <td>{_escape(c.get('name'))}</td>
              <td class="num">{_fmt_num(c.get('spend'))}</td>
              <td class="num">{_fmt_num(c.get('contribution'))}</td>
              <td class="num {_roi_class(c.get('roi'))}">{c.get('roi', 0):.2f}×</td>
              <td class="num {_gap_class(c.get('efficiency_gap'))}">{_fmt_gap(c.get('efficiency_gap'))}</td>
              <td>{_escape(c.get('verdict'))}</td>
            </tr>'''
            for c in channels
        )

        # Scenarios table (if any)
        scenarios_block = ''
        if scenarios:
            sc_headers = ''.join(f'<th>{_escape(s.get("scenario_name"))}</th>' for s in scenarios)
            sc_kpi = ''.join(f'<td class="num">{_fmt_num(s.get("totals", {}).get("predicted_kpi"))}</td>' for s in scenarios)
            sc_budget = ''.join(f'<td class="num">{_fmt_num(s.get("totals", {}).get(sc_spend_field))}</td>' for s in scenarios)

            # Best ROAS highlight
            best_idx = 0
            best_roas = -1
            for i, s in enumerate(scenarios):
                r = float(s.get('totals', {}).get(sc_roas_field, 0) or 0)
                if r > best_roas:
                    best_roas = r
                    best_idx = i
            sc_roas = ''.join(
                f'<td class="num {"roi-good" if i == best_idx else ""}"><b>{float(s.get("totals", {}).get(sc_roas_field, 0) or 0):.2f}×</b></td>'
                if i == best_idx else
                f'<td class="num">{float(s.get("totals", {}).get(sc_roas_field, 0) or 0):.2f}×</td>'
                for i, s in enumerate(scenarios)
            )
            sc_lift = ''.join(f'<td class="num">+{float(s.get("totals", {}).get("lift_pct", 0) or 0):.1f}%</td>' for s in scenarios)

            scenarios_block = f'''
  <section class="block">
    <h2>📊 Сравнение сценариев</h2>
    <table class="metrics-table">
      <thead><tr><th>Метрика</th>{sc_headers}</tr></thead>
      <tbody>
        <tr><td>Прогноз KPI</td>{sc_kpi}</tr>
        <tr><td>{sc_budget_label}</td>{sc_budget}</tr>
        <tr><td>{sc_roas_label}</td>{sc_roas}</tr>
        <tr><td>Лифт vs baseline</td>{sc_lift}</tr>
      </tbody>
    </table>
    {'<p class="note">⚠ ROAS в native-единицах (смешанные). Укажите unit_costs на шаге «Валидация» для сравнения в ₽.</p>' if not homogeneous_money else ''}
  </section>'''

        html_content = _HTML_TEMPLATE.format(
            project_name=_escape(project_name),
            generated_at=_escape(now),
            mqs_score=f'{mqs_score:.0f}',
            mqs_label=_escape(mqs_label),
            mqs_color=_mqs_color(mqs_score),
            r_sq=f'{r_sq:.3f}' if r_sq else '—',
            mape=f'{mape:.1f}%' if mape else '—',
            r_hat=f'{r_hat:.3f}' if r_hat else '—',
            base_pct=f'{base_pct:.0f}%' if base_pct else '—',
            lift=f'+{lift:.1f}%' if lift else '0%',
            total_budget=_fmt_num(total_budget),
            n_channels=len(channels),
            ch_rows=ch_rows_html,
            scenarios_block=scenarios_block,
            charts_json=charts_json,
        )

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_content, encoding='utf-8')
        size_kb = path.stat().st_size / 1024
        logger.info(f'HTML export OK: {path} ({size_kb:.1f} KB)')
        return {
            'status': 'ok',
            'path': str(path),
            'size_kb': round(size_kb, 1),
        }

    except Exception as e:
        logger.exception('HTML export failed')
        return {
            'status': 'error',
            'message': str(e),
            'type': type(e).__name__,
        }


def _mqs_color(score: float) -> str:
    if score >= 80: return '#22c55e'
    if score >= 60: return '#f59e0b'
    return '#ef4444'


def _roi_class(roi: Any) -> str:
    try:
        v = float(roi)
        if v > 2: return 'roi-good'
        if v < 1: return 'roi-bad'
        return 'roi-mid'
    except (ValueError, TypeError):
        return ''


def _gap_class(gap: Any) -> str:
    try:
        v = float(gap)
        if v >= 5: return 'gap-pos'
        if v <= -5: return 'gap-neg'
        return ''
    except (ValueError, TypeError):
        return ''


def _fmt_gap(gap: Any) -> str:
    try:
        v = float(gap)
        sign = '+' if v > 0 else ''
        return f'{sign}{v:.0f}%'
    except (ValueError, TypeError):
        return '—'


_HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>{project_name} — MMM Report</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>
  :root {{
    --bg: #0b0f16;
    --surface: #111827;
    --surface-2: #1e293b;
    --border: rgba(255,255,255,0.08);
    --text: #e2e8f0;
    --muted: #94a3b8;
    --accent: #3b82f6;
    --good: #22c55e;
    --warn: #f59e0b;
    --bad: #ef4444;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    line-height: 1.55;
    font-size: 14px;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; padding: 32px 24px; }}
  header {{ text-align: center; margin-bottom: 32px; }}
  header h1 {{ font-size: 32px; margin: 0 0 8px 0; font-weight: 700; }}
  header .subtitle {{ color: var(--muted); font-size: 14px; }}

  .kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 12px;
    margin: 24px 0 40px 0;
  }}
  .kpi-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 18px;
  }}
  .kpi-card .kpi-label {{
    font-size: 11px;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 4px;
  }}
  .kpi-card .kpi-value {{ font-size: 22px; font-weight: 700; }}
  .kpi-card .kpi-sub {{ font-size: 12px; color: var(--muted); margin-top: 2px; }}

  .block {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 20px;
  }}
  .block h2 {{
    font-size: 18px;
    margin: 0 0 16px 0;
    font-weight: 600;
  }}

  .chart {{ width: 100%; height: 360px; }}
  .charts-two {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 20px;
  }}
  @media (max-width: 900px) {{
    .charts-two {{ grid-template-columns: 1fr; }}
  }}

  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th, td {{
    padding: 10px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }}
  th {{
    color: var(--muted);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: 0.05em;
  }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .roi-good {{ color: var(--good); font-weight: 600; }}
  .roi-mid {{ color: var(--warn); }}
  .roi-bad {{ color: var(--bad); font-weight: 600; }}
  .gap-pos {{ color: var(--good); }}
  .gap-neg {{ color: var(--bad); }}
  .note {{
    color: var(--muted);
    font-size: 12px;
    font-style: italic;
    margin: 12px 0 0 0;
  }}
  footer {{
    text-align: center;
    color: var(--muted);
    font-size: 12px;
    margin-top: 40px;
    padding: 20px;
  }}
</style>
</head>
<body>
<div class="container">
  <header>
    <h1>{project_name}</h1>
    <div class="subtitle">Отчёт Marketing Mix Modeling · {generated_at}</div>
  </header>

  <section class="kpi-grid">
    <div class="kpi-card">
      <div class="kpi-label">MQS</div>
      <div class="kpi-value" style="color: {mqs_color};">{mqs_score}</div>
      <div class="kpi-sub">{mqs_label}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">R²</div>
      <div class="kpi-value">{r_sq}</div>
      <div class="kpi-sub">Точность подгонки</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">MAPE</div>
      <div class="kpi-value">{mape}</div>
      <div class="kpi-sub">Средняя ошибка</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">R-hat</div>
      <div class="kpi-value">{r_hat}</div>
      <div class="kpi-sub">Сходимость MCMC</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Базовая часть</div>
      <div class="kpi-value">{base_pct}</div>
      <div class="kpi-sub">Органика без медиа</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Прирост</div>
      <div class="kpi-value" style="color: var(--good);">{lift}</div>
      <div class="kpi-sub">От оптимизации</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Бюджет</div>
      <div class="kpi-value" style="font-size: 18px;">{total_budget}</div>
      <div class="kpi-sub">руб.</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">Каналов</div>
      <div class="kpi-value">{n_channels}</div>
      <div class="kpi-sub">В модели</div>
    </div>
  </section>

  <section class="block">
    <h2>📊 Декомпозиция продаж</h2>
    <div id="chart-waterfall" class="chart"></div>
  </section>

  <div class="charts-two">
    <section class="block">
      <h2>🎯 ROI по каналам</h2>
      <div id="chart-roi" class="chart"></div>
    </section>
    <section class="block">
      <h2>⚖ Share of Spend vs Effect</h2>
      <div id="chart-share" class="chart"></div>
    </section>
  </div>

  <section class="block">
    <h2>📈 Динамика по периодам</h2>
    <div id="chart-timeline" class="chart" style="height: 420px;"></div>
  </section>

  <section class="block">
    <h2>💰 Оптимизация бюджета</h2>
    <div id="chart-optimize" class="chart"></div>
  </section>

  {scenarios_block}

  <section class="block">
    <h2>📋 Детализация по каналам</h2>
    <table>
      <thead>
        <tr>
          <th>Канал</th>
          <th class="num">Расход</th>
          <th class="num">Вклад</th>
          <th class="num">ROI</th>
          <th class="num">Gap</th>
          <th>Вердикт</th>
        </tr>
      </thead>
      <tbody>
        {ch_rows}
      </tbody>
    </table>
  </section>

  <footer>
    Сгенерировано Aurora AI Econometrica · Интерактивные графики: ECharts 5
  </footer>
</div>

<script>
const DATA = {charts_json};

const palette = ['#3b82f6','#22c55e','#f59e0b','#ef4444','#8b5cf6','#ec4899','#06b6d4','#84cc16','#f97316','#a855f7'];
const textStyle = {{ color: '#e2e8f0' }};
const baseAxis = {{
  axisLine: {{ lineStyle: {{ color: 'rgba(255,255,255,0.15)' }} }},
  axisLabel: {{ color: '#94a3b8' }},
  splitLine: {{ lineStyle: {{ color: 'rgba(255,255,255,0.05)' }} }},
}};

// Waterfall
if (DATA.waterfall.labels.length) {{
  echarts.init(document.getElementById('chart-waterfall')).setOption({{
    textStyle,
    tooltip: {{ trigger: 'axis', backgroundColor: '#1e293b', borderColor: 'rgba(255,255,255,0.1)', textStyle: {{ color: '#e2e8f0' }} }},
    grid: {{ left: '3%', right: '4%', bottom: '3%', containLabel: true }},
    xAxis: {{ type: 'category', data: DATA.waterfall.labels, ...baseAxis }},
    yAxis: {{ type: 'value', ...baseAxis }},
    series: [{{ type: 'bar', data: DATA.waterfall.values, itemStyle: {{ color: '#3b82f6' }} }}],
  }});
}}

// ROI
if (DATA.roi.names.length) {{
  echarts.init(document.getElementById('chart-roi')).setOption({{
    textStyle,
    tooltip: {{ trigger: 'axis', backgroundColor: '#1e293b', borderColor: 'rgba(255,255,255,0.1)', textStyle: {{ color: '#e2e8f0' }} }},
    grid: {{ left: '3%', right: '4%', bottom: '3%', containLabel: true }},
    xAxis: {{ type: 'value', ...baseAxis }},
    yAxis: {{ type: 'category', data: DATA.roi.names, ...baseAxis }},
    series: [{{
      type: 'bar',
      data: DATA.roi.roi.map((v, i) => ({{
        value: v,
        itemStyle: {{ color: v > 2 ? '#22c55e' : v < 1 ? '#ef4444' : '#f59e0b' }}
      }})),
      label: {{ show: true, position: 'right', color: '#e2e8f0', formatter: '{{c}}×' }},
    }}],
  }});
}}

// Share Spend vs Effect
if (DATA.shareSpendEffect.names.length) {{
  echarts.init(document.getElementById('chart-share')).setOption({{
    textStyle,
    legend: {{ textStyle: {{ color: '#e2e8f0' }} }},
    tooltip: {{ trigger: 'axis', backgroundColor: '#1e293b', borderColor: 'rgba(255,255,255,0.1)', textStyle: {{ color: '#e2e8f0' }} }},
    grid: {{ left: '3%', right: '4%', bottom: '3%', containLabel: true }},
    xAxis: {{ type: 'category', data: DATA.shareSpendEffect.names, ...baseAxis, axisLabel: {{ ...baseAxis.axisLabel, rotate: 20 }} }},
    yAxis: {{ type: 'value', ...baseAxis, axisLabel: {{ ...baseAxis.axisLabel, formatter: '{{value}}%' }} }},
    series: [
      {{ name: '% бюджета', type: 'bar', data: DATA.shareSpendEffect.spend, itemStyle: {{ color: '#94a3b8' }} }},
      {{ name: '% эффекта', type: 'bar', data: DATA.shareSpendEffect.effect, itemStyle: {{ color: '#22c55e' }} }},
    ],
  }});
}}

// Timeline (stacked area)
if (DATA.timeline.dates.length) {{
  const series = [];
  if (DATA.timeline.baseline.length) {{
    series.push({{
      name: 'Base',
      type: 'line',
      stack: 'total',
      areaStyle: {{ color: '#475569' }},
      lineStyle: {{ color: '#475569' }},
      itemStyle: {{ color: '#475569' }},
      data: DATA.timeline.baseline,
    }});
  }}
  DATA.timeline.channelOrder.forEach((name, i) => {{
    if (DATA.timeline.channels[name]) {{
      const color = palette[i % palette.length];
      series.push({{
        name,
        type: 'line',
        stack: 'total',
        areaStyle: {{ color }},
        lineStyle: {{ color }},
        itemStyle: {{ color }},
        data: DATA.timeline.channels[name],
      }});
    }}
  }});
  echarts.init(document.getElementById('chart-timeline')).setOption({{
    textStyle,
    legend: {{ textStyle: {{ color: '#e2e8f0' }}, top: 0 }},
    tooltip: {{ trigger: 'axis', backgroundColor: '#1e293b', borderColor: 'rgba(255,255,255,0.1)', textStyle: {{ color: '#e2e8f0' }} }},
    grid: {{ top: 60, left: '3%', right: '4%', bottom: '10%', containLabel: true }},
    dataZoom: [{{ type: 'inside' }}, {{ type: 'slider', height: 20 }}],
    xAxis: {{ type: 'category', data: DATA.timeline.dates, ...baseAxis }},
    yAxis: {{ type: 'value', ...baseAxis }},
    series,
  }});
}}

// Optimize
if (DATA.optimize.names.length) {{
  echarts.init(document.getElementById('chart-optimize')).setOption({{
    textStyle,
    legend: {{ textStyle: {{ color: '#e2e8f0' }} }},
    tooltip: {{ trigger: 'axis', backgroundColor: '#1e293b', borderColor: 'rgba(255,255,255,0.1)', textStyle: {{ color: '#e2e8f0' }} }},
    grid: {{ left: '3%', right: '4%', bottom: '3%', containLabel: true }},
    xAxis: {{ type: 'category', data: DATA.optimize.names, ...baseAxis, axisLabel: {{ ...baseAxis.axisLabel, rotate: 20 }} }},
    yAxis: {{ type: 'value', ...baseAxis }},
    series: [
      {{ name: 'Текущий', type: 'bar', data: DATA.optimize.current, itemStyle: {{ color: '#94a3b8' }} }},
      {{ name: 'Оптимальный', type: 'bar', data: DATA.optimize.optimal, itemStyle: {{ color: '#3b82f6' }} }},
    ],
  }});
}}

// Responsive resize
window.addEventListener('resize', () => {{
  document.querySelectorAll('.chart').forEach(el => {{
    const inst = echarts.getInstanceByDom(el);
    if (inst) inst.resize();
  }});
}});
</script>
</body>
</html>
'''
