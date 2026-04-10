"""
Matplotlib dark theme matching Aurora AI Aether Mesh design system.
Call apply_theme() before generating any chart.
"""
import io as _io
import base64 as _base64
import matplotlib as mpl
import matplotlib.pyplot as plt


# Aurora AI color palette
COLORS = {
    'bg': '#0f1117',
    'surface': '#1a1d27',
    'text': '#e2e8f0',
    'text_secondary': '#94a3b8',
    'accent': '#3b82f6',
    'accent_secondary': '#6366f1',
    'success': '#22c55e',
    'warning': '#f59e0b',
    'error': '#ef4444',
    'grid': '#1e293b',
}

# Channel color palette (consistent across all charts)
CHANNEL_COLORS = [
    '#3b82f6',  # blue
    '#8b5cf6',  # violet
    '#06b6d4',  # cyan
    '#22c55e',  # green
    '#f59e0b',  # amber
    '#ef4444',  # red
    '#ec4899',  # pink
    '#14b8a6',  # teal
    '#f97316',  # orange
    '#a855f7',  # purple
]


def apply_theme():
    """Apply Aurora dark theme to matplotlib."""
    mpl.rcParams.update({
        'figure.facecolor': COLORS['bg'],
        'axes.facecolor': COLORS['surface'],
        'axes.edgecolor': COLORS['grid'],
        'axes.labelcolor': COLORS['text'],
        'axes.titlecolor': COLORS['text'],
        'xtick.color': COLORS['text_secondary'],
        'ytick.color': COLORS['text_secondary'],
        'text.color': COLORS['text'],
        'grid.color': COLORS['grid'],
        'grid.alpha': 0.3,
        'legend.facecolor': COLORS['surface'],
        'legend.edgecolor': COLORS['grid'],
        'font.size': 11,
        'axes.titlesize': 14,
        'axes.labelsize': 12,
        'figure.dpi': 100,
        'savefig.dpi': 100,
        'savefig.bbox': 'tight',
        'savefig.facecolor': COLORS['bg'],
    })


def fig_to_base64(fig, dpi: int = 100) -> str:
    """Convert matplotlib figure to base64 PNG string."""
    buf = _io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', facecolor=COLORS['bg'], dpi=dpi)
    plt.close(fig)
    buf.seek(0)
    return _base64.b64encode(buf.getvalue()).decode('utf-8')
