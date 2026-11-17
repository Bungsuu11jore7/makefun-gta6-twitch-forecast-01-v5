# makefun-gta6-twitch-forecast-01-v5

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Bungsuu11jore7/makefun-gta6-twitch-forecast-01-v5/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Bungsuu11jore7/makefun-gta6-twitch-forecast-01-v5/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Forecasts GTA VI's launch-day Twitch viewers hour by hour. Version 5, a genuine step-change over v4: every past launch curve is first re-indexed into unlock time (hours since the US East Coast midnight unlock, 04:00Z in daylight saving, 05:00Z in standard time; simultaneous-global launches use their own unlock hour, mixed console+PC-simultaneous launches are left out rather than aligned to the wrong hour), and three diverse centre models are blended in log space — a kernel-weighted local-linear ridge of the log viewer-ratio on log hour-1 print, plus two kernel-weighted mean curves at different bandwidths. The blend is then corrected with the launch's own pre-release pattern: a one-sided diurnal dip (where the launch's own pre-release audience already vanished, the forecast trough deepens — never the reverse), an inflation shift at the trough hours gated by the launch's own midday dip, an early-dip echo at midday, and a small-launch evening lift. The pre-release diurnal profile is a 5-tap triangular smooth over the 14 days before release, so sparse-sampling noise doesn't masquerade as shape. The spread is a per-hour lognormal width from this centre's practice residual spread (x1.15, floored at 0.15). For a mega launch beyond the biggest comparable, the size slope is damped to 30% past the data range and the inflation/size terms are capped, so the forecast falls with size but never explodes or collapses. Deterministic, stdlib only.

Local practice score (SullyGnome truth): mean pinball loss 0.0952 (p00 0.0770, p01 0.1093, p02 0.0810, p03 0.1136) vs v4's 0.1063, v3's 0.1189, v1's 0.1623 and the house baseline's 0.3871. Leave-one-launch-out over the 26 comparable past launches: mean 0.5478, median 0.3886 (dominated by a few unpredictable small/simultaneous launches); over the 11 big launches most like GTA VI: mean 0.2317, median 0.2048. Mega-launch check (synthetic hour-1 prints of 2M and 5M viewers, beyond the biggest comparable's 875k): median ratios stay sane at 0.38–1.14 and 0.37–1.09 with no explosion, collapse or wild oscillation.

## Run it

```sh
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=6wtj6288&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>
