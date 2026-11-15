#!/usr/bin/env python3
"""P0 离线评估：读取标注 CSV（可配合运行快照），输出选稿指标。

不调用网络、不发邮件。指标口径见 README：
- Precision@15：选中且 label>=3 的数量 / 15
- Recall：选中且 label>=3 / 所有 label>=3
- 噪音率：选中里 label=1 的比例
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.snapshot import find_latest_snapshot


def _to_int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "selected"}


def load_labels(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def merge_rows(rows: list[dict], snapshot: dict | None) -> list[dict]:
    """用快照补齐 CSV 里没有的字段（score、text_source、event_id 等）。"""
    if not snapshot:
        return rows
    by_id = {
        str(candidate.get("id")): candidate
        for candidate in snapshot.get("candidates", [])
        if candidate.get("id")
    }
    merged = []
    for row in rows:
        base = dict(by_id.get(str(row.get("id", "")), {}))
        for key, value in row.items():
            if value not in ("", None):
                base[key] = value
        base.setdefault("label", row.get("label", ""))
        base.setdefault("reason", row.get("reason", ""))
        merged.append(base)
    return merged


def _share_max(values: list[str]) -> float:
    if not values:
        return 0.0
    return round(max(Counter(values).values()) / len(values), 3)


def compute_metrics(rows: list[dict], total: int = 15) -> dict:
    labeled = []
    for row in rows:
        label = _to_int(row.get("label"))
        if label is not None:
            labeled.append({**row, "_label": label})

    selected = [row for row in rows if _truthy(row.get("selected"))]
    selected_labeled = [row for row in labeled if _truthy(row.get("selected"))]
    good_selected = [row for row in selected_labeled if row["_label"] >= 3]
    good_all = [row for row in labeled if row["_label"] >= 3]
    noisy_selected = [row for row in selected_labeled if row["_label"] == 1]

    page_selected = [
        row for row in selected if (row.get("text_source") or "") == "page"
    ]
    event_counts = Counter(
        row.get("event_id") for row in selected if row.get("event_id")
    )
    duplicated = sum(count for count in event_counts.values() if count > 1)

    by_source: dict[str, dict] = {}
    for row in selected_labeled:
        source = row.get("source", "") or "unknown"
        entry = by_source.setdefault(source, {"selected": 0, "good": 0})
        entry["selected"] += 1
        if row["_label"] >= 3:
            entry["good"] += 1

    return {
        "rows": len(rows),
        "labeled": len(labeled),
        "selected": len(selected),
        "selected_labeled": len(selected_labeled),
        "good_selected": len(good_selected),
        "good_all": len(good_all),
        "precision_at_15": round(len(good_selected) / total, 3) if total else 0.0,
        "precision": round(len(good_selected) / len(selected_labeled), 3)
        if selected_labeled else 0.0,
        "recall": round(len(good_selected) / len(good_all), 3) if good_all else 0.0,
        "noise_rate": round(len(noisy_selected) / len(selected_labeled), 3)
        if selected_labeled else 0.0,
        "fulltext_coverage": round(len(page_selected) / len(selected), 3)
        if selected else 0.0,
        "source_share_max": _share_max([row.get("source", "") for row in selected]),
        "publisher_share_max": _share_max(
            [row.get("publisher", "") for row in selected]
        ),
        "event_duplicate_rate": round(duplicated / len(selected), 3)
        if selected else 0.0,
        "label_distribution": dict(
            sorted(Counter(row["_label"] for row in labeled).items())
        ),
        "by_source": by_source,
    }


def _fmt_rate(value: float) -> str:
    return f"{value:.1%}"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="P0 选稿指标离线评估")
    parser.add_argument("labels", help="填写后的 labels-YYYY-MM-DD.csv")
    parser.add_argument("--snapshot", default="", help="对应的 run-YYYY-MM-DD.json")
    parser.add_argument("--total", type=int, default=15, help="Precision@N 的 N（默认 15）")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    labels_path = Path(args.labels)
    if not labels_path.exists():
        raise SystemExit(f"找不到标注文件：{labels_path}")

    snapshot_path = Path(args.snapshot) if args.snapshot else find_latest_snapshot()
    snapshot = None
    if snapshot_path and snapshot_path.exists():
        snapshot = load_snapshot(snapshot_path)
    rows = merge_rows(load_labels(labels_path), snapshot)
    metrics = compute_metrics(rows, args.total)
    metrics["labels_file"] = str(labels_path)
    metrics["snapshot_file"] = str(snapshot_path) if snapshot_path else ""

    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
        return

    print()
    print("=" * 56)
    print("[P0 评估]")
    print(f"标注 {metrics['labeled']} 条 / 样本 {metrics['rows']} 条；"
          f"选中 {metrics['selected']} 条，其中已标注 {metrics['selected_labeled']} 条")
    print("=" * 56)
    print(f"Precision@{args.total}: {_fmt_rate(metrics['precision_at_15'])} "
          f"({metrics['good_selected']}/{args.total})")
    print(f"Precision（已标注选中）: {_fmt_rate(metrics['precision'])}")
    print(f"Recall: {_fmt_rate(metrics['recall'])} "
          f"({metrics['good_selected']}/{metrics['good_all']})")
    print(f"噪音率: {_fmt_rate(metrics['noise_rate'])}")
    print(f"正文覆盖率: {_fmt_rate(metrics['fulltext_coverage'])} "
          f"({metrics['selected']} 篇中)")
    print(f"最大来源占比: {_fmt_rate(metrics['source_share_max'])}")
    print(f"最大媒体占比: {_fmt_rate(metrics['publisher_share_max'])}")
    print(f"事件重复率: {_fmt_rate(metrics['event_duplicate_rate'])}")
    if metrics["label_distribution"]:
        dist = " ".join(f"{key}={value}" for key, value in metrics["label_distribution"].items())
        print(f"标签分布: {dist}")
    else:
        print("标签分布: 尚未填写 label")
    print("=" * 56)


if __name__ == "__main__":
    main()
