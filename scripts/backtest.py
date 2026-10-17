"""Out-of-sample checks on the Lift Ledger (H5, H6). LastLift makes no failure predictions; this script shows why,
and shows what the history does support (k explains how often a platform loses access).

    python scripts/backtest.py     # writes data/history/backtest.json and claims.json (hist_bt_*)

H6 (negative result): rank lifts by 2024 history, compare with the step-free hours each one actually cost in 2025
(Spearman rank correlation and precision of the top ten), for three rankings: 2024 hours x impact, impact alone,
2024 alert count. Impact = platform-directions the lift is the single point of failure for.

H5 (monthly occurrence, rolling origin): for each test month (the last 17 archive months), each lift's chance of at
least one closure that month is estimated from the previous 12 months (Beta-Bernoulli, prior fitted to all lifts in
the training window) and compared with what happened. Scored by Brier skill against the pooled base rate, with a
station-cluster bootstrap interval, and a 10-bin reliability diagram. Bins with at least 100 forecasts must be within
0.08 of the observed frequency; if not, the failure is stated.

Validation of k: share of (platform-direction, month) pairs with any lost hour, for k = 1 against k >= 2.
"""
import collections
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import history_replay as hr  # noqa: E402

BOOT_SEED = 20261019          # eval/VALIDATION_PROTOCOL.md: station-cluster bootstrap, 1,000 resamples
BOOT_N = 1000
FOLDS = 17


def spearman(x, y):
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    rx, ry = ranks(x), ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return round(cov / (sx * sy), 3) if sx and sy else None


def precision_at(pred, actual, n=10):
    top_p = set(sorted(pred, key=lambda k: (-pred[k], k))[:n])
    top_a = set(sorted(actual, key=lambda k: (-actual[k], k))[:n])
    return round(len(top_p & top_a) / n, 2)


def months_between(a, b):
    out, (y, m) = [], a
    while (y, m) <= b:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + (m == 12), m % 12 + 1)
    return out


def main():
    from lastlift import seed
    net = json.loads((seed.latest_snapshot() / "network.json").read_text(encoding="utf-8"))
    sw = json.loads((hr.HIST / "service_windows.json").read_text(encoding="utf-8"))
    meta = json.loads((hr.HIST / "meta.json").read_text(encoding="utf-8"))
    archive_end = hr.parse(meta["archive_end"])
    eps = hr.episodes(hr.merged_windows())
    modelled = set(net["lifts"])
    platform = net["platform"]

    # --- H6: does 2024 rank the lifts that cost the most step-free hours in 2025? -----------------------------
    impact = collections.Counter()
    for p in platform.values():
        for d in ("board", "exit"):
            for c in p[d].get("minimal") or []:
                if len(c) == 1:
                    impact[c[0]] += 1

    def year(y):
        a, b = datetime(y, 1, 1, tzinfo=timezone.utc), datetime(y + 1, 1, 1, tzinfo=timezone.utc)
        clipped = {f: [(max(s, a), min(e, b), *r) for s, e, *r in es if e > a and s < b] for f, es in eps.items()}
        _, per_lift, _, _ = hr.replay(clipped, platform, modelled, sw)
        hours = {f: sum((e - s).total_seconds() / 3600 for s, e, *_ in es) for f, es in clipped.items()}
        alerts = {f: len({x for *_, aids, _c in es for x in aids}) for f, es in clipped.items()}
        return per_lift, hours, alerts

    cost25, _, _ = year(2025)
    _, hours24, alerts24 = year(2024)
    lifts = sorted(f for f in modelled if impact[f] > 0)
    actual = {f: cost25[f]["single_svc_h"] if f in cost25 else 0.0 for f in lifts}
    rankings = {
        "hours_x_impact_2024": {f: hours24.get(f, 0.0) * impact[f] for f in lifts},
        "impact_only": {f: float(impact[f]) for f in lifts},
        "alerts_2024": {f: float(alerts24.get(f, 0)) for f in lifts},
    }
    h6 = {name: {"spearman": spearman([r[f] for f in lifts], [actual[f] for f in lifts]),
                 "precision_at_10": precision_at(r, actual)} for name, r in rankings.items()}
    h6["lifts"] = len(lifts)

    # --- H5: monthly occurrence, rolling origin --------------------------------------------------------------
    lm = archive_end.year, archive_end.month - 1 or 12
    if archive_end.month == 1:
        lm = (archive_end.year - 1, 12)
    all_months = months_between((2020, 1), lm)
    occ = collections.defaultdict(set)                # lift -> months with any closure
    for f, es in eps.items():
        if f not in modelled:
            continue
        for s, e, *_ in es:
            for m in months_between((s.year, s.month), (e.year, e.month)):
                occ[f].add(m)
    station_of = {f: x["station_id"] for f, x in net["lifts"].items()}
    lift_list = sorted(modelled)
    forecasts = []                                    # (station, p_model, p_clim, y)
    for i in range(len(all_months) - FOLDS, len(all_months)):
        train = all_months[i - 12:i]
        test = all_months[i]
        counts = [sum(m in occ[f] for m in train) for f in lift_list]
        mean = sum(counts) / (12 * len(counts))
        var = sum((c / 12 - mean) ** 2 for c in counts) / len(counts)
        # method-of-moments Beta prior on the monthly rate, shrunk towards the pooled rate
        k = max(mean * (1 - mean) / var - 1, 1.0) if var > 0 else 50.0
        a, b = mean * k, (1 - mean) * k
        for f, c in zip(lift_list, counts):
            forecasts.append((station_of[f], (a + c) / (a + b + 12), mean, 1 if test in occ[f] else 0))

    def brier(rows):
        bm = sum((p - y) ** 2 for _, p, _, y in rows) / len(rows)
        bc = sum((q - y) ** 2 for _, _, q, y in rows) / len(rows)
        return bm, bc, 1 - bm / bc if bc else None

    bm, bc, skill = brier(forecasts)
    by_station = collections.defaultdict(list)
    for r in forecasts:
        by_station[r[0]].append(r)
    stations = sorted(by_station)
    rng = random.Random(BOOT_SEED)
    boots = []
    for _ in range(BOOT_N):
        rows = [r for s in (rng.choice(stations) for _ in stations) for r in by_station[s]]
        boots.append(brier(rows)[2])
    boots.sort()
    ci = [round(boots[int(0.025 * BOOT_N)], 3), round(boots[int(0.975 * BOOT_N) - 1], 3)]
    bins = []
    for j in range(10):
        lo, hi = j / 10, (j + 1) / 10
        sel = [(p, y) for _, p, _, y in forecasts if lo <= p < hi or (j == 9 and p == 1.0)]
        if sel:
            pred = sum(p for p, _ in sel) / len(sel)
            obs = sum(y for _, y in sel) / len(sel)
            bins.append({"bin": [lo, hi], "n": len(sel), "pred": round(pred, 3), "obs": round(obs, 3),
                         "ok": len(sel) < 100 or abs(pred - obs) <= 0.08})
    calibrated = all(b["ok"] for b in bins)

    # --- validation of k: how often did platform-directions lose access, by k? -------------------------------
    replay = json.loads((hr.HIST / "replay.json").read_text(encoding="utf-8"))
    ledger_months = months_between((2024, 1), lm)
    k_groups = {"k1": [0, 0], "k2plus": [0, 0]}
    for stop, p in platform.items():
        for d in ("board", "exit"):
            k = p[d].get("k")
            if not k or p[d].get("at_grade"):
                continue
            g = "k1" if k == 1 else "k2plus"
            lost = set((replay["platform_dirs"].get(f"{stop}:{d}") or {}).get("months", []))
            k_groups[g][0] += len(lost & set(ledger_months))
            k_groups[g][1] += len(ledger_months)
    k_share = {g: round(x / n, 4) if n else None for g, (x, n) in k_groups.items()}

    doc = {"h6": h6, "h5": {"folds": FOLDS, "forecasts": len(forecasts), "brier_model": round(bm, 4),
                            "brier_climatology": round(bc, 4), "skill": round(skill, 3) if skill is not None else None,
                            "skill_ci95_station_bootstrap": ci, "reliability": bins, "calibrated": calibrated,
                            "test_months": all_months[-FOLDS:]},
           "k_validation": {"months": len(ledger_months), "share_of_months_with_loss": k_share,
                            "pairs": {g: v for g, v in k_groups.items()}}}
    (hr.HIST / "backtest.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8",
                                           newline="\n")
    claims_path = ROOT / "claims.json"
    claims = {k: v for k, v in json.loads(claims_path.read_text(encoding="utf-8")).items()
              if not k.startswith("hist_bt_")}
    claims.update({
        "hist_bt_spearman": h6["hours_x_impact_2024"]["spearman"],
        "hist_bt_p10": h6["hours_x_impact_2024"]["precision_at_10"],
        "hist_bt_spearman_alerts": h6["alerts_2024"]["spearman"],
        "hist_bt_lifts": h6["lifts"],
        "hist_bt_brier_skill": doc["h5"]["skill"], "hist_bt_brier_skill_ci": f"{ci[0]}, {ci[1]}",
        "hist_bt_calibrated": calibrated,
        "hist_bt_k1_month_share": k_share["k1"], "hist_bt_k2_month_share": k_share["k2plus"],
    })
    claims_path.write_text(json.dumps(claims, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(doc, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
