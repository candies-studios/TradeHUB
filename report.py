"""
Turns backtest results into one dashboard web page (index.html / report.html):
an overview of every instrument, then a section per instrument with its chart and trades.
Used by:  python backtest.py --html report.html  and the GitHub "Backtest dashboard" workflow.
"""
import html
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

import config

IST = timezone(timedelta(hours=5, minutes=30))


def _rs(v):
    return ("−" if v < 0 else "") + f"₹{abs(v):,.0f}"


def _cls(v):
    return "up" if v > 0 else "down" if v < 0 else ""


def _pts(v):
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}" if abs(v) >= 1 else f"{v:,.2f}"


def _equity_svg(t: pd.DataFrame) -> str:
    if t.empty:
        return '<p class="muted">No trades in this period, so there is no equity curve.</p>'
    eq = [0.0] + t.pnl_rs.cumsum().tolist()
    W, H, P, PL = 900, 220, 26, 84
    lo, hi = min(eq), max(eq)
    span = (hi - lo) or 1
    x = lambda i: PL + (W - PL - P) * i / max(1, len(eq) - 1)
    y = lambda v: P + (H - 2 * P) * (1 - (v - lo) / span)
    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(eq))
    area = f"{x(0):.1f},{y(0):.1f} " + pts + f" {x(len(eq) - 1):.1f},{y(0):.1f}"
    col = "var(--up)" if eq[-1] >= 0 else "var(--down)"
    ticks = "".join(
        f'<line x1="{PL}" x2="{W - P}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
        f'<text x="{PL - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="tick">{_rs(v)}</text>'
        for v in sorted({lo, 0.0, hi}))
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Cumulative profit and loss">{ticks}'
            f'<polygon points="{area}" fill="{col}" opacity=".12"/>'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2.5" stroke-linejoin="round"/>'
            f'<circle cx="{x(len(eq) - 1):.1f}" cy="{y(eq[-1]):.1f}" r="4.5" fill="{col}"/></svg>')


def _stats(t: pd.DataFrame):
    if t.empty:
        return dict(n=0, win=None, pnl=0.0, dd=0.0, avg=0.0)
    eq = t.pnl_rs.cumsum()
    return dict(n=len(t), win=(t.pnl_rs > 0).mean(), pnl=t.pnl_rs.sum(), dd=(eq - eq.cummax()).min(), avg=t.pnl_rs.mean())


def _tiles(s, extra=""):
    win = "–" if s["win"] is None else f"{s['win']:.0%}"
    items = [("Trades", str(s["n"]), extra), ("Win rate", win, ""),
             ("Net P&L", _rs(s["pnl"]), "after estimated costs", _cls(s["pnl"])),
             ("Max drawdown", _rs(s["dd"]), "worst peak-to-trough fall", "down" if s["dd"] < 0 else "")]
    return "<div class='tiles'>" + "".join(
        f"<div class='tile'><span>{k[0]}</span><strong class='{k[3] if len(k) > 3 else ''}'>{k[1]}</strong><small>{k[2]}</small></div>"
        for k in items) + "</div>"


def _section(key, r):
    inst, t, df = r["inst"], r["trades"], r["data"]
    head = f"<h2>{html.escape(inst['name'])} <span class='chip'>{inst['exchange']}</span></h2>"
    if df.empty:
        return f"<section class='card' id='{key}'>{head}<p class='muted'>No market data could be downloaded for this instrument on the last run.</p></section>"
    s = _stats(t)
    is_auto = "auto" in (str(inst.get("sl_points")), str(inst.get("target_points")))
    if t.empty:
        risk = "auto from volatility" if is_auto else f"SL {inst['sl_points']} · target {inst['target_points']}"
    else:
        risk = (f"SL ≈ {_pts(t.sl_points.median())} · target ≈ {_pts(t.target_points.median())} pts (auto)" if is_auto
                else f"SL {inst['sl_points']} · target {inst['target_points']} pts")
    period = f"{df.index[0]:%d %b} – {df.index[-1]:%d %b %Y}"
    meta = (f"<div class='chips'><span class='chip'>{inst['lots']} lot{'s' if inst['lots'] > 1 else ''} × {inst['units_per_lot']}</span>"
            f"<span class='chip'>{risk}</span><span class='chip'>{period}</span>"
            + (f"<span class='chip'>signals from {html.escape(inst['ticker'])}, {html.escape(inst.get('quote', ''))}</span>" if inst["segment"] == "commodity" else "")
            + "</div>")
    reasons = " · ".join(f"{k}: {v}" for k, v in t.exit_reason.value_counts().items()) if not t.empty else ""
    rows = ""
    if not t.empty:
        for r_ in t.tail(15).iloc[::-1].itertuples():
            strike = "" if pd.isna(r_.strike) or r_.strike is None else f"{int(r_.strike)}"
            rows += (f"<tr><td>{pd.Timestamp(r_.entry_time):%d %b %H:%M}</td><td><span class='side {r_.side}'>{r_.side}</span></td>"
                     f"<td class='num'>{strike or '–'}</td><td class='num'>{r_.rsi_at_signal}</td><td>{html.escape(str(r_.exit_reason))}</td>"
                     f"<td class='num'>{r_.premium_points:+,.2f}</td><td class='num {_cls(r_.pnl_rs)}'>{_rs(r_.pnl_rs)}</td></tr>")
    table = (f"<div class='tw'><table><thead><tr><th>Entry</th><th>Side</th><th class='num'>Strike</th><th class='num'>RSI</th>"
             f"<th>Exit</th><th class='num'>Premium pts</th><th class='num'>P&amp;L</th></tr></thead>"
             f"<tbody>{rows or '<tr><td colspan=7 class=muted>No trades triggered.</td></tr>'}</tbody></table></div>")
    return (f"<section class='card' id='{key}'>{head}{meta}{_tiles(s)}"
            f"<h3>Cumulative P&amp;L</h3>{_equity_svg(t)}<p class='muted small'>{reasons}</p>"
            f"<h3>Recent trades</h3>{table}</section>")


def write(results: dict, path: str):
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    lv = config.REVERSAL_LEVELS if config.STRATEGY_MODE == "reversal" else config.MOMENTUM_LEVELS
    all_t = pd.concat([r["trades"] for r in results.values() if not r["trades"].empty] or [pd.DataFrame(columns=["pnl_rs"])])
    total = _stats(all_t) if len(all_t) else _stats(pd.DataFrame())

    ov_rows = ""
    for key, r in results.items():
        s, inst = _stats(r["trades"]), r["inst"]
        nodata = r["data"].empty
        win = "–" if s["win"] is None else f"{s['win']:.0%}"
        ov_rows += (f"<tr><td><a href='#{key}'>{html.escape(inst['name'])}</a></td><td>{inst['exchange']}</td>"
                    + ("<td colspan=5 class='muted'>no data on last run</td></tr>" if nodata else
                       f"<td class='num'>{s['n']}</td><td class='num'>{win}</td>"
                       f"<td class='num {_cls(s['pnl'])}'>{_rs(s['pnl'])}</td><td class='num'>{_rs(s['avg']) if s['n'] else '–'}</td>"
                       f"<td class='num {'down' if s['dd'] < 0 else ''}'>{_rs(s['dd'])}</td></tr>"))
    sections = "".join(_section(k, r) for k, r in results.items())

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>RSI Backtest Dashboard</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--ink:#111827;--ink2:#4b5563;--line:#e3e6eb;--up:#0f8a4a;--down:#c62828;--accent:#1d4ed8}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1318;--card:#171c23;--ink:#eef1f5;--ink2:#a6afbc;--line:#2a313b;--up:#34c77b;--down:#ef5350;--accent:#6ea8ff;color-scheme:dark}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:1080px;margin:0 auto;padding:20px max(16px,3vw) 56px}}
.nav{{display:flex;gap:6px;margin-bottom:18px}}.nav a{{padding:7px 14px;border-radius:999px;text-decoration:none;color:var(--ink2);font-weight:600;font-size:14px;border:1px solid var(--line);background:var(--card)}}
.nav a.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
h1{{font-size:clamp(22px,3vw,30px);margin:0}}h2{{font-size:20px;margin:0 0 8px;display:flex;align-items:center;gap:8px}}h3{{font-size:15px;margin:18px 0 6px}}
.muted{{color:var(--ink2)}}.small{{font-size:13px;margin:6px 0 0}}
.head{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;align-items:end;margin-bottom:18px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 12px}}.chip{{font-size:12.5px;border:1px solid var(--line);background:var(--bg);border-radius:999px;padding:3px 10px;color:var(--ink2);font-weight:500}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}}
.tile span{{font-size:13px;color:var(--ink2)}}.tile strong{{display:block;font-size:24px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.tile small{{color:var(--ink2);font-size:12.5px}}.up{{color:var(--up)}}.down{{color:var(--down)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:16px;scroll-margin-top:12px}}
.card .tile{{background:var(--bg)}}
.chart{{width:100%;height:auto;display:block}}.chart .grid{{stroke:var(--line)}}.chart .tick{{fill:var(--ink2);font-size:11px}}
.tw{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:560px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);font-size:14px}}th{{font-size:12px;color:var(--ink2);font-weight:600}}
td a{{color:var(--accent);font-weight:600;text-decoration:none}}.num{{text-align:right}}
.side{{font-size:12px;font-weight:700;padding:2px 7px;border-radius:5px}}
.side.CE{{background:color-mix(in srgb,var(--up) 15%,transparent);color:var(--up)}}.side.PE{{background:color-mix(in srgb,var(--down) 15%,transparent);color:var(--down)}}
.note{{font-size:13px;color:var(--ink2);border-left:3px solid var(--accent);padding:6px 0 6px 12px}}
@media (max-width:720px){{.tiles{{grid-template-columns:1fr 1fr}}}}
</style></head><body><div class="wrap">
<nav class="nav"><a href="./" class="on">Backtest</a><a href="paper.html">Paper log</a></nav>
<div class="head"><div><h1>RSI-{config.RSI_PERIOD} option buying — backtest</h1>
<div class="chips"><span class="chip">{config.STRATEGY_MODE} mode · CE when RSI &gt; {lv['call']} · PE when RSI &lt; {lv['put']}</span><span class="chip">5-minute candles</span></div></div>
<div class="muted" style="text-align:right;font-size:13px">Updated {now}</div></div>
<section class="card"><h2>All instruments</h2>{_tiles(total)}
<div class="tw" style="margin-top:14px"><table><thead><tr><th>Instrument</th><th>Exchange</th><th class="num">Trades</th><th class="num">Win rate</th>
<th class="num">Net P&amp;L</th><th class="num">Avg / trade</th><th class="num">Max drawdown</th></tr></thead><tbody>{ov_rows}</tbody></table></div></section>
{sections}
<p class="note">Premiums are estimated from the underlying's move using delta and ignore time decay, so real results are usually worse.
Commodity signals use international prices (COMEX/NYMEX) converted to rupees; MCX prices track them closely but not exactly.
For research only, not financial advice.</p>
</div></body></html>"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
