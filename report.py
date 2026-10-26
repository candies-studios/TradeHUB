"""
Turns backtest results into one dashboard web page (index.html / report.html):
a strategy comparison across all instruments, then a section per instrument.
Used by:  python backtest.py --html report.html  and the GitHub "Backtest dashboard" workflow.
"""
import html
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

import config

IST = timezone(timedelta(hours=5, minutes=30))
SERIES_VAR = {"RSI": "var(--s1)", "EMA": "var(--s2)"}


def _rs(v):
    return ("−" if v < 0 else "") + f"₹{abs(v):,.0f}"


def _cls(v):
    return "up" if v > 0 else "down" if v < 0 else ""


def _pts(v):
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.1f}" if abs(v) >= 1 else f"{v:,.2f}"


def _sname(s):
    return config.STRATEGY_NAMES.get(s, s)


def _stats(t: pd.DataFrame):
    if t is None or t.empty:
        return dict(n=0, win=None, pnl=0.0, dd=0.0, avg=0.0)
    eq = t.pnl_rs.cumsum()
    return dict(n=len(t), win=(t.pnl_rs > 0).mean(), pnl=t.pnl_rs.sum(), dd=(eq - eq.cummax()).min(), avg=t.pnl_rs.mean())


def _win(s):
    return "–" if s["win"] is None else f"{s['win']:.0%}"


def _by(t: pd.DataFrame, strat: str) -> pd.DataFrame:
    if t is None or t.empty or "strategy" not in t:
        return pd.DataFrame()
    return t[t.strategy == strat].sort_values("exit_time")


def _equity_svg(t: pd.DataFrame, strategies, start, end) -> str:
    """One line per strategy, plotted against time so the two are comparable."""
    if t is None or t.empty:
        return '<p class="muted">No trades in this period, so there is no equity curve.</p>'
    W, H, P, PL = 900, 230, 26, 84
    t0, t1 = pd.Timestamp(start).value, max(pd.Timestamp(end).value, pd.Timestamp(start).value + 1)
    series = {}
    for s in strategies:
        g = _by(t, s)
        if g.empty:
            continue
        times = [pd.Timestamp(start).value] + [pd.Timestamp(x).value for x in g.exit_time]
        series[s] = list(zip(times, [0.0] + g.pnl_rs.cumsum().tolist()))
    vals = [v for pts in series.values() for _, v in pts] + [0.0]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    x = lambda ts: PL + (W - PL - P) * (ts - t0) / (t1 - t0)
    y = lambda v: P + (H - 2 * P) * (1 - (v - lo) / span)
    out = "".join(f'<line x1="{PL}" x2="{W - P}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
                  f'<text x="{PL - 8}" y="{y(v) + 4:.1f}" text-anchor="end" class="tick">{_rs(v)}</text>'
                  for v in sorted({lo, 0.0, hi}))
    for s, pts in series.items():
        line = " ".join(f"{x(a):.1f},{y(v):.1f}" for a, v in pts)
        out += (f'<polyline points="{line}" fill="none" stroke="{SERIES_VAR.get(s, "var(--ink2)")}" stroke-width="2.4" stroke-linejoin="round"/>'
                f'<circle cx="{x(pts[-1][0]):.1f}" cy="{y(pts[-1][1]):.1f}" r="4" fill="{SERIES_VAR.get(s, "var(--ink2)")}"/>')
    legend = "".join(f"<span><i style='background:{SERIES_VAR.get(s)}'></i>{_sname(s)}</span>" for s in series)
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Cumulative profit and loss by strategy">{out}</svg><div class="legend">{legend}</div>'


def _compare_table(t: pd.DataFrame, strategies) -> str:
    rows = ""
    for s in strategies:
        st = _stats(_by(t, s))
        rows += (f"<tr><td><span class='dot' style='background:{SERIES_VAR.get(s)}'></span>{_sname(s)}</td>"
                 f"<td class='num'>{st['n']}</td><td class='num'>{_win(st)}</td>"
                 f"<td class='num {_cls(st['pnl'])}'>{_rs(st['pnl'])}</td><td class='num'>{_rs(st['avg']) if st['n'] else '–'}</td>"
                 f"<td class='num {'down' if st['dd'] < 0 else ''}'>{_rs(st['dd'])}</td></tr>")
    return ("<div class='tw'><table><thead><tr><th>Strategy</th><th class='num'>Trades</th><th class='num'>Win rate</th>"
            "<th class='num'>Net P&amp;L</th><th class='num'>Avg / trade</th><th class='num'>Max drawdown</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>")


def _section(key, r):
    inst, t, df, strategies = r["inst"], r["trades"], r["data"], r.get("strategies", ["RSI"])
    head = f"<h2>{html.escape(inst['name'])} <span class='chip'>{inst['exchange']}</span></h2>"
    if df.empty:
        return f"<section class='card' id='{key}'>{head}<p class='muted'>No market data could be downloaded for this instrument on the last run.</p></section>"
    is_auto = "auto" in (str(inst.get("sl_points")), str(inst.get("target_points")))
    if is_auto and not t.empty:
        risk = f"SL ≈ {_pts(t.sl_points.median())} · target ≈ {_pts(t.target_points.median())} pts (auto)"
    elif is_auto:
        risk = "SL / target auto from volatility"
    else:
        risk = f"SL {inst['sl_points']} · target {inst['target_points']} pts"
    chips = (f"<div class='chips'><span class='chip'>{inst['lots']} lot{'s' if inst['lots'] > 1 else ''} × {inst['units_per_lot']}</span>"
             f"<span class='chip'>{risk}</span><span class='chip'>{df.index[0]:%d %b} – {df.index[-1]:%d %b %Y}</span>"
             + (f"<span class='chip'>signals from {html.escape(inst['ticker'])}, {html.escape(inst.get('quote', ''))}</span>" if inst["segment"] == "commodity" else "")
             + "</div>")
    rows = ""
    if not t.empty:
        for x in t.sort_values("entry_time").tail(15).iloc[::-1].itertuples():
            strike = "" if x.strike is None or pd.isna(x.strike) else f"{int(x.strike)}"
            rows += (f"<tr><td>{pd.Timestamp(x.entry_time):%d %b %H:%M}</td>"
                     f"<td><span class='dot' style='background:{SERIES_VAR.get(x.strategy)}'></span>{_sname(x.strategy)}</td>"
                     f"<td><span class='side {x.side}'>{x.side}</span></td><td class='num'>{strike or '–'}</td>"
                     f"<td>{html.escape(str(x.exit_reason))}</td><td class='num'>{x.premium_points:+,.2f}</td>"
                     f"<td class='num {_cls(x.pnl_rs)}'>{_rs(x.pnl_rs)}</td></tr>")
    trades = ("<div class='tw'><table><thead><tr><th>Entry</th><th>Strategy</th><th>Side</th><th class='num'>Strike</th>"
              "<th>Exit</th><th class='num'>Premium pts</th><th class='num'>P&amp;L</th></tr></thead>"
              f"<tbody>{rows or '<tr><td colspan=7 class=muted>No trades triggered.</td></tr>'}</tbody></table></div>")
    return (f"<section class='card' id='{key}'>{head}{chips}{_compare_table(t, strategies)}"
            f"<h3>Cumulative P&amp;L</h3>{_equity_svg(t, strategies, df.index[0], df.index[-1])}"
            f"<h3>Recent trades</h3>{trades}</section>")


def write(results: dict, path: str):
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    lv = config.REVERSAL_LEVELS if config.STRATEGY_MODE == "reversal" else config.MOMENTUM_LEVELS
    strategies = next(iter(results.values())).get("strategies", ["RSI"]) if results else ["RSI"]
    frames = [r["trades"] for r in results.values() if not r["trades"].empty]
    all_t = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    # strategy totals across every instrument
    totals = ""
    for s in strategies:
        st = _stats(_by(all_t, s))
        totals += (f"<div class='strat'><h3><span class='dot' style='background:{SERIES_VAR.get(s)}'></span>{_sname(s)}</h3>"
                   f"<div class='tiles'><div class='tile'><span>Trades</span><strong>{st['n']}</strong></div>"
                   f"<div class='tile'><span>Win rate</span><strong>{_win(st)}</strong></div>"
                   f"<div class='tile'><span>Net P&amp;L</span><strong class='{_cls(st['pnl'])}'>{_rs(st['pnl'])}</strong></div>"
                   f"<div class='tile'><span>Max drawdown</span><strong class='{'down' if st['dd'] < 0 else ''}'>{_rs(st['dd'])}</strong></div></div></div>")

    # overview: one row per instrument, net P&L and win rate for each strategy
    head_cells = "".join(f"<th class='num'>{_sname(s)} trades</th><th class='num'>win</th><th class='num'>net P&amp;L</th>" for s in strategies)
    ov = ""
    for key, r in results.items():
        cells = ""
        if r["data"].empty:
            cells = f"<td colspan='{3 * len(strategies)}' class='muted'>no data on last run</td>"
        else:
            for s in strategies:
                st = _stats(_by(r["trades"], s))
                cells += f"<td class='num'>{st['n']}</td><td class='num'>{_win(st)}</td><td class='num {_cls(st['pnl'])}'>{_rs(st['pnl'])}</td>"
        ov += f"<tr><td><a href='#{key}'>{html.escape(r['inst']['name'])}</a></td><td>{r['inst']['exchange']}</td>{cells}</tr>"

    rule_chips = ""
    if "RSI" in strategies:
        rule_chips += f"<span class='chip'>RSI-{config.RSI_PERIOD} ({config.STRATEGY_MODE}): CE when RSI &gt; {lv['call']} · PE when RSI &lt; {lv['put']}</span>"
    if "EMA" in strategies:
        rule_chips += f"<span class='chip'>EMA {config.EMA_FAST}/{config.EMA_SLOW}: CE when {config.EMA_FAST} crosses above {config.EMA_SLOW} · PE when it crosses below</span>"
    sections = "".join(_section(k, r) for k, r in results.items())

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Backtest Dashboard</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--ink:#111827;--ink2:#4b5563;--line:#e3e6eb;--up:#0f8a4a;--down:#c62828;--accent:#1d4ed8;--s1:#1d4ed8;--s2:#c2410c}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1318;--card:#171c23;--ink:#eef1f5;--ink2:#a6afbc;--line:#2a313b;--up:#34c77b;--down:#ef5350;--accent:#6ea8ff;--s1:#6ea8ff;--s2:#fb923c;color-scheme:dark}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:1120px;margin:0 auto;padding:20px max(16px,3vw) 56px}}
.nav{{display:flex;gap:6px;margin-bottom:18px}}.nav a{{padding:7px 14px;border-radius:999px;text-decoration:none;color:var(--ink2);font-weight:600;font-size:14px;border:1px solid var(--line);background:var(--card)}}
.nav a.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
h1{{font-size:clamp(22px,3vw,30px);margin:0}}h2{{font-size:20px;margin:0 0 8px;display:flex;align-items:center;gap:8px}}h3{{font-size:15px;margin:18px 0 8px;display:flex;align-items:center}}
.muted{{color:var(--ink2)}}
.head{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;align-items:end;margin-bottom:18px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 12px}}.chip{{font-size:12.5px;border:1px solid var(--line);background:var(--bg);border-radius:999px;padding:3px 10px;color:var(--ink2);font-weight:500}}
.head .chip{{background:var(--card)}}
.strats{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.strat h3{{margin-top:4px}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.tile{{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.strat .tiles{{grid-template-columns:1fr 1fr}}
.tile span{{font-size:12.5px;color:var(--ink2)}}.tile strong{{display:block;white-space:nowrap;font-size:21px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.up{{color:var(--up)}}.down{{color:var(--down)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:16px;scroll-margin-top:12px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;flex:none}}
.chart{{width:100%;height:auto;display:block}}.chart .grid{{stroke:var(--line)}}.chart .tick{{fill:var(--ink2);font-size:11px}}
.legend{{display:flex;gap:16px;font-size:13px;color:var(--ink2);margin-top:4px}}.legend span{{display:flex;align-items:center;gap:6px}}.legend i{{width:16px;height:3px;border-radius:2px;display:inline-block}}
.tw{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:560px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);font-size:14px;white-space:nowrap}}th{{font-size:12px;color:var(--ink2);font-weight:600}}
td a{{color:var(--accent);font-weight:600;text-decoration:none}}.num{{text-align:right}}
.side{{font-size:12px;font-weight:700;padding:2px 7px;border-radius:5px}}
.side.CE{{background:color-mix(in srgb,var(--up) 15%,transparent);color:var(--up)}}.side.PE{{background:color-mix(in srgb,var(--down) 15%,transparent);color:var(--down)}}
.note{{font-size:13px;color:var(--ink2);border-left:3px solid var(--accent);padding:6px 0 6px 12px}}
@media (max-width:860px){{.strats{{grid-template-columns:1fr}}}}
@media (max-width:520px){{.tiles{{grid-template-columns:1fr 1fr}}}}
</style></head><body><div class="wrap">
<nav class="nav"><a href="./" class="on">Backtest</a><a href="paper.html">Paper log</a></nav>
<div class="head"><div><h1>Option buying strategies — backtest</h1><div class="chips">{rule_chips}<span class='chip'>5-minute candles</span></div></div>
<div class="muted" style="text-align:right;font-size:13px">Updated {now}</div></div>
<section class="card"><h2>Strategy comparison, all instruments</h2><div class="strats">{totals}</div>
<div class="tw" style="margin-top:16px"><table><thead><tr><th>Instrument</th><th>Exchange</th>{head_cells}</tr></thead><tbody>{ov}</tbody></table></div></section>
{sections}
<p class="note">Each strategy is tested on its own: its own trades, daily limit of {config.MAX_TRADES_PER_DAY} per instrument, and the same stop-loss/target rules.
Premiums are estimated from the underlying's move using delta and ignore time decay, so real results are usually worse.
Commodity signals use international prices (COMEX/NYMEX) converted to rupees. For research only, not financial advice.</p>
</div></body></html>"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
