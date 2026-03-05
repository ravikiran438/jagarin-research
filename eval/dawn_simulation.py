"""
DAWN synthetic evaluation — compares DAWN against three baselines across
all 12 duty types using Monte Carlo simulation.

Baselines:
  B1: Fixed 7-day reminder (fires when daysRemain <= 7)
  B2: Fixed 14-day reminder (fires when daysRemain <= 14)
  B3: Deadline countdown (fires when daysRemain <= windowEnd)

Metric: "Optimal window hit rate" — fraction of decisions that fire within
the duty's declared optimal action window [windowEnd, windowStart].

For each duty type we simulate 1000 duties with randomised:
  - days remaining at evaluation time (uniform over 0..90)
  - hour of day (uniform over 0..23)
  - day of week (1..7)
  - charging state (Bernoulli 0.35)
  - wifi state (Bernoulli 0.60)
  - ignore streak (0..5)

All random seeds are fixed for reproducibility.
"""

import math
import random
import json
from dataclasses import dataclass, field
from typing import Optional

random.seed(42)

# ── Duty type parameters ──────────────────────────────────────────────────────

@dataclass
class DutyParams:
    name: str
    window_start: int   # days before deadline: window opens
    window_end: int     # days before deadline: window closes (must act by)
    toc_peak: float     # TOC score at peak of window (0-1)
    toc_sigma_l: float  # left sigma (days before peak)
    toc_sigma_r: float  # right sigma (days after peak, smaller = cliff)
    cliff: bool = False # True for BOPIS-style step function

DUTY_TYPES = [
    DutyParams("Insurance Renewal",    window_start=45, window_end=14, toc_peak=0.9, toc_sigma_l=12, toc_sigma_r=5),
    DutyParams("Prescription Refill",  window_start=14, window_end=3,  toc_peak=0.85,toc_sigma_l=5,  toc_sigma_r=2),
    DutyParams("Wellness Visit",       window_start=30, window_end=7,  toc_peak=0.75,toc_sigma_l=10, toc_sigma_r=4),
    DutyParams("Subscription Renewal", window_start=21, window_end=5,  toc_peak=0.80,toc_sigma_l=8,  toc_sigma_r=3),
    DutyParams("Vehicle Service",      window_start=30, window_end=7,  toc_peak=0.78,toc_sigma_l=10, toc_sigma_r=4),
    DutyParams("Return Deadline",      window_start=21, window_end=2,  toc_peak=0.88,toc_sigma_l=7,  toc_sigma_r=2),
    DutyParams("License Renewal",      window_start=60, window_end=14, toc_peak=0.85,toc_sigma_l=15, toc_sigma_r=6),
    DutyParams("Support Follow-up",    window_start=7,  window_end=1,  toc_peak=0.80,toc_sigma_l=3,  toc_sigma_r=1),
    DutyParams("Tax Deadline",         window_start=45, window_end=7,  toc_peak=0.92,toc_sigma_l=12, toc_sigma_r=4),
    DutyParams("Travel Check-in",      window_start=3,  window_end=0,  toc_peak=0.95,toc_sigma_l=1,  toc_sigma_r=0.5),
    DutyParams("Custom",               window_start=14, window_end=3,  toc_peak=0.75,toc_sigma_l=5,  toc_sigma_r=2),
    DutyParams("BOPIS Pickup",         window_start=2,  window_end=0,  toc_peak=1.0, toc_sigma_l=1,  toc_sigma_r=0.3, cliff=True),
]

# ── TOC ───────────────────────────────────────────────────────────────────────

def toc_score(days_remain: int, p: DutyParams) -> float:
    """Asymmetric Gaussian TOC; step function for BOPIS."""
    peak_day = (p.window_start + p.window_end) / 2
    dist = days_remain - peak_day
    if p.cliff:
        # Step function: full value within window, 0 outside
        return p.toc_peak if p.window_end <= days_remain <= p.window_start else 0.0
    sigma = p.toc_sigma_l if dist > 0 else p.toc_sigma_r
    if sigma <= 0:
        return p.toc_peak if dist == 0 else 0.0
    return p.toc_peak * math.exp(-(dist ** 2) / (2 * sigma ** 2))

# ── BEP ───────────────────────────────────────────────────────────────────────

def bep_score(hour: int, dow: int, charging: bool, wifi: bool, ignore_streak: int) -> float:
    """Rule-based BEP (logistic regression prior before personalization)."""
    score = 0.5
    # Time of day
    if 9 <= hour <= 11 or 14 <= hour <= 16:
        score += 0.20
    elif 18 <= hour <= 20:
        score += 0.10
    elif hour < 7 or hour > 22:
        score -= 0.25
    # Day of week (1=Mon..7=Sun)
    if dow in (6, 7):
        score += 0.10
    # Device context
    if charging:
        score += 0.08
    if wifi:
        score += 0.05
    # Ignore streak dampener
    score *= max(0.0, 1.0 - 0.15 * ignore_streak)
    return max(0.0, min(1.0, score))

# ── VDI ───────────────────────────────────────────────────────────────────────

def vdi_score(days_remain: int, p: DutyParams) -> float:
    """Rate of TOC decay: how fast value is being destroyed."""
    toc_now  = toc_score(days_remain, p)
    toc_next = toc_score(max(0, days_remain - 1), p)
    decay = toc_now - toc_next
    # Normalise to 0-1 (max single-day decay ≈ toc_peak)
    return min(1.0, max(0.0, decay / max(p.toc_peak, 0.01)))

# ── DAWN composite ────────────────────────────────────────────────────────────

W_TOC, W_BEP, W_VDI, W_CDR = 0.35, 0.25, 0.25, 0.15

def dawn_score(days_remain: int, p: DutyParams,
               hour: int, dow: int, charging: bool, wifi: bool,
               ignore_streak: int, cdr: float = 0.0) -> float:
    toc = toc_score(days_remain, p)
    bep = bep_score(hour, dow, charging, wifi, ignore_streak)
    vdi = vdi_score(days_remain, p)
    return W_TOC * toc + W_BEP * bep + W_VDI * vdi + W_CDR * cdr

NUDGE_THRESHOLD  = 0.45
ESCALATE_THRESHOLD = 0.70

def dawn_decision(score: float) -> str:
    if score >= ESCALATE_THRESHOLD:
        return "ACT_NOW"
    if score >= NUDGE_THRESHOLD:
        return "NUDGE"
    return "SLEEP"

# ── Baselines ─────────────────────────────────────────────────────────────────

def baseline_7(days_remain: int, p: DutyParams) -> str:
    return "NUDGE" if days_remain <= 7 else "SLEEP"

def baseline_14(days_remain: int, p: DutyParams) -> str:
    return "NUDGE" if days_remain <= 14 else "SLEEP"

def baseline_countdown(days_remain: int, p: DutyParams) -> str:
    return "NUDGE" if days_remain <= p.window_end else "SLEEP"

def baseline_window(days_remain: int, p: DutyParams) -> str:
    """Oracle baseline: fires exactly when in window (perfect timing, no BEP)."""
    return "NUDGE" if p.window_end <= days_remain <= p.window_start else "SLEEP"

# ── Evaluation ────────────────────────────────────────────────────────────────

def in_optimal_window(days_remain: int, p: DutyParams) -> bool:
    return p.window_end <= days_remain <= p.window_start

N_TRIALS = 1000

results = {}

for duty in DUTY_TYPES:
    dawn_hits = 0
    b7_hits   = 0
    b14_hits  = 0
    bc_hits   = 0
    dawn_false_early = 0  # fired outside window (too early)
    dawn_false_late  = 0  # fired outside window (too late / overdue)
    dawn_fires = 0
    b7_fires   = 0
    b14_fires  = 0
    bc_fires   = 0

    for _ in range(N_TRIALS):
        days   = random.randint(0, 90)
        hour   = random.randint(0, 23)
        dow    = random.randint(1, 7)
        charg  = random.random() < 0.35
        wifi   = random.random() < 0.60
        streak = random.choices([0,1,2,3,4,5], weights=[50,25,12,7,4,2])[0]
        in_win = in_optimal_window(days, duty)

        # DAWN
        score = dawn_score(days, duty, hour, dow, charg, wifi, streak)
        d_dec = dawn_decision(score)
        if d_dec != "SLEEP":
            dawn_fires += 1
            if in_win:
                dawn_hits += 1
            elif days > duty.window_start:
                dawn_false_early += 1
            else:
                dawn_false_late += 1

        # Baselines
        if baseline_7(days, duty) != "SLEEP":
            b7_fires += 1
            if in_win: b7_hits += 1
        if baseline_14(days, duty) != "SLEEP":
            b14_fires += 1
            if in_win: b14_hits += 1
        if baseline_countdown(days, duty) != "SLEEP":
            bc_fires += 1
            if in_win: bc_hits += 1

    def pct(hits, fires): return 100.0 * hits / fires if fires > 0 else 0.0
    def rate(fires): return 100.0 * fires / N_TRIALS

    results[duty.name] = {
        "window": f"{duty.window_end}–{duty.window_start} days",
        "dawn":   {"fire_rate": rate(dawn_fires), "precision": pct(dawn_hits, dawn_fires),
                   "false_early": dawn_false_early, "false_late": dawn_false_late},
        "b7":     {"fire_rate": rate(b7_fires),   "precision": pct(b7_hits,   b7_fires)},
        "b14":    {"fire_rate": rate(b14_fires),  "precision": pct(b14_hits,  b14_fires)},
        "bc":     {"fire_rate": rate(bc_fires),   "precision": pct(bc_hits,   bc_fires)},
    }

# ── Print results table ───────────────────────────────────────────────────────

print(f"\n{'Duty Type':<22} {'Window':<14} {'DAWN':>8} {'B-7d':>8} {'B-14d':>8} {'B-cntd':>8}")
print(f"{'':22} {'':14} {'prec%':>8} {'prec%':>8} {'prec%':>8} {'prec%':>8}")
print("-" * 76)

dawn_precisions = []
b7_precisions   = []
b14_precisions  = []
bc_precisions   = []

for duty_name, r in results.items():
    dp = r["dawn"]["precision"]
    bp7 = r["b7"]["precision"]
    bp14 = r["b14"]["precision"]
    bpc = r["bc"]["precision"]
    dawn_precisions.append(dp)
    b7_precisions.append(bp7)
    b14_precisions.append(bp14)
    bc_precisions.append(bpc)
    print(f"{duty_name:<22} {r['window']:<14} {dp:>7.1f}% {bp7:>7.1f}% {bp14:>7.1f}% {bpc:>7.1f}%")

print("-" * 76)
avg_dawn = sum(dawn_precisions) / len(dawn_precisions)
avg_b7   = sum(b7_precisions)   / len(b7_precisions)
avg_b14  = sum(b14_precisions)  / len(b14_precisions)
avg_bc   = sum(bc_precisions)   / len(bc_precisions)
print(f"{'Average':<22} {'':14} {avg_dawn:>7.1f}% {avg_b7:>7.1f}% {avg_b14:>7.1f}% {avg_bc:>7.1f}%")

print(f"\nFire rate comparison (% of evaluations that trigger a notification):")
print(f"{'Duty Type':<22} {'DAWN':>8} {'B-7d':>8} {'B-14d':>8} {'B-cntd':>8}")
print("-" * 60)
dawn_fire_rates = []
b7_fire_rates   = []
b14_fire_rates  = []
bc_fire_rates   = []
for duty_name, r in results.items():
    df = r["dawn"]["fire_rate"]
    bf7 = r["b7"]["fire_rate"]
    bf14 = r["b14"]["fire_rate"]
    bfc = r["bc"]["fire_rate"]
    dawn_fire_rates.append(df)
    b7_fire_rates.append(bf7)
    b14_fire_rates.append(bf14)
    bc_fire_rates.append(bfc)
    print(f"{duty_name:<22} {df:>7.1f}% {bf7:>7.1f}% {bf14:>7.1f}% {bfc:>7.1f}%")
print("-" * 60)
print(f"{'Average':<22} {sum(dawn_fire_rates)/len(dawn_fire_rates):>7.1f}% "
      f"{sum(b7_fire_rates)/len(b7_fire_rates):>7.1f}% "
      f"{sum(b14_fire_rates)/len(b14_fire_rates):>7.1f}% "
      f"{sum(bc_fire_rates)/len(bc_fire_rates):>7.1f}%")

# Save full results for paper
with open("dawn_eval_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("\nFull results saved to dawn_eval_results.json")
