#!/usr/bin/env python3
"""Monthly fairness audit script (BIAS-04).

Reads all JSONL snapshots from data/fairness_audit/ and produces a
consolidated fairness report with:
- local_factor distribution across all recorded recommendations
- Violation detection: % of recommendations with < 40% local businesses in top-5
- Trend analysis: mean local_factor over time (if multiple snapshots exist)
- Pass/fail verdict against the BIAS-01 acceptance criterion (≥ 40% local in top-5)

Usage:
    python scripts/monthly_fairness_audit.py [--days 30] [--verbose]

The script exits 0 regardless of verdict. A non-pass verdict is surfaced
in the report output, not via exit code.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Resolve project root for path-independent execution.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_AUDIT_DIR = _PROJECT_ROOT / "data" / "fairness_audit"

# -- Thresholds (aligned with BIAS-01) --
LOCAL_FACTOR_THRESHOLD = 0.40  # ≥ 40% of top-5 must be local businesses
LOCAL_FACTOR_MIN = 0.5        # local_factor > 0.5 counts as "local business"


def load_audit_files(audit_dir: Path, days: int | None = None) -> list[dict]:
    """Load all JSONL audit files, optionally filtered by recency."""
    records = []
    if not audit_dir.exists():
        return records

    cutoff = None
    if days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for path in sorted(audit_dir.glob("*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                    ts_str = record.get("timestamp")
                    if ts_str and cutoff:
                        ts = datetime.fromisoformat(ts_str)
                        if ts < cutoff:
                            continue
                    records.append(record)
                except (json.JSONDecodeError, ValueError):
                    continue
    return records


def analyze_local_factors(records: list[dict]) -> dict:
    """Analyze local_factor distribution across all recorded recommendations."""
    all_factors: list[float] = []
    snapshot_stats: list[dict] = []
    violations = 0
    total_snapshots = 0

    for record in records:
        factors = record.get("local_factors", [])
        if not factors:
            continue
        total_snapshots += 1
        snapshot_factors = [float(f) for f in factors if f is not None]
        all_factors.extend(snapshot_factors)

        # Per-snapshot: % of places with local_factor > 0.5
        local_count = sum(1 for f in snapshot_factors if f > LOCAL_FACTOR_MIN)
        local_pct = local_count / len(snapshot_factors) if snapshot_factors else 0
        is_violation = local_pct < LOCAL_FACTOR_THRESHOLD

        if is_violation:
            violations += 1

        snapshot_stats.append({
            "timestamp": record.get("timestamp"),
            "place_count": len(snapshot_factors),
            "local_count": local_count,
            "local_pct": round(local_pct, 3),
            "mean_local_factor": round(sum(snapshot_factors) / len(snapshot_factors), 3) if snapshot_factors else 0,
            "violation": is_violation,
        })

    if not all_factors:
        return {
            "verdict": "NO_DATA",
            "message": "No fairness audit records found.",
            "total_snapshots": 0,
            "total_places": 0,
        }

    # Overall statistics
    mean_lf = sum(all_factors) / len(all_factors)
    local_overall = sum(1 for f in all_factors if f > LOCAL_FACTOR_MIN)
    local_pct_overall = local_overall / len(all_factors)

    # Bucket distribution
    buckets = {"0.0-0.2": 0, "0.2-0.4": 0, "0.4-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0}
    for f in all_factors:
        if f <= 0.2:
            buckets["0.0-0.2"] += 1
        elif f <= 0.4:
            buckets["0.2-0.4"] += 1
        elif f <= 0.6:
            buckets["0.4-0.6"] += 1
        elif f <= 0.8:
            buckets["0.6-0.8"] += 1
        else:
            buckets["0.8-1.0"] += 1

    # Trend: mean local_factor by date
    daily_means: dict[str, list[float]] = defaultdict(list)
    for stat in snapshot_stats:
        ts = stat.get("timestamp", "")
        if ts:
            date_str = ts[:10]  # YYYY-MM-DD
            daily_means[date_str].append(stat["mean_local_factor"])

    trend = {
        date: round(sum(vals) / len(vals), 3)
        for date, vals in sorted(daily_means.items())
    }

    verdict = "PASS" if violations == 0 else "FAIL"
    if total_snapshots == 0:
        verdict = "NO_DATA"

    return {
        "verdict": verdict,
        "total_snapshots": total_snapshots,
        "total_places": len(all_factors),
        "mean_local_factor": round(mean_lf, 4),
        "min_local_factor": round(min(all_factors), 4),
        "max_local_factor": round(max(all_factors), 4),
        "median_local_factor": round(sorted(all_factors)[len(all_factors) // 2], 4),
        "local_business_pct": round(local_pct_overall, 4),
        "snapshot_violations": violations,
        "snapshot_violation_rate": round(violations / total_snapshots, 4) if total_snapshots else 0,
        "threshold": LOCAL_FACTOR_THRESHOLD,
        "bucket_distribution": buckets,
        "trend_daily_mean": trend,
        "recent_snapshots": snapshot_stats[-5:],  # last 5 snapshots
    }


def print_report(analysis: dict, verbose: bool = False) -> None:
    """Print a human-readable fairness audit report."""
    verdict = analysis.get("verdict", "UNKNOWN")
    verdict_icon = "✅ PASS" if verdict == "PASS" else "❌ FAIL" if verdict == "FAIL" else "⚠️ NO_DATA"

    print("=" * 60)
    print("  HÀM NINH — Monthly Fairness Audit Report")
    print("=" * 60)
    print(f"  Verdict: {verdict_icon} {verdict}")
    print(f"  Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print()

    if verdict == "NO_DATA":
        print("  No fairness audit records found.")
        print("  Run the system with place recommendations to generate data.")
        return

    print(f"  Total snapshots: {analysis['total_snapshots']}")
    print(f"  Total places evaluated: {analysis['total_places']}")
    print()
    print("  Local Factor Distribution:")
    print(f"    Mean:   {analysis['mean_local_factor']:.4f}")
    print(f"    Median: {analysis['median_local_factor']:.4f}")
    print(f"    Min:    {analysis['min_local_factor']:.4f}")
    print(f"    Max:    {analysis['max_local_factor']:.4f}")
    print()

    print(f"  Local Business Share: {analysis['local_business_pct']:.1%} (threshold: {analysis['threshold']:.0%})")
    print(f"  Snapshot violations: {analysis['snapshot_violations']}/{analysis['total_snapshots']} ({analysis['snapshot_violation_rate']:.1%})")
    print()

    print("  Bucket Distribution:")
    for bucket, count in analysis["bucket_distribution"].items():
        bar = "█" * (count // max(1, analysis["total_places"] // 20))
        print(f"    {bucket}: {count:4d} {bar}")
    print()

    if analysis.get("trend_daily_mean"):
        print("  Daily Mean Trend:")
        for date, mean in analysis["trend_daily_mean"].items():
            print(f"    {date}: {mean:.4f}")
        print()

    if verdict == "FAIL":
        print("  ⚠️  VIOLATIONS DETECTED")
        print(f"  {analysis['snapshot_violations']} snapshot(s) had < {analysis['threshold']:.0%} local businesses in results.")
        print("  Review the recent snapshots below:")
        for snap in analysis.get("recent_snapshots", []):
            icon = "❌" if snap.get("violation") else "✅"
            print(f"    {icon} {snap.get('timestamp', '?')} — local_pct={snap.get('local_pct', 0):.1%}, mean_lf={snap.get('mean_local_factor', 0):.3f}")
        print()

    if verbose and analysis.get("recent_snapshots"):
        print("  Recent Snapshots (last 5):")
        for snap in analysis["recent_snapshots"]:
            print(f"    {json.dumps(snap, ensure_ascii=False)}")
        print()

    print("=" * 60)


def main() -> None:
    days = None
    verbose = False

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--days" and i + 1 < len(args):
            days = int(args[i + 1])
            i += 2
        elif args[i] == "--verbose":
            verbose = True
            i += 1
        else:
            i += 1

    records = load_audit_files(_AUDIT_DIR, days=days)
    analysis = analyze_local_factors(records)
    print_report(analysis, verbose=verbose)


if __name__ == "__main__":
    main()
