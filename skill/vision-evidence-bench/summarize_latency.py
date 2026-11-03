"""Summarize numeric frame metrics from a CSV file without third-party tools."""

import argparse
import csv
import json
import math


def percentile(values, fraction):
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(
        ordered[lower] * (1.0 - weight) + ordered[upper] * weight
    )


def summarize(path):
    columns = {}
    with open(path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            for key, raw in row.items():
                try:
                    value = float(raw)
                except (TypeError, ValueError):
                    continue
                columns.setdefault(key, []).append(value)
    return {
        key: {
            "count": len(values),
            "mean": sum(values) / len(values),
            "p95": percentile(values, 0.95),
            "max": max(values),
        }
        for key, values in columns.items()
        if values
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = summarize(args.csv_path)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    for key, stats in result.items():
        print(
            "%-20s n=%d mean=%9.3f p95=%9.3f max=%9.3f"
            % (
                key,
                stats["count"],
                stats["mean"],
                stats["p95"],
                stats["max"],
            )
        )


if __name__ == "__main__":
    main()
