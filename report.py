"""
Turns backtest results into one dashboard web page (index.html / report.html):
a strategy comparison (dropdown: compare all, or one strategy at a time) across all instruments,
then a section per instrument that follows the same dropdown.
Used by:  python backtest.py --html report.html  and the GitHub "Backtest dashboard" workflow.
"""
import html
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

import config

IST = timezone(timedelta(hours=5, minutes=30))
SERIES_VAR = {"RSI": "var(--s1)", "EMA": "var(--s2)", "ORB": "var(--s3)", "VWAP": "var(--s4)", "PDH": "var(--s5)"}


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
        out += (f'<g data-s="{s}"><polyline points="{line}" fill="none" stroke="{SERIES_VAR.get(s, "var(--ink2)")}" stroke-width="2.4" stroke-linejoin="round"/>'
                f'<circle cx="{x(pts[-1][0]):.1f}" cy="{y(pts[-1][1]):.1f}" r="4" fill="{SERIES_VAR.get(s, "var(--ink2)")}"/></g>')
    legend = "".join(f"<span data-s='{s}'><i style='background:{SERIES_VAR.get(s)}'></i>{_sname(s)}</span>" for s in series)
    return f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" aria-label="Cumulative profit and loss by strategy">{out}</svg><div class="legend">{legend}</div>'


def _compare_table(t: pd.DataFrame, strategies) -> str:
    rows = ""
    for s in strategies:
        st = _stats(_by(t, s))
        rows += (f"<tr data-s='{s}'><td><span class='dot' style='background:{SERIES_VAR.get(s)}'></span>{_sname(s)}</td>"
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
    sig = t[t.strategy.isin(["RSI", "EMA"])] if not t.empty else t
    if is_auto and not sig.empty:
        risk = f"RSI / EMA: SL ≈ {_pts(sig.sl_points.median())} · target ≈ {_pts(sig.target_points.median())} pts (auto)"
    elif is_auto:
        risk = "RSI / EMA: SL / target auto from volatility"
    else:
        risk = f"RSI / EMA: SL {inst['sl_points']} · target {inst['target_points']} pts"
    if any(s in config.SETUP_STRATEGIES for s in strategies):
        risk += f" · ORB / VWAP / PDH: stop beyond the swing, target {config.REWARD_R:g}R"
    chips = (f"<div class='chips'><span class='chip'>{inst['lots']} lot{'s' if inst['lots'] > 1 else ''} × {inst['units_per_lot']}</span>"
             f"<span class='chip'>{risk}</span><span class='chip'>{df.index[0]:%d %b} – {df.index[-1]:%d %b %Y}</span>"
             + (f"<span class='chip'>signals from {html.escape(inst['ticker'])}, {html.escape(inst.get('quote', ''))}</span>" if inst["segment"] == "commodity" else "")
             + "</div>")
    rows = ""
    if not t.empty:
        ts = t.sort_values("entry_time")
        latest_all = set(ts.tail(15).index)
        keep = set(latest_all)
        for s in strategies:
            keep |= set(ts[ts.strategy == s].tail(10).index)
        for i, x in ts.loc[sorted(keep, key=lambda k: ts.at[k, "entry_time"], reverse=True)].iterrows():
            strike = "" if x.strike is None or pd.isna(x.strike) else f"{int(x.strike)}"
            rows += (f"<tr data-s='{x.strategy}' data-all='{1 if i in latest_all else 0}'><td>{pd.Timestamp(x.entry_time):%d %b %H:%M}</td>"
                     f"<td><span class='dot' style='background:{SERIES_VAR.get(x.strategy)}'></span>{_sname(x.strategy)}</td>"
                     f"<td><span class='side {x.side}'>{x.side}</span></td><td class='num'>{strike or '–'}</td>"
                     f"<td>{html.escape(str(x.exit_reason))}</td><td class='num'>{x.premium_points:+,.2f}</td>"
                     f"<td class='num {_cls(x.pnl_rs)}'>{_rs(x.pnl_rs)}</td></tr>")
    empty = "<tr class='none'><td colspan=7 class=muted>No trades triggered.</td></tr>"
    trades = ("<div class='tw'><table class='recent'><thead><tr><th>Entry</th><th>Strategy</th><th>Side</th><th class='num'>Strike</th>"
              "<th>Exit</th><th class='num'>Premium pts</th><th class='num'>P&amp;L</th></tr></thead>"
              f"<tbody>{rows}{empty}</tbody></table></div>")
    return (f"<section class='card inst' id='{key}'>{head}{chips}{_compare_table(t, strategies)}"
            f"<h3>Cumulative P&amp;L</h3>{_equity_svg(t, strategies, df.index[0], df.index[-1])}"
            f"<h3>Recent trades</h3>{trades}</section>")


RULES = {
    "RSI": lambda lv: f"RSI-{config.RSI_PERIOD} ({config.STRATEGY_MODE}): buy CE when RSI crosses above {lv['call']}, PE when it crosses below {lv['put']}. "
                      f"Stop-loss and target from volatility (ATR).",
    "EMA": lambda lv: f"Buy CE when the {config.EMA_FAST} EMA crosses above the {config.EMA_SLOW} EMA, PE when it crosses below. "
                      f"Stop-loss and target from volatility (ATR).",
    "ORB": lambda lv: f"Opening range = first {config.ORB_MINUTES} min. A 5-min candle closes beyond it (with VWAP, 20 EMA and the 15-min 20 EMA agreeing), "
                      f"price retests the level without closing back inside, and a confirmation candle closes beyond the retest candle. "
                      f"Stop beyond the retest swing, target {config.REWARD_R:g}R. One attempt per direction per session.",
    "VWAP": lambda lv: f"Trend: 15-min close beyond its 20 EMA, ADX(14) above {config.VWAP_ADX_MIN} and rising. Pullback to VWAP / 20 EMA that holds the last swing, "
                       f"then a confirmation candle; enter beyond its high / low. Stop beyond the pullback swing + ATR buffer, target {config.REWARD_R:g}R. "
                       f"Skipped if the previous session's high/low blocks the path. Max {config.VWAP_MAX_ENTRIES} per session.",
    "PDH": lambda lv: f"A 5-min candle closes beyond the previous session's high (low), the retest holds above (below) it with price beyond VWAP and the 20 EMA, "
                      f"and a confirmation candle forms; enter beyond its high / low. Stop beyond the retest swing, target {config.REWARD_R:g}R. "
                      f"Skipped if the next major level is too close. One attempt per level per direction.",
}


def _tiles(st):
    return (f"<div class='tiles'><div class='tile'><span>Trades</span><strong>{st['n']}</strong></div>"
            f"<div class='tile'><span>Win rate</span><strong>{_win(st)}</strong></div>"
            f"<div class='tile'><span>Net P&amp;L</span><strong class='{_cls(st['pnl'])}'>{_rs(st['pnl'])}</strong></div>"
            f"<div class='tile'><span>Max drawdown</span><strong class='{'down' if st['dd'] < 0 else ''}'>{_rs(st['dd'])}</strong></div></div>")


def write(results: dict, path: str):
    now = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")
    lv = config.REVERSAL_LEVELS if config.STRATEGY_MODE == "reversal" else config.MOMENTUM_LEVELS
    strategies = next(iter(results.values())).get("strategies", ["RSI"]) if results else ["RSI"]
    frames = [r["trades"] for r in results.values() if not r["trades"].empty]
    all_t = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    have = [r["data"] for r in results.values() if not r["data"].empty]
    start = min(d.index[0] for d in have) if have else pd.Timestamp.now()
    end = max(d.index[-1] for d in have) if have else pd.Timestamp.now()

    # ---- "Compare all" view: strategy league table + instrument x strategy matrix + combined equity
    best = max(strategies, key=lambda s: _stats(_by(all_t, s))["pnl"]) if strategies else None
    league = ""
    for s in strategies:
        st = _stats(_by(all_t, s))
        league += (f"<tr><td><button class='pick' data-go='{s}'><span class='dot' style='background:{SERIES_VAR.get(s)}'></span>{_sname(s)}</button>"
                   + (" <span class='badge'>best net P&amp;L</span>" if s == best and st["pnl"] > 0 else "") + "</td>"
                   f"<td class='num'>{st['n']}</td><td class='num'>{_win(st)}</td>"
                   f"<td class='num {_cls(st['pnl'])}'>{_rs(st['pnl'])}</td><td class='num'>{_rs(st['avg']) if st['n'] else '–'}</td>"
                   f"<td class='num {'down' if st['dd'] < 0 else ''}'>{_rs(st['dd'])}</td></tr>")
    matrix_head = "".join(f"<th class='num'><span class='dot' style='background:{SERIES_VAR.get(s)}'></span>{_sname(s)}</th>" for s in strategies)
    matrix = ""
    for key, r in results.items():
        if r["data"].empty:
            cells = f"<td colspan='{len(strategies)}' class='muted'>no data on last run</td>"
        else:
            cells = ""
            for s in strategies:
                st = _stats(_by(r["trades"], s))
                cells += (f"<td class='num'><span class='{_cls(st['pnl'])}'>{_rs(st['pnl'])}</span>"
                          f"<small>{st['n']} · {_win(st)}</small></td>")
        matrix += f"<tr><td><a href='#{key}'>{html.escape(r['inst']['name'])}</a></td>{cells}</tr>"
    view_all = (f"<div class='view' data-v='all'>"
                f"<div class='tw'><table><thead><tr><th>Strategy</th><th class='num'>Trades</th><th class='num'>Win rate</th>"
                f"<th class='num'>Net P&amp;L</th><th class='num'>Avg / trade</th><th class='num'>Max drawdown</th></tr></thead>"
                f"<tbody>{league}</tbody></table></div>"
                f"<h3>Cumulative P&amp;L, all instruments</h3>{_equity_svg(all_t, strategies, start, end)}"
                f"<h3>Net P&amp;L by instrument <span class='muted' style='font-weight:400;margin-left:6px'>(trades · win rate below)</span></h3>"
                f"<div class='tw'><table class='matrix'><thead><tr><th>Instrument</th>{matrix_head}</tr></thead><tbody>{matrix}</tbody></table></div></div>")

    # ---- one view per strategy
    views = ""
    for s in strategies:
        g = _by(all_t, s)
        rows = ""
        for key, r in results.items():
            if r["data"].empty:
                rows += f"<tr><td>{html.escape(r['inst']['name'])}</td><td colspan='5' class='muted'>no data on last run</td></tr>"
                continue
            st = _stats(_by(r["trades"], s))
            rows += (f"<tr><td><a href='#{key}'>{html.escape(r['inst']['name'])}</a></td><td class='num'>{st['n']}</td><td class='num'>{_win(st)}</td>"
                     f"<td class='num {_cls(st['pnl'])}'>{_rs(st['pnl'])}</td><td class='num'>{_rs(st['avg']) if st['n'] else '–'}</td>"
                     f"<td class='num {'down' if st['dd'] < 0 else ''}'>{_rs(st['dd'])}</td></tr>")
        exits = ""
        if not g.empty:
            ec = g.exit_reason.value_counts()
            exits = " · ".join(f"{k}: {v}" for k, v in ec.items())
        views += (f"<div class='view' data-v='{s}' hidden>"
                  f"<p class='rule'><span class='dot' style='background:{SERIES_VAR.get(s)}'></span>{html.escape(RULES.get(s, lambda _: '')(lv))}</p>"
                  f"{_tiles(_stats(g))}"
                  + (f"<p class='muted' style='font-size:13px;margin:8px 0 0'>Exits — {html.escape(exits)}</p>" if exits else "")
                  + f"<h3>Cumulative P&amp;L, all instruments</h3>{_equity_svg(g, [s], start, end)}"
                  f"<h3>By instrument</h3><div class='tw'><table><thead><tr><th>Instrument</th><th class='num'>Trades</th><th class='num'>Win rate</th>"
                  f"<th class='num'>Net P&amp;L</th><th class='num'>Avg / trade</th><th class='num'>Max drawdown</th></tr></thead>"
                  f"<tbody>{rows}</tbody></table></div></div>")

    options = "<option value='all'>Compare all strategies</option>" + "".join(
        f"<option value='{s}'>{_sname(s)}</option>" for s in strategies)
    sections = "".join(_section(k, r) for k, r in results.items())

    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Strategy Backtest Dashboard</title>
<style>
:root{{--bg:#f5f6f8;--card:#fff;--ink:#111827;--ink2:#4b5563;--line:#e3e6eb;--up:#0f8a4a;--down:#c62828;--accent:#1d4ed8;
--s1:#1d4ed8;--s2:#c2410c;--s3:#0e7490;--s4:#7c3aed;--s5:#be185d}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1318;--card:#171c23;--ink:#eef1f5;--ink2:#a6afbc;--line:#2a313b;--up:#34c77b;--down:#ef5350;--accent:#6ea8ff;
--s1:#6ea8ff;--s2:#fb923c;--s3:#22d3ee;--s4:#b197fc;--s5:#f472b6;color-scheme:dark}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:1120px;margin:0 auto;padding:20px max(16px,3vw) 56px}}
.nav{{display:flex;gap:6px;margin-bottom:18px}}.nav a{{padding:7px 14px;border-radius:999px;text-decoration:none;color:var(--ink2);font-weight:600;font-size:14px;border:1px solid var(--line);background:var(--card)}}
.nav a.on{{background:var(--ink);color:var(--bg);border-color:var(--ink)}}
h1{{font-size:clamp(22px,3vw,30px);margin:0}}h2{{font-size:20px;margin:0 0 8px;display:flex;align-items:center;gap:8px}}h3{{font-size:15px;margin:18px 0 8px;display:flex;align-items:center}}
.muted{{color:var(--ink2)}}
.head{{display:flex;flex-wrap:wrap;justify-content:space-between;gap:12px;align-items:end;margin-bottom:18px}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 12px}}.chip{{font-size:12.5px;border:1px solid var(--line);background:var(--bg);border-radius:999px;padding:3px 10px;color:var(--ink2);font-weight:500}}
.head .chip{{background:var(--card)}}
.cmp-head{{display:flex;flex-wrap:wrap;gap:10px;justify-content:space-between;align-items:center;margin-bottom:12px}}.cmp-head h2{{margin:0}}
.sel{{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--ink2);font-weight:600}}
select{{font:inherit;font-size:14px;font-weight:600;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 34px 8px 12px;
appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--ink2) 50%),linear-gradient(135deg,var(--ink2) 50%,transparent 50%);
background-position:calc(100% - 17px) 55%,calc(100% - 12px) 55%;background-size:5px 5px;background-repeat:no-repeat;cursor:pointer;min-width:220px}}
select:focus-visible,.pick:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
.tiles{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}
.tile{{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.tile span{{font-size:12.5px;color:var(--ink2)}}.tile strong{{display:block;white-space:nowrap;font-size:21px;letter-spacing:-.02em;font-variant-numeric:tabular-nums}}
.up{{color:var(--up)}}.down{{color:var(--down)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:16px;scroll-margin-top:12px}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;flex:none}}
.rule{{display:flex;align-items:baseline;font-size:14px;color:var(--ink2);margin:0 0 12px;max-width:80ch}}.rule .dot{{transform:translateY(1px)}}
.pick{{all:unset;cursor:pointer;display:inline-flex;align-items:center;font-weight:600;color:var(--ink)}}.pick:hover{{color:var(--accent)}}
.badge{{font-size:11px;font-weight:700;color:var(--up);border:1px solid currentColor;border-radius:999px;padding:1px 7px;margin-left:6px}}
.matrix small{{display:block;font-size:11.5px;color:var(--ink2)}}.matrix td.num{{vertical-align:top}}
.chart{{width:100%;height:auto;display:block}}.chart .grid{{stroke:var(--line)}}.chart .tick{{fill:var(--ink2);font-size:11px}}
.legend{{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:13px;color:var(--ink2);margin-top:4px}}.legend span{{display:flex;align-items:center;gap:6px}}.legend i{{width:16px;height:3px;border-radius:2px;display:inline-block}}
.tw{{overflow-x:auto}}table{{width:100%;border-collapse:collapse;min-width:560px;font-variant-numeric:tabular-nums}}
th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);font-size:14px;white-space:nowrap}}th{{font-size:12px;color:var(--ink2);font-weight:600}}
th .dot{{width:8px;height:8px;margin-right:5px}}
td a{{color:var(--accent);font-weight:600;text-decoration:none}}.num{{text-align:right}}
.side{{font-size:12px;font-weight:700;padding:2px 7px;border-radius:5px}}
.side.CE{{background:color-mix(in srgb,var(--up) 15%,transparent);color:var(--up)}}.side.PE{{background:color-mix(in srgb,var(--down) 15%,transparent);color:var(--down)}}
.note{{font-size:13px;color:var(--ink2);border-left:3px solid var(--accent);padding:6px 0 6px 12px}}
[hidden]{{display:none!important}}
@media (max-width:520px){{.tiles{{grid-template-columns:1fr 1fr}}.sel,select{{width:100%}}.cmp-head{{align-items:stretch}}}}
</style></head><body><div class="wrap">
<nav class="nav"><a href="./" class="on">Backtest</a><a href="paper.html">Paper log</a></nav>
<div class="head"><div><h1>Option buying strategies — backtest</h1><div class="chips"><span class='chip'>{len(strategies)} strategies</span><span class='chip'>5-minute candles</span><span class='chip'>{start:%d %b} – {end:%d %b %Y}</span></div></div>
<div class="muted" style="text-align:right;font-size:13px">Updated {now}</div></div>
<section class="card" id="compare"><div class="cmp-head"><h2>Strategy comparison</h2>
<label class="sel" for="strat-pick">Show <select id="strat-pick">{options}</select></label></div>
{view_all}{views}</section>
{sections}
<p class="note">Each strategy is tested on its own: its own trades and {"no daily limit on signals" if config.MAX_TRADES_PER_DAY is None else f"a daily limit of {config.MAX_TRADES_PER_DAY} per instrument"}.
RSI-14 and EMA 9/20 use volatility-based stop-loss/target; ORB-5M, VWAP-5M and PDH-PDL-5M use a stop beyond the retest/pullback swing and a {config.REWARD_R:g}R target on the index/commodity price, and skip trades where costs would eat the reward.
Premiums are estimated from the underlying's move using delta and ignore time decay, so real results are usually worse.
Indian indices have no volume in the free data feed, so their VWAP is a session average price. Commodity signals use international prices (COMEX/NYMEX) converted to rupees. For research only, not financial advice.</p>
</div>
<script>
(function(){{
  var sel=document.getElementById('strat-pick');
  function apply(v){{
    document.querySelectorAll('#compare .view').forEach(function(el){{el.hidden=el.dataset.v!==v;}});
    document.querySelectorAll('section.inst').forEach(function(sec){{
      sec.querySelectorAll('[data-s]').forEach(function(el){{
        var show=v==='all'||el.dataset.s===v;
        if(show&&el.tagName==='TR'&&el.closest('table.recent')&&v==='all') show=el.dataset.all==='1';
        el.style.display=show?'':'none';
      }});
      var tb=sec.querySelector('table.recent tbody');
      if(tb){{var any=[].some.call(tb.querySelectorAll('tr[data-s]'),function(r){{return r.style.display!=='none';}});
        tb.querySelector('tr.none').style.display=any?'none':'';}}
    }});
    try{{localStorage.setItem('tradehub-strat',v);}}catch(e){{}}
  }}
  sel.addEventListener('change',function(){{apply(sel.value);}});
  document.querySelectorAll('.pick').forEach(function(b){{b.addEventListener('click',function(){{sel.value=b.dataset.go;apply(sel.value);}});}});
  var saved=null;try{{saved=localStorage.getItem('tradehub-strat');}}catch(e){{}}
  if(saved&&sel.querySelector('option[value="'+saved+'"]'))sel.value=saved;
  apply(sel.value);
}})();
</script>
</body></html>"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
