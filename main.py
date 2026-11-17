"""gta6-twitch-ccu-forecast-01, version 5: an unlock-aligned log-space ensemble.

Forecasts GTA VI's launch-day Twitch viewers hour by hour (hours 2..24, five
quantiles each) from the case's hour-1 print and the past launches in the file.

The model, in one paragraph: every past launch curve is re-indexed into
unlock time (hours since the US East Coast midnight unlock, 04:00Z in daylight
saving, 05:00Z in standard time; simultaneous-global launches use their own
unlock hour), because a launch's shape is driven by when regions unlock, not
by the UTC clock. Three diverse centre models are fitted on those
unlock-aligned log viewer-ratio curves and blended in log space --
  1. a kernel-weighted local-linear ridge of the log ratio on log hour-1
     print (size is the dominant shape driver: big launches spike at hour 1
     and fall back, small launches build through the day),
  2. a kernel-weighted mean curve (bandwidth 1.5 in log size),
  3. the same mean with a wider bandwidth (2.5), which steadies the tails --
and the blend is then corrected with the launch's own pre-release pattern
(the only target-specific signal beyond hour 1):
  * a one-sided diurnal dip: where the launch's own pre-release audience
    already vanished at an hour (smoothed mean log viewers by UTC hour over
    the 14 days before release, relative to its midnight level), the
    forecast trough at that hour deepens -- never the reverse, because
    pre-release highs are trailer/event noise, not shape signal;
  * an inflation shift at the trough hours: the further the hour-1 print sits
    above the launch's own pre-release midnight level, the deeper the
    troughs, gated by how deep the launch's own midday dip is (so a launch
    with a flat pre-release midday keeps its shallow trough);
  * an early-dip echo: a launch that already dipped hard in hours 2-4 dips
    harder again at midday (the two dips correlate across past launches);
  * a small-launch evening lift: launches below ~60k at hour 1 rise more
    into the evening than the size regression captures (validated
    leave-one-launch-out: the evening residual grows 0.30 per log unit below
    11.0), applied flat over hours 16-23 and exactly zero for big launches.

Spread: per-hour lognormal widths from the practice residual spread of this
centre (x1.15, floored at 0.15 so the late hours never go razor-thin), baked
in as constants. Extrapolation guards for a mega launch (hour 1 beyond the
biggest comparable, log 13.68): the local-linear slope is damped to 30%
beyond the data range, the inflation level is capped at 10.0 and the
early-trough size gate at 1.0, so the forecast can fall with size but can
never explode or collapse.

Deterministic, standard library only, offline. Reads MAKEFUN_INPUT_DIR /
MAKEFUN_OUTPUT_DIR (default /input, /output), one case per *.in file.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.645, -0.674, 0, 0.674, 1.645]

# Per-hour lognormal widths (hours 2..24), = 1.15 x the smoothed practice
# residual sd of this centre, floored at 0.15.
SIGMA = [0.26, 0.25, 0.30, 0.21, 0.18, 0.16, 0.18, 0.20, 0.22, 0.29, 0.32,
         0.32, 0.25, 0.24, 0.25, 0.26, 0.23, 0.17, 0.15, 0.15, 0.15, 0.15,
         0.15]

# Trough hour offsets (1-based from the release day's hour 1): hours 2-4 and
# hours 10-14. All dip/inflation corrections apply only here.
TROUGH_EARLY = (0, 1, 2)          # offsets 1..3  -> hours 2..4
TROUGH_MID = (9, 10, 11, 12, 13)  # offsets 10..14 -> hours 10..14
EVENING = tuple(range(15, 23))    # offsets 16..23 -> hours 17..24

SIMULTANEOUS_UNLOCK = {
    "Black Myth: Wukong": 2,
    "Hollow Knight: Silksong": 14,
    "Battlefield 6": 14,
    "007 First Light": 14,
    "Cyberpunk 2077": 0,
}


def parse_ts(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)


def epoch_hour(text):
    return int(parse_ts(text).timestamp() // 3600)


def us_dst(year, month, day):
    """True when the date falls in US daylight saving (2nd Sun Mar .. 1st Sun Nov)."""
    def nth_sunday(y, m, n):
        d = datetime(y, m, 1, tzinfo=timezone.utc)
        delta = (6 - d.weekday()) % 7
        return d + timedelta(days=delta + 7 * (n - 1))

    start = nth_sunday(year, 3, 2)
    end = nth_sunday(year, 11, 1)
    dt = datetime(year, month, day, tzinfo=timezone.utc)
    return start <= dt < end


def round2(x):
    """Round to 2 decimals, half up, like JavaScript's Math.round(x*100)/100."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value == int(value) else value


def smooth3(xs):
    out = []
    for i in range(len(xs)):
        vals = [xs[j] for j in (i - 1, i, i + 1) if 0 <= j < len(xs)]
        out.append(sum(vals) / len(vals))
    return out


def clip(x, lo, hi):
    return max(lo, min(hi, x))


class Launch:
    """One past launch: release-day curve + pre-release diurnal, in log space."""

    def __init__(self, name, day_start, hourly, tier, unlock_text=""):
        self.name = name
        self.day_start = day_start
        self.tier = tier
        self.unlock_text = unlock_text or ""
        self.ds_h = epoch_hour(day_start)
        self.pts = {}
        for p in hourly or []:
            try:
                off = epoch_hour(p["from"]) - self.ds_h
            except (KeyError, TypeError, ValueError):
                continue
            self.pts[off] = max(0, p.get("viewers", 0))

    def p1(self):
        v = self.pts.get(0)
        return v if v and v >= 1 else None

    def logratio(self):
        """log(viewers[h] / viewers[1]) for offsets 0..23, or None if incomplete."""
        p1 = self.p1()
        if p1 is None:
            return None
        out = []
        for o in range(24):
            v = self.pts.get(o)
            if v is None or v < 1:
                return None
            out.append(math.log(v / p1))
        return out

    def pre_diurnal(self):
        """Mean log viewers by UTC hour over the 14 days before release
        (offsets -336..-1), passed through a 3-point moving average twice --
        a 5-tap triangular smooth. The pre-release series is sparse (a small
        category is sampled only a few times a day), so a single hour's spike
        is usually sampling noise, not shape; the wide smooth keeps only
        the persistent day shape. None when any hour has too few points."""
        by = {h: [] for h in range(24)}
        for off, v in self.pts.items():
            if -336 <= off < 0:
                by[(self.ds_h + off) % 24].append(math.log(max(v, 1)))
        out = []
        for h in range(24):
            if len(by[h]) < 3:
                return None
            out.append(sum(by[h]) / len(by[h]))
        return smooth3(smooth3(out))

    def weekday(self):
        return parse_ts(self.day_start).weekday()

    def unlock_hour(self):
        """UTC hour of the US-East midnight unlock for rolling launches, the
        launch's own simultaneous unlock hour, or None if unusable. A mixed
        launch whose text reports a simultaneous/global PC unlock on top of
        rolling consoles (e.g. ELDEN RING) has no single unlock hour: its
        curve is dominated by the PC surge, so it is left out of the
        unlock-aligned pool rather than aligned to the wrong hour."""
        if self.name in SIMULTANEOUS_UNLOCK:
            return SIMULTANEOUS_UNLOCK[self.name]
        text = self.unlock_text.lower()
        if "simultaneous" in text or "single global" in text:
            return None
        ds = parse_ts(self.day_start)
        return 4 if us_dst(ds.year, ds.month, ds.day) else 5


def tier_of(unlock_text):
    text = unlock_text or ""
    if "early-access-contaminated" in text:
        return "early"
    if "Tier: weak" in text:
        return "weak"
    if "Tier: target-history" in text:
        return "stub"
    return "comparable"


def unlock_curve(launch, logr):
    """The launch's log-ratio curve re-indexed by unlock-relative hour u in
    -5..23 (index 0 == 5 hours before unlock); edges clamped."""
    uc = launch.unlock_hour()
    if uc is None:
        return None
    return [logr[clip(u + uc, 0, 23)] for u in range(-5, 24)]


def kernel_weight(dx, bw):
    return math.exp(-0.5 * (dx / bw) ** 2)


def weekday_factor(wd_target, wd_comp):
    same_side = (wd_target >= 5) == (wd_comp >= 5)
    return 1.0 if same_side else 0.75

# --- centre members (all operate on unlock-aligned curves) -----------------

def member_uloclin(target, pool):
    """Kernel-weighted local-linear ridge of the log ratio on log hour-1
    print, fitted per unlock-relative hour. The slope is damped to 30%
    beyond the comparables' size range, so a mega launch extrapolates
    gently instead of linearly off a cliff."""
    lp = math.log(target["p1"])
    ut = target["unlock"]
    data = []
    for comp, ucurve in pool:
        w = kernel_weight(math.log(comp.p1()) - lp, 1.8)
        w *= weekday_factor(target["wd"], comp.weekday())
        data.append((math.log(comp.p1()), w, ucurve))
    out = []
    for o in range(1, 24):
        iu = (o - ut) + 5
        sw = sum(w for _, w, _ in data)
        if sw <= 0:
            out.append(0.0)
            continue
        mr = sum(w * r[iu] for _, w, r in data) / sw
        mx = sum(w * x for x, w, _ in data) / sw
        sxx = sum(w * (x - mx) ** 2 for x, w, _ in data) + 0.6
        sxy = sum(w * (x - mx) * (r[iu] - mr) for x, w, r in data)
        slope = sxy / sxx if sxx > 0 else 0.0
        dx = lp - mx
        xs = [x for x, _, _ in data]
        lo, hi = min(xs), max(xs)
        if lp > hi:
            dx = (hi - mx) + (lp - hi) * 0.3
        elif lp < lo:
            dx = (lo - mx) + (lp - lo) * 0.3
        out.append(mr + slope * dx)
    return out


def member_umean(target, pool, bw):
    """Kernel-weighted mean of the comparables' unlock-aligned curves."""
    lp = math.log(target["p1"])
    ut = target["unlock"]
    num = [0.0] * 29
    den = [0.0] * 29
    for comp, ucurve in pool:
        w = kernel_weight(math.log(comp.p1()) - lp, bw)
        w *= weekday_factor(target["wd"], comp.weekday())
        for i in range(29):
            num[i] += w * ucurve[i]
            den[i] += w
    out = []
    for o in range(1, 24):
        iu = (o - ut) + 5
        out.append(num[iu] / den[iu] if den[iu] > 0 else 0.0)
    return out


# --- target-specific corrections -------------------------------------------

def target_features(case):
    """Hour-1 print, weekday, unlock hour and the launch's own pre-release
    diurnal profile (clean: the pre-release window ends before release day,
    so the hour-1 print never leaks into the baseline)."""
    known = next((k for k in case["known"] if k["hour"] == 1), None)
    if known is None:
        raise ValueError("case has no hour-1 print")
    p1 = max(1, known["viewers"])
    tgt = Launch(case["game"]["name"], case["day_start"],
                 case.get("history_hourly") or [], "target")
    diurnal = tgt.pre_diurnal()
    ds = parse_ts(case["day_start"])
    unlock = 4 if us_dst(ds.year, ds.month, ds.day) else 5
    return {
        "p1": p1, "wd": tgt.weekday(), "unlock": unlock,
        "diurnal": diurnal,
        "midnight": diurnal[0] if diurnal else None,
    }


def apply_corrections(centre, feat, pool_infl_median):
    """Dip / inflation / early-dip-echo / small-launch evening lift, all in
    log-ratio units. Every term is one-sided or gated, and every
    size-driven term is capped, so a mega launch stays sane."""
    out = list(centre)
    logp1 = math.log(feat["p1"])
    diurnal = feat["diurnal"]
    if diurnal is None:
        # Offset-indexed dip (index i == forecast offset i+1 == UTC hour i+1).
        dip = [0.0] * 23
        midnight = None
    else:
        dip = [diurnal[h] - diurnal[0] for h in range(1, 24)]
        midnight = diurnal[0]
    dip_mid = sum(min(0.0, dip[o]) for o in TROUGH_MID) / len(TROUGH_MID)
    dip_early = sum(min(0.0, dip[o]) for o in TROUGH_EARLY) / len(TROUGH_EARLY)
    infl = (logp1 - midnight) if midnight is not None else pool_infl_median
    infl = min(infl, 10.0)  # cap: never deepen troughs beyond the data's range
    gate_mid = clip(-dip_mid / 0.10, 0.0, 1.0)
    size_gate = min(max(0.0, logp1 - 12.0), 1.0)
    for o in TROUGH_EARLY:
        out[o] += 0.7 * min(0.0, dip[o]) - 0.2 * size_gate
    for o in TROUGH_MID:
        out[o] += (0.7 * min(0.0, dip[o]) - 0.02 * infl * gate_mid
                   + 0.5 * dip_early)
    small = max(0.0, 11.0 - logp1)
    for o in EVENING:
        out[o] += 0.2 * small
    return out


# --- per-case forecast ------------------------------------------------------

def forecast_case(case):
    if case["levels"] != LEVELS:
        raise ValueError("case asks for levels %r, not %r"
                         % (case["levels"], LEVELS))
    feat = target_features(case)
    pool = []
    infls = []
    for comp in case.get("comparables") or []:
        if tier_of(comp.get("unlock", "")) != "comparable":
            continue
        launch = Launch(comp["name"], comp["day_start"],
                        comp.get("hourly") or [], "comparable",
                        comp.get("unlock", ""))
        logr = launch.logratio()
        ucurve = unlock_curve(launch, logr) if logr is not None else None
        if ucurve is None:
            continue
        pool.append((launch, ucurve))
        d = launch.pre_diurnal()
        if d is not None and launch.p1():
            infls.append(math.log(launch.p1()) - d[0])
    if not pool:
        raise ValueError("no usable comparables")
    infls.sort()
    pool_infl_median = infls[len(infls) // 2] if infls else 8.0

    target = {"p1": feat["p1"], "wd": feat["wd"], "unlock": feat["unlock"]}
    loclin = member_uloclin(target, pool)
    mean15 = member_umean(target, pool, 1.5)
    mean25 = member_umean(target, pool, 2.5)
    centre = [0.5 * a + 0.3 * b + 0.2 * c
              for a, b, c in zip(loclin, mean15, mean25)]
    centre = apply_corrections(centre, feat, pool_infl_median)

    logp1 = math.log(feat["p1"])
    hours = []
    prev = None
    for idx, o in enumerate(range(1, 24)):
        med = logp1 + centre[idx]
        sig = SIGMA[idx]
        qs = []
        for z in Z:
            q = round2(math.exp(med + z * sig))
            q = min(max(q, 0.01), 1e9)
            qs.append(q)
        # keep the row non-decreasing after rounding
        for i in range(1, 5):
            if qs[i] < qs[i - 1]:
                qs[i] = qs[i - 1]
        hours.append({"hour": o + 1, "q": qs})
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        (OUTPUT_DIR / (path.stem + ".out")).write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n",
            encoding="utf-8")


if __name__ == "__main__":
    main()
