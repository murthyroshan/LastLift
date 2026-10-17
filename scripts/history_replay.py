"""Lift Ledger: replay every archived elevator closure through today's step-free graph (H1, H2 bracket, H3).

    python scripts/history_replay.py      # writes data/history/replay.json, claims.json (hist_*), applies to the graph

Episodes: an alert's windows per lift, merged when the gap between them is at most GAP_MIN minutes (default 30).
Ends: recorded when MBTA recorded one; otherwise imputed (default: the alert's last modification, "low"). The
sensitivity table re-runs everything with imputed windows left out or extended ("high"), and gaps of 0/30/120.

Event sweep: between two consecutive changes of the set C of closed modelled lifts, a platform-direction has lost
step-free access exactly when C contains one of its minimal failure sets (computed and checked in M10). A lost hour
is "single lift" when C contains a one-lift failure set for it, otherwise "concurrent" (redundancy defeated: two or
more lifts out at once). Hours are counted on the calendar and within the station's scheduled service day (first to
last departure, Boston local time); headlines use service hours.
"""
import collections
import csv
import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ingest"))

from history import eastern_offset  # noqa: E402

HIST = ROOT / "data" / "history"
GAP_MIN = 30
LEDGER_FROM = datetime(2024, 1, 1, tzinfo=timezone.utc)
DAY_KIND = ["weekday"] * 5 + ["saturday", "sunday"]


def parse(t):
    return datetime.fromisoformat(t.replace("Z", "+00:00")) if t else None


def load_windows(name="windows.csv"):
    path = HIST / name
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        return [{**r, "start": parse(r["start"]), "end_recorded": parse(r["end_recorded"]),
                 "end_low": parse(r["end_low"]), "end_high": parse(r["end_high"])} for r in csv.DictReader(fh)]


def merged_windows():
    """Portal windows first; a portal window with no recorded end takes LAMP's recorded end for the same alert and
    lift; LAMP windows for (alert, lift) pairs the portal lacks are added. Each row keeps its source."""
    portal = [{**w, "source": "portal"} for w in load_windows()]
    lamp = load_windows("windows_lamp.csv")
    lamp_by = collections.defaultdict(list)
    for w in lamp:
        lamp_by[(w["alert_id"], w["facility_id"])].append(w)
    seen = set()
    for w in portal:
        k = (w["alert_id"], w["facility_id"])
        seen.add(k)
        if w["end_recorded"] is None:
            ends = [x["end_recorded"] for x in lamp_by.get(k, []) if x["end_recorded"] and x["end_recorded"] > w["start"]]
            if ends:
                w["end_recorded"], w["source"] = max(ends), "portal+lamp_end"
    added = [{**w, "source": "lamp"} for k, ws in lamp_by.items() if k not in seen for w in ws]
    return portal + added


def episodes(windows, imputed="low", gap_min=GAP_MIN):
    """Per facility: merged closure episodes [(start, end, imputed, alert_ids, causes)]."""
    per = collections.defaultdict(list)
    for w in windows:
        end = w["end_recorded"] or (None if imputed == "out" else w[f"end_{imputed}"])
        if end and end > w["start"]:
            per[w["facility_id"]].append((w["start"], end, w["end_recorded"] is None, w["alert_id"], w["cause"]))
    gap = timedelta(minutes=gap_min)
    out = {}
    for f, ws in per.items():
        ws.sort()
        merged = []
        for s, e, imp, aid, cause in ws:
            if merged and s - merged[-1][1] <= gap:
                m = merged[-1]
                merged[-1] = (m[0], max(m[1], e), m[2] or imp, m[3] | {aid}, m[4] | {cause})
            else:
                merged.append((s, e, imp, {aid}, {cause}))
        out[f] = merged
    return out


def service_hours(station_win, t0, t1):
    """Hours of [t0, t1) inside the station's scheduled service (first to last departure, local time)."""
    if not station_win:
        return 0.0
    total = 0.0
    off = eastern_offset(t0)
    day = (t0 + off).date() - timedelta(days=1)          # the previous service day can run past midnight
    while True:
        midnight_local = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        kind = DAY_KIND[day.weekday()]
        if kind in station_win:
            first, last = station_win[kind]
            off = eastern_offset(midnight_local + timedelta(hours=12))
            a = midnight_local - off + timedelta(seconds=first)
            b = midnight_local - off + timedelta(seconds=last)
            lo, hi = max(a, t0), min(b, t1)
            if hi > lo:
                total += (hi - lo).total_seconds() / 3600
        if midnight_local - timedelta(hours=6) > t1:
            break
        day += timedelta(days=1)
    return total


def replay(eps, platform, modelled, windows_by_station, start_at=None):
    """Sweep the closed set over time. Returns per platform-direction and per lift totals, and a daily series."""
    events = collections.defaultdict(lambda: [0, set(), set()])     # t -> [_, opened, closed]
    count = collections.Counter()
    for f, es in eps.items():
        if f not in modelled:
            continue
        for s, e, *_ in es:
            if start_at and e <= start_at:
                continue
            s = max(s, start_at) if start_at else s
            events[s][2].add(f)
            events[e][1].add(f)
    dirs = []                                           # (stop, dir, station, minimal sets as frozensets, singles)
    for stop, p in platform.items():
        for d in ("board", "exit"):
            m = p[d].get("minimal")
            if m:
                sets = [frozenset(x) for x in m]
                dirs.append((stop, d, p["station_id"], sets, {next(iter(x)) for x in sets if len(x) == 1}))
    by_fac = collections.defaultdict(list)
    for i, (_, _, _, sets, _) in enumerate(dirs):
        for f in set().union(*sets):
            by_fac[f].append(i)
    per_dir = collections.defaultdict(lambda: {"cal_h": 0.0, "svc_h": 0.0, "single_svc_h": 0.0,
                                               "concurrent_svc_h": 0.0, "months": set(), "losses": 0})
    per_lift = collections.defaultdict(lambda: {"single_svc_h": 0.0, "single_cal_h": 0.0})
    daily = collections.defaultdict(float)              # local date -> platform-direction service hours lost
    concurrent_events = collections.Counter()
    times = sorted(events)
    closed = collections.Counter()
    lost_before = set()
    for t0, t1 in zip(times, times[1:] + [None]):
        _, opened, newly = events[t0]
        for f in opened:
            closed[f] -= 1
            if closed[f] <= 0:
                del closed[f]
        for f in newly:
            closed[f] += 1
        if t1 is None:
            break
        C = set(closed)
        cand = {i for f in C for i in by_fac.get(f, ())}
        lost_now = set()
        for i in cand:
            stop, d, st, sets, singles = dirs[i]
            if any(s <= C for s in sets):
                lost_now.add(i)
                cal = (t1 - t0).total_seconds() / 3600
                svc = service_hours(windows_by_station.get(st), t0, t1)
                x = per_dir[(stop, d)]
                x["cal_h"] += cal
                x["svc_h"] += svc
                ym = (t0 + eastern_offset(t0)).strftime("%Y-%m")
                x["months"].add(ym)
                single = singles & C
                if single:
                    x["single_svc_h"] += svc
                    for f in single:
                        per_lift[f]["single_svc_h"] += svc
                        per_lift[f]["single_cal_h"] += cal
                else:
                    x["concurrent_svc_h"] += svc
                    if i not in lost_before:
                        concurrent_events[(stop, d)] += 1
                if i not in lost_before:
                    x["losses"] += 1
                daily[(t0 + eastern_offset(t0)).strftime("%Y-%m-%d")] += svc
        lost_before = lost_now
    return per_dir, per_lift, daily, concurrent_events


def lift_stats(eps, archive_end):
    """Per lift (H3): availability over the last 12 and 24 archive months, outages, median repair time, months."""
    out = {}
    for f, es in eps.items():
        stats = {}
        for months in (12, 24):
            lo = archive_end - timedelta(days=round(365.25 * months / 12))
            h = sum(max(0, (min(e, archive_end) - max(s, lo)).total_seconds()) for s, e, *_ in es) / 3600
            span = (archive_end - lo).total_seconds() / 3600
            stats[f"avail_{months}m"] = round(1 - h / span, 4)
            stats[f"closed_h_{months}m"] = round(h, 1)
            stats[f"outages_{months}m"] = sum(1 for s, e, *_ in es if e > lo)
        durs = [(e - s).total_seconds() / 3600 for s, e, imp, *_ in es if s >= archive_end - timedelta(days=731)]
        stats["mttr_h"] = round(statistics.median(durs), 1) if durs else None
        stats["last_outage_end"] = max(e for _, e, *_ in es).strftime("%Y-%m-%dT%H:%M:%SZ")
        strip = collections.defaultdict(float)
        for s, e, *_ in es:
            t = max(s, LEDGER_FROM)
            while t < e:
                nxt = datetime(t.year + (t.month == 12), t.month % 12 + 1, 1, tzinfo=timezone.utc)
                strip[t.strftime("%Y-%m")] += (min(e, nxt) - t).total_seconds() / 3600
                t = nxt
        stats["months"] = {k: round(v, 1) for k, v in sorted(strip.items()) if k <= archive_end.strftime("%Y-%m")}
        out[f] = stats
    return out


def empirical_reliability(platform, lifts, net_obj, samples=1000, seed=20261021):
    """G5 with each lift's own unavailability (1 - availability over the last 12 archive months) instead of a
    uniform q: exact per platform-direction, Monte-Carlo (seeded) for journeys between stations."""
    import random
    q = {f: max(0.0, 1 - x["avail_12m"]) for f, x in lifts.items() if x.get("avail_12m") is not None}
    per = {}
    for stop, p in platform.items():
        for d in ("board", "exit"):
            m, rel = p[d].get("minimal"), p[d].get("relevant")
            if not m or not rel:
                continue
            bit = {f: 1 << i for i, f in enumerate(rel)}
            masks = [sum(bit[f] for f in c) for c in m]
            qs = [q.get(f, 0.0) for f in rel]
            r = 0.0
            for mask in range(1 << len(rel)):
                if any(mm & mask == mm for mm in masks):
                    pr = 1.0
                    for i, qi in enumerate(qs):
                        pr *= qi if mask >> i & 1 else 1 - qi
                    r += pr
            per[f"{stop}:{d}"] = {"r": round(r, 6), "q_missing": sorted(f for f in rel if f not in q)}
    rng = random.Random(seed)
    facs = sorted(net_obj.units)
    total = len(net_obj.stations) * (len(net_obj.stations) - 1)
    shares = []
    for _ in range(samples):
        down = [f for f in facs if rng.random() < q.get(f, 0.0)]
        shares.append(sum(len(v) for v in net_obj.od(down).values()) / total)
    m = statistics.mean(shares)
    half = 1.96 * statistics.stdev(shares) / samples ** 0.5
    return per, {"mean": round(m, 5), "ci95": [round(m - half, 5), round(m + half, 5)], "samples": samples,
                 "seed": seed, "q_source": "1 - availability over the last 12 archive months"}


def main():
    from lastlift import seed, state
    snap = seed.latest_snapshot()
    net = json.loads((snap / "network.json").read_text(encoding="utf-8"))
    meta = json.loads((HIST / "meta.json").read_text(encoding="utf-8"))
    archive_end = parse(meta["archive_end"])
    sw = json.loads((HIST / "service_windows.json").read_text(encoding="utf-8"))
    modelled = set(net["lifts"])
    platform = net["platform"]
    ws = merged_windows()                     # portal + LAMP (see merged_windows)
    portal_ws = load_windows()
    lamp_ws = load_windows("windows_lamp.csv")

    def run(imputed="low", gap=GAP_MIN, start_at=LEDGER_FROM, src=None):
        eps = episodes(src if src is not None else ws, imputed, gap)
        return eps, replay(eps, platform, modelled, sw, start_at)

    eps, (per_dir, per_lift, daily, conc) = run()
    total_svc = sum(x["svc_h"] for x in per_dir.values())
    single_svc = sum(x["single_svc_h"] for x in per_dir.values())
    sens = []
    for imputed in ("out", "low", "high"):
        for gap in (0, 30, 120):
            _, (pd_, *_rest) = run(imputed, gap)
            sens.append({"imputed": imputed, "gap_min": gap,
                         "dirs_lost": len(pd_), "calendar_h": round(sum(x["cal_h"] for x in pd_.values())),
                         "service_h": round(sum(x["svc_h"] for x in pd_.values())),
                         "single_share": round(sum(x["single_svc_h"] for x in pd_.values()) /
                                               max(1e-9, sum(x["svc_h"] for x in pd_.values())), 4)})
    # H2: calendar 2025 platform-direction hours, recorded ends only, from each source and merged
    y25, y26 = datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc)

    def year_cal(src, imputed="out"):
        e = episodes(src, imputed, GAP_MIN)
        e = {f: [(max(s, y25), min(t, y26), *r) for s, t, *r in es if t > y25 and s < y26] for f, es in e.items()}
        pd_, *_r = replay(e, platform, modelled, sw, None)
        return round(sum(x["cal_h"] for x in pd_.values()))
    bracket_2025 = {"portal_recorded": year_cal(portal_ws), "portal_imputed_high": year_cal(portal_ws, "high"),
                    "lamp_recorded": year_cal(lamp_ws), "merged_recorded": year_cal(ws),
                    "merged_imputed_low": year_cal(ws, "low")}
    lamp_meta = json.loads((HIST / "lamp_meta.json").read_text(encoding="utf-8")) if lamp_ws else {}
    _, (_pd, _pl, daily_all, _c) = run(start_at=None)
    yearly = collections.defaultdict(float)
    for d, h in daily_all.items():
        yearly[d[:4]] += h
    sources = collections.Counter(w["source"] for w in ws)
    lamp = {"source": lamp_meta.get("source"), "sha256": lamp_meta.get("sha256"),
            "from": lamp_meta.get("first_window_start"), "windows_by_source": dict(sorted(sources.items())),
            "yearly_service_h": {y: round(h) for y, h in sorted(yearly.items())}}
    lifts = lift_stats(eps, archive_end)
    from lastlift import network
    rel_emp, mc_emp = empirical_reliability(platform, lifts, network.get(state.graph_name("base")))
    top_dir = max(per_dir.items(), key=lambda kv: (kv[1]["svc_h"], kv[0]))
    top_lift = max(per_lift.items(), key=lambda kv: (kv[1]["single_svc_h"], kv[0]))
    doc = {
        "from": LEDGER_FROM.strftime("%Y-%m-%d"), "archive_end": meta["archive_end"], "gap_min": GAP_MIN,
        "imputed": "low",
        "platform_dirs": {f"{s}:{d}": {"cal_h": round(x["cal_h"], 1), "svc_h": round(x["svc_h"], 1),
                                       "single_svc_h": round(x["single_svc_h"], 1),
                                       "concurrent_svc_h": round(x["concurrent_svc_h"], 1),
                                       "months": sorted(x["months"]), "losses": x["losses"],
                                       "concurrent_losses": conc.get((s, d), 0)}
                          for (s, d), x in sorted(per_dir.items())},
        "lifts": {f: {**lifts.get(f, {}), "single_svc_h": round(per_lift[f]["single_svc_h"], 1) if f in per_lift else 0.0}
                  for f in sorted(set(lifts) | set(per_lift))},
        "episodes": {f: [[s.strftime("%Y-%m-%dT%H:%M:%SZ"), e.strftime("%Y-%m-%dT%H:%M:%SZ"), imp, sorted(a),
                          sorted(c - {""})] for s, e, imp, a, c in es] for f, es in sorted(eps.items())},
        "daily_svc_h": {k: round(v, 2) for k, v in sorted(daily.items())},
        "sensitivity": sens, "bracket_2025_calendar_h": bracket_2025,
        "reliability_empirical": rel_emp, "monte_carlo_empirical": mc_emp, "lamp": lamp,
    }
    (HIST / "replay.json").write_text(json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n",
                                      encoding="utf-8", newline="\n")
    claims_path = ROOT / "claims.json"
    claims = {k: v for k, v in json.loads(claims_path.read_text(encoding="utf-8")).items()
              if not k.startswith("hist_") or k.startswith(("hist_bt_", "hist_gold_"))}   # backtest / gold own those
    n_eps = sum(len(es) for f, es in eps.items())
    claims.update({
        "hist_from": doc["from"], "hist_archive_end": meta["archive_end"][:10],
        "hist_alerts": meta["alerts"], "hist_windows": meta["windows"], "hist_episodes": n_eps,
        "hist_facilities": meta["facilities_in_archive"],
        "hist_windows_imputed": sum(1 for w in ws if w["end_recorded"] is None), "hist_windows_merged": len(ws),
        "hist_dirs_lost": len(per_dir), "hist_lost_service_h": round(total_svc),
        "hist_lost_calendar_h": round(sum(x["cal_h"] for x in per_dir.values())),
        "hist_single_share": round(single_svc / max(total_svc, 1e-9), 4),
        "hist_concurrent_service_h": round(sum(x["concurrent_svc_h"] for x in per_dir.values())),
        "hist_concurrent_losses": sum(conc.values()),
        "hist_top_dir": f"{top_dir[0][0]}:{top_dir[0][1]}", "hist_top_dir_service_h": round(top_dir[1]["svc_h"]),
        "hist_top_lift": top_lift[0], "hist_top_lift_service_h": round(top_lift[1]["single_svc_h"]),
        "hist_2025_portal_h": bracket_2025["portal_recorded"], "hist_2025_lamp_h": bracket_2025["lamp_recorded"],
        "hist_2025_merged_h": bracket_2025["merged_recorded"],
        "hist_drift_not_in_gtfs": len(meta["drift"]["archive_not_in_gtfs"]),
        "hist_drift_model_never": len(meta["drift"]["model_never_in_archive"]),
        "rel_emp_dirs_over_5pct": sum(1 for x in rel_emp.values() if x["r"] > 0.05),
        "rel_emp_dirs": len(rel_emp),
        "rel_emp_worst_dir": max(rel_emp, key=lambda k: (rel_emp[k]["r"], k)),
        "rel_emp_worst": round(max(x["r"] for x in rel_emp.values()), 4),
        "net_mc_reachable_emp": mc_emp["mean"],
    })
    claims.update({"hist_lamp_from": (lamp["from"] or "")[:7],
                   "hist_windows_lamp_added": sources.get("lamp", 0),
                   "hist_windows_lamp_end": sources.get("portal+lamp_end", 0)})
    claims_path.write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in claims.items() if k.startswith("hist_")}, indent=1))
    print(json.dumps(sens, indent=0))
    applied = seed.apply_history(state.graph_name("base"), ROOT / "data" / "history")
    print("applied", applied)
    return 0


if __name__ == "__main__":
    sys.exit(main())
