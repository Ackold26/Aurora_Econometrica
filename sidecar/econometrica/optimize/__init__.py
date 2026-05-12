"""Aurora Econometrica - optimize package (v1.3.0).

Modular optimization tools layered on top of `engines/optimizer.py`:
- bounds: safe corridor computation (per-channel + aggregate budget bounds).
- inverse: bisection-based goal-seek (find min budget for target sales).
- goal_seek: high-level wrapper with auto-pricing + posterior CI.
- auto_price: auto-suggest value_per_count_unit from data.

Per ADR-014 (Safe corridor bounds), ADR-016 (KPI kinds binary semantics).

Usage:
    from optimize.bounds import compute_safe_corridor
    from optimize.inverse import optimize_inverse
    from optimize.goal_seek import goal_seek
    from optimize.auto_price import detect_price_per_pack
"""
