"""
Turns backtest results into a single dashboard web page (index.html / report.html).
Used by:  python backtest.py --html report.html
and by the GitHub "Backtest dashboard" workflow, which publishes it on GitHub Pages.
"""
import html
from datetime import datetime, timezone, timedelta

import pandas as pd

import config

IST = timezone(timedelta(hours=5, minutes=30))


def _rs(v):
    sign = "−" if v < 0 else ""
    return f"{sign}₹{abs(v):,.0f}"


def _equity_svg(t: pd.DataFrame) -> str:
    if t.empty:
        return '<p class="muted">No trades in this period, so there is no equity curve.</p>'
    eq = t.pnl_rs.cumsum().tolist()
    eq = [0.0] + eq
    W, H, P, PL = 900, 260, 34, 84
    lo, hi = min(eq + [0]), max(eq + [0])
    span = (hi - lo) or 1
    x = lambda i: PL + (W - PL - P) * i / max(1, len(eq) - 1)
    y = lambda v: P + (H - 2 * P) * (1 - (v - lo) / span)
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(eq))
    area = f"{x(0):.1f},{y(0):.1f} " + pts + f" {x(len(eq) - 1):.1f},{y(0):.1f}"
    colour = "var(--up)" if eq[-1] >= 0 else "var(--down)"
    ticks = "".join(
        f'<line x1="{PL}" x2="{W - P}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
        f'<text x="{PL - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="tick">{_rs(v)}</text>'
        for v in sorted({lo, 0.0, hi})
    )
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Cumulative profit and loss">'
            f'{ticks}<polygon points="{area}" fill="{colour}" opacity=".12"/>'
            f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<circle cx="{x(len(eq) - 1):.1f}" cy="{y(eq[-1]):.1f}" r="4.5" fill="{colour}"/></svg>')


def write(trades: pd.DataFrame, data: pd.DataFrame, path: str):
    from pathlib import Path

    t = trades if trades is not None else pd.DataFrame()
    days = data.index.normalize().nunique()
    period = f"{data.index[0]:%d %b %Y} – {data.index[-1]:%d %b %Y}"
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")

    if t.empty:
        tiles = [("Trades", "0", ""), ("Win rate", "–", ""), ("Total P&L", "₹0", ""), ("Max drawdown", "₹0", "")]
        rows, reasons = "", ""
    else:
        wins = t[t.pnl_rs > 0]
        eq = t.pnl_rs.cumsum()
        dd = (eq - eq.cummax()).min()
        total = t.pnl_rs.sum()
        tiles = [
            ("Trades", f"{len(t)}", f"{(t.side == 'CE').sum()} calls · {(t.side == 'PE').sum()} puts"),
            ("Win rate", f"{len(wins) / len(t):.0%}", f"{len(wins)} winners"),
            ("Total P&L", _rs(total), f"after ~₹{config.COST_PER_TRADE_RS}/trade costs", "up" if total >= 0 else "down"),
            ("Max drawdown", _rs(dd), "worst peak-to-trough fall", "down" if dd < 0 else ""),
        ]
        reasons = " · ".join(f"{k}: {v}" for k, v in t.exit_reason.value_counts().items())
        recent = t.tail(60).iloc[::-1]
        rows = "".join(
            f"<tr><td>{pd.Timestamp(r.entry_time):%d %b %H:%M}</td>"
            f"<td><span class='side {r.side}'>{r.side}</span></td>"
            f"<td class='num'>{r.strike}</td><td class='num'>{r.rsi_at_signal}</td>"
            f"<td>{html.escape(str(r.exit_reason))}</td>"
            f"<td class='num'>{r.premium_points:+.1f}</td>"
            f"<td class='num {'up' if r.pnl_rs >= 0 else 'down'}'>{_rs(r.pnl_rs)}</td></tr>"
            for r in recent.itertuples()
        )

    tile_html = "".join(
        f"<div class='tile'><span>{k[0]}</span><strong class='{k[3] if len(k) > 3 else ''}'>{k[1]}</strong><small>{k[2]}</small></div>"
        for k in tiles
    )
    lv = config.REVERSAL_LEVELS if config.STRATEGY_MODE == "reversal" else config.MOMENTUM_LEVELS

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nifty RSI Backtest</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--ink:#111827;--ink2:#4b5563;--line:#e3e6eb;--up:#0f8a4a;--down:#c62828;--accent:#1d4ed8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1318;--card:#171c23;--ink:#eef1f5;--ink2:#a6afbc;--line:#2a313b;--up:#34c77b;--down:#ef5350;--accent:#6ea8ff;color-scheme:dark}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;padding:28px max(16px,3vw) 48px}}
h1{{font-size:clamp(22px,3vw,30px);margin:0}}.muted{{color:var(--ink2)}}
.head{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;align-items:end;margin-bottom:22px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}}.chip{{font-size:12.5px;border:1px solid var(--line);background:var(--card);border-radius:999px;padding:4px 10px;color:var(--ink2)}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px}}
.tile span{{font-size:13px;color:var(--ink2)}}.tile strong{{display:block;font-size:26px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.tile small{{color:var(--ink2);font-size:12.5px}}.up{{color:var(--up)}}.down{{color:var(--down)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:16px}}
.card h2{{font-size:16px;margin:0 0 10px}}.chart{{width:100%;height:auto;display:block}}
.chart .grid{{stroke:var(--line)}}.chart .tick{{fill:var(--ink2);font-size:11px}}
.tw{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:560px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);font-size:14px}}th{{font-size:12px;color:var(--ink2);font-weight:600}}
.num{{text-align:right}}.side{{font-size:12px;font-weight:700;padding:2px 7px;border-radius:5px}}
.side.CE{{background:color-mix(in srgb,var(--up) 15%,transparent);color:var(--up)}}.side.PE{{background:color-mix(in srgb,var(--down) 15%,transparent);color:var(--down)}}
.nav{{display:flex;gap:6px;margin-bottom:18px}}.nav a{{padding:7px 14px;border-radius:999px;text-decoration:none;color:var(--ink2);font-weight:600;font-size:14px;border:1px solid var(--line);background:var(--card)}}
.nav a.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
.note{{font-size:13px;color:var(--ink2);border-left:3px solid var(--accent);padding:6px 0 6px 12px}}
@media (max-width:720px){{.tiles{{grid-template-columns:1fr 1fr}}}}
</style></head><body><div class="wrap">
<nav class="nav"><a href="./" class="on">Backtest</a><a href="paper.html">Paper log</a></nav>
<div class="head"><div><h1>Nifty RSI-{config.RSI_PERIOD} option buying — backtest</h1>
<div class="chips"><span class="chip">{config.STRATEGY_MODE} mode · CE &gt; {lv['call']} / PE &lt; {lv['put']}</span>
<span class="chip">{config.TIMEFRAME} candles</span><span class="chip">{config.LOTS} lots × {config.LOT_SIZE}</span>
<span class="chip">SL {config.STOP_LOSS_POINTS} · target {config.TARGET_POINTS} pts</span></div></div>
<div class="muted" style="text-align:right;font-size:13px">{period} · {days} trading days<br>Updated {now}</div></div>
<div class="tiles">{tile_html}</div>
<div class="card"><h2>Cumulative P&amp;L</h2>{_equity_svg(t)}<p class="muted" style="margin:8px 0 0;font-size:13px">{reasons}</p></div>
<div class="card"><h2>Recent trades</h2><div class="tw"><table>
<thead><tr><th>Entry</th><th>Side</th><th class="num">Strike</th><th class="num">RSI</th><th>Exit</th><th class="num">Premium pts</th><th class="num">P&amp;L</th></tr></thead>
<tbody>{rows or '<tr><td colspan="7" class="muted">No trades triggered.</td></tr>'}</tbody></table></div></div>
<p class="note">Premiums are estimated from Nifty's move using delta and ignore time decay, so real results are usually worse.
This page is for research only and is not financial advice.</p>
</div></body></html>"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
