"""
Chart helpers — native PPTX chart generation with tokens-driven styling.

Four MMM chart types per CLIENT_READY_ANATOMY.md §6:
  1. Waterfall (decomposition) — BAR_STACKED with baseline + per-channel contribs
  2. ROI bar — BAR_CLUSTERED horizontal, muted-except-one-gold
  3. Share of Spend vs Effect — 100% stacked COLUMN_CLUSTERED
  4. Timeline stacked area — AREA_STACKED over dates

All use theme colors auto-assigned by PowerPoint from our themed .pptx container.
Overrides applied via format.fill.solid() for specific highlights.

M3 Session 3: implement in detail. Currently stubs returning the chart frame
for downstream positioning.
"""

from __future__ import annotations

from pptx.chart.data import CategoryChartData, XyChartData
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
from pptx.util import Inches, Pt

from .tokens import COLOR, FONT


def _style_chart_text(chart) -> None:
    """Apply tokens-driven axes/legend styling to a chart."""
    # Axes
    for axis in (chart.category_axis, chart.value_axis):
        try:
            axis.tick_labels.font.size = Pt(10)
            axis.tick_labels.font.name = FONT.family.sans
            axis.tick_labels.font.color.rgb = COLOR.brand.deep_80
        except Exception:
            pass
    # Legend
    if chart.has_legend:
        chart.legend.font.size = Pt(10)
        chart.legend.font.name = FONT.family.sans
        chart.legend.font.color.rgb = COLOR.brand.deep_80


def make_roi_bar(slide, x_in, y_in, w_in, h_in, *, channels, roi_values, highlight_idx=None):
    """Horizontal bar chart: ROI per channel. M3 stub."""
    data = CategoryChartData()
    data.categories = channels
    data.add_series("ROI", roi_values)
    graphic_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.BAR_CLUSTERED,
        Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in),
        data
    )
    chart = graphic_frame.chart
    chart.has_legend = False
    _style_chart_text(chart)
    # Color series: muted by default
    for i, point in enumerate(chart.plots[0].series[0].points):
        point.format.fill.solid()
        if highlight_idx == i:
            point.format.fill.fore_color.rgb = COLOR.brand.gold
        else:
            point.format.fill.fore_color.rgb = COLOR.brand.deep_40
    return graphic_frame


def make_share_comparison(slide, x_in, y_in, w_in, h_in, *, channels, spend_shares, effect_shares):
    """Two-column stacked comparison: Spend vs Effect per channel. M3 stub."""
    data = CategoryChartData()
    data.categories = ["Доля бюджета", "Доля эффекта"]
    for i, channel in enumerate(channels):
        values = (spend_shares[i], effect_shares[i])
        data.add_series(channel, values)
    graphic_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_STACKED_100,
        Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in),
        data
    )
    chart = graphic_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    chart.legend.include_in_layout = False
    _style_chart_text(chart)
    # Color each series via channel_colors palette
    for i, series in enumerate(chart.plots[0].series):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = COLOR.data.channel_colors[i % len(COLOR.data.channel_colors)]
    return graphic_frame


def make_decomposition_stacked(slide, x_in, y_in, w_in, h_in, *, categories, series_data):
    """Stacked bar chart (waterfall fallback): decomposition of KPI.
    series_data: dict {name: [values]}. M3 stub.
    """
    data = CategoryChartData()
    data.categories = categories
    for name, values in series_data.items():
        data.add_series(name, values)
    graphic_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.BAR_STACKED,
        Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in),
        data
    )
    chart = graphic_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    _style_chart_text(chart)
    for i, series in enumerate(chart.plots[0].series):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = COLOR.data.channel_colors[i % len(COLOR.data.channel_colors)]
    return graphic_frame


def make_timeline_area(slide, x_in, y_in, w_in, h_in, *, dates, baseline, channel_series):
    """Stacked area: KPI over time with baseline + channel contributions.
    channel_series: dict {channel_name: [values]}. M3 stub.
    """
    data = CategoryChartData()
    data.categories = dates
    data.add_series("Baseline", baseline)
    for name, values in channel_series.items():
        data.add_series(name, values)
    graphic_frame = slide.shapes.add_chart(
        XL_CHART_TYPE.AREA_STACKED,
        Inches(x_in), Inches(y_in), Inches(w_in), Inches(h_in),
        data
    )
    chart = graphic_frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.BOTTOM
    _style_chart_text(chart)
    # Baseline = muted grey, channels = palette
    series_list = list(chart.plots[0].series)
    if series_list:
        series_list[0].format.fill.solid()
        series_list[0].format.fill.fore_color.rgb = COLOR.brand.deep_40
        for i, series in enumerate(series_list[1:]):
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = COLOR.data.channel_colors[i % len(COLOR.data.channel_colors)]
    return graphic_frame
