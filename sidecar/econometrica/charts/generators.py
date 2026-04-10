"""
Chart generators for Econometrica.
All charts return base64 PNG strings for embedding in Svelte UI.
"""
import numpy as np
import matplotlib.pyplot as plt
from .theme import apply_theme, fig_to_base64, COLORS, CHANNEL_COLORS


apply_theme()


def waterfall_chart(data: dict) -> str:
    """Generate waterfall decomposition chart.

    Args:
        data: {'labels': [...], 'values': [...], 'types': ['baseline', 'channel', ...]}
    Returns:
        Base64 PNG string
    """
    labels = data['labels']
    values = data['values']
    types = data['types']
    n = len(labels)

    fig, ax = plt.subplots(figsize=(max(10, n * 0.8), 6))

    cumulative = 0
    bottoms = []
    colors = []
    for i, (val, typ) in enumerate(zip(values, types)):
        if typ == 'baseline':
            bottoms.append(0)
            colors.append(COLORS['text_secondary'])
            cumulative = val
        elif typ == 'total':
            bottoms.append(0)
            colors.append(COLORS['accent'])
        else:
            bottoms.append(cumulative)
            colors.append(CHANNEL_COLORS[i % len(CHANNEL_COLORS)])
            cumulative += val

    ax.bar(range(n), values, bottom=bottoms, color=colors, width=0.6, edgecolor='none')

    # Value labels
    for i, (val, bottom) in enumerate(zip(values, bottoms)):
        y_pos = bottom + val / 2
        label = f'{val:,.0f}'
        ax.text(i, y_pos, label, ha='center', va='center', fontsize=9,
                color='white', fontweight='bold')

    ax.set_xticks(range(n))
    ax.set_xticklabels(labels, rotation=30, ha='right', fontsize=9)
    ax.set_ylabel('Продажи')
    ax.set_title('Декомпозиция продаж по каналам')
    ax.grid(axis='y', alpha=0.2)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    return fig_to_base64(fig)


def response_curves_chart(data: dict) -> str:
    """Generate response curves for all channels.

    Args:
        data: {channel_name: {'spend': [...], 'response': [...], 'current_x': float, 'optimal_x': float}}
    """
    n_channels = len(data)
    cols = min(3, n_channels)
    rows = (n_channels + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows))
    if n_channels == 1:
        axes = [axes]
    else:
        axes = axes.flatten() if hasattr(axes, 'flatten') else [axes]

    for i, (channel, curve) in enumerate(data.items()):
        if i >= len(axes):
            break
        ax = axes[i]
        spend = curve['spend']
        response = curve['response']
        current_x = curve['current_x']
        optimal_x = curve['optimal_x']

        ax.plot(spend, response, color=CHANNEL_COLORS[i % len(CHANNEL_COLORS)], linewidth=2)
        ax.axvline(current_x, color=COLORS['text_secondary'], linestyle='--', alpha=0.7, label='Текущий')
        ax.axvline(optimal_x, color=COLORS['success'], linestyle='--', alpha=0.7, label='Оптимальный')
        ax.set_title(channel, fontsize=11)
        ax.set_xlabel('Бюджет')
        ax.set_ylabel('Эффект')
        ax.legend(fontsize=8)
        ax.grid(alpha=0.2)

    # Hide empty subplots
    for j in range(i + 1, len(axes)):
        axes[j].set_visible(False)

    fig.suptitle('Response Curves по каналам', fontsize=14, y=1.02)
    fig.tight_layout()
    return fig_to_base64(fig)


def awareness_chart(historical: list, forecast: list,
                    ci_lower: list, ci_upper: list) -> str:
    """Generate awareness forecast chart with CI band.

    Args:
        historical: Past awareness values
        forecast: Predicted future values
        ci_lower, ci_upper: Confidence interval bounds
    """
    fig, ax = plt.subplots(figsize=(12, 5))

    n_hist = len(historical)
    n_fore = len(forecast)
    x_hist = list(range(n_hist))
    x_fore = list(range(n_hist, n_hist + n_fore))

    # Historical
    ax.plot(x_hist, historical, color=COLORS['accent'], linewidth=2, label='Факт')

    # Forecast
    ax.plot(x_fore, forecast, color=COLORS['success'], linewidth=2, linestyle='--', label='Прогноз')
    ax.fill_between(x_fore, ci_lower, ci_upper, color=COLORS['success'], alpha=0.15, label='95% CI')

    # Divider line
    ax.axvline(n_hist - 0.5, color=COLORS['text_secondary'], linestyle=':', alpha=0.5)

    ax.set_xlabel('Период')
    ax.set_ylabel('Awareness, %')
    ax.set_title('Прогноз уровня знания бренда')
    ax.legend()
    ax.grid(alpha=0.2)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    return fig_to_base64(fig)


def s_curve_chart(curve_data: dict) -> str:
    """Generate S-curve chart: awareness → sales.

    Args:
        curve_data: {'x': [...], 'y': [...], 'actual_x': [...], 'actual_y': [...]}
    """
    fig, ax = plt.subplots(figsize=(10, 6))

    # Fitted curve
    ax.plot(curve_data['x'], curve_data['y'],
            color=COLORS['accent'], linewidth=2.5, label='S-кривая (модель)')

    # Actual data points
    ax.scatter(curve_data['actual_x'], curve_data['actual_y'],
               color=COLORS['warning'], s=40, alpha=0.7, label='Фактические данные', zorder=5)

    ax.set_xlabel('Awareness, %')
    ax.set_ylabel('Продажи')
    ax.set_title('Зависимость продаж от уровня знания бренда')
    ax.legend()
    ax.grid(alpha=0.2)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

    return fig_to_base64(fig)


def mqs_gauge(score: float, tier: str, color: str) -> str:
    """Generate MQS (Model Quality Score) gauge visualization.

    Args:
        score: MQS score (0-100)
        tier: Tier label
        color: Hex color for the tier
    """
    fig, ax = plt.subplots(figsize=(3, 3))

    # Draw arc
    theta = np.linspace(np.pi, 0, 100)
    ax.plot(np.cos(theta), np.sin(theta), color=COLORS['grid'], linewidth=8, solid_capstyle='round')

    # Filled portion
    fill_pct = score / 100
    theta_fill = np.linspace(np.pi, np.pi * (1 - fill_pct), max(2, int(100 * fill_pct)))
    ax.plot(np.cos(theta_fill), np.sin(theta_fill), color=color, linewidth=8, solid_capstyle='round')

    # Score text
    ax.text(0, 0.15, f'{score:.0f}', ha='center', va='center',
            fontsize=28, fontweight='bold', color=color)
    ax.text(0, -0.15, tier, ha='center', va='center',
            fontsize=11, color=COLORS['text_secondary'])

    ax.set_xlim(-1.3, 1.3)
    ax.set_ylim(-0.4, 1.3)
    ax.axis('off')
    fig.patch.set_facecolor(COLORS['bg'])

    return fig_to_base64(fig)
