#!/usr/bin/env python3
"""Build charts only from explicitly reported, source-linked values in the production manifest."""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

manifest_path = Path("work/production_manifest.json")
script_path = Path("work/script.txt")
output_dir = Path("assets")
output_dir.mkdir(parents=True, exist_ok=True)

manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
script_text = script_path.read_text(encoding="utf-8")
charts = manifest.get("data_charts") or manifest.get("charts") or []
created = []
created_details = []

def number_tokens(text):
    tokens = set()
    for match in re.findall(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?%?(?![A-Za-z])", text):
        tokens.add(match.replace(",", "").replace("%", ""))
    return tokens

explicit_numbers = number_tokens(script_text)
for index, chart in enumerate(charts[:12], 1):
    title = str(chart.get("title") or "").strip()[:120]
    source_url = str(chart.get("source_url") or chart.get("source") or "").strip()
    labels = chart.get("labels") or []
    values = chart.get("values") or []
    if not values and isinstance(chart.get("points"), list):
        points = chart["points"]
        labels = [str(p.get("label") or "") for p in points]
        values = [p.get("value") for p in points]
        if not source_url and points:
            source_url = str(points[0].get("source_url") or points[0].get("source") or "")
    try:
        nums = [float(v) for v in values]
    except (TypeError, ValueError):
        print(f"Skipped chart {index}: values are not numeric.")
        continue
    parsed = urlparse(source_url)
    if not title or len(labels) < 2 or len(labels) != len(nums) or not parsed.scheme in ("https",) or not parsed.netloc:
        print(f"Skipped chart {index}: title, 2+ labels/values, and source URL are required.")
        continue
    if not all(f"{v:g}" in explicit_numbers or str(int(v)) in explicit_numbers for v in nums if float(v).is_integer() or True):
        print(f"Skipped chart {index}: one or more numeric values are not explicitly present in the script.")
        continue
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.bar(range(len(nums)), nums)
    ax.set_xticks(range(len(nums)), [str(x)[:28] for x in labels], rotation=20, ha="right")
    ax.set_title(title)
    ax.set_ylabel("Source-reported value (unit as described in script)")
    ax.grid(axis="y", alpha=0.22)
    domain = parsed.netloc.removeprefix("www.")
    fig.text(0.01, 0.01, f"Source: {domain} | Values are script/source-derived, not estimates.", fontsize=9)
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    path = output_dir / f"evidence_chart_{index}.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    created.append(str(path))
    created_details.append({
        "path": str(path),
        "title": title,
        "source_url": source_url,
        "labels": [str(x) for x in labels],
        "values": nums,
    })

Path("work/evidence_charts_report.json").write_text(
    json.dumps({"charts_created": created, "chart_details": created_details, "charts_requested": len(charts),
                "policy": "Only source-linked numeric values explicitly present in the script; up to twelve charts are rendered if supported by the sourced script data."}, indent=2),
    encoding="utf-8",
)
print(json.dumps({"charts_created": len(created), "charts_requested": len(charts)}))
