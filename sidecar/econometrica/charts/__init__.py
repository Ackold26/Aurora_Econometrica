"""Chart generation package (headless).

Sidecar рендерит графики без окон: бэкенд matplotlib фиксируется здесь,
в точке входа пакета, ДО импорта pyplot подмодулями (generators/theme).
Без этого matplotlib на машине с установленным, но битым Tcl/Tk выбирает
TkAgg и падает TclError при первом plt.subplots (флак pytest 2026-07-18;
клиентский бандл PyInstaller тоже не исключает tkinter).
"""
import matplotlib

matplotlib.use("Agg")
