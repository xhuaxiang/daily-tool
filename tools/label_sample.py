#!/usr/bin/env python3
"""P0 人工标注样本：从运行快照生成 CSV，供人工打分。

不再重新抓取网络：样本就是当天邮件实际选中的候选池。
生成后填写 label / reason 两列：
- label: 4=必读, 3=有用, 2=一般, 1=噪音
- reason: 重要 / 可学习 / 重复 / 标题党 / 源太弱 / 正文缺失 / 翻译错误 / 分类错误 / 其他
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.snapshot import find_latest_snapshot, write_labels_csv

logger = logging.getLogger("news")


def _write_labels(sample: list[dict], output: Path) -> Path:
    """兼容旧调用：把样本写成标注 CSV。"""
    return write_labels_csv(sample, output)


def _load_snapshot(path: Path, limit: int) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    candidates = data.get("candidates") or []
    if not candidates:
        raise SystemExit(f"{path} 里没有 candidates 数据")
    if limit > 0:
        candidates = candidates[:limit]
    return data, candidates


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description="P0 从运行快照生成人工标注 CSV（不重新抓取网络）",
    )
    parser.add_argument(
        "--from-snapshot", default="",
        help="run-YYYY-MM-DD.json 路径；不填则使用最新的快照",
    )
    parser.add_argument(
        "--n", type=int, default=0,
        help="最多输出多少条候选（默认 0=全部，含落选）",
    )
    parser.add_argument(
        "--output", default="",
        help="输出 CSV；默认 data/labels-<run_date>.csv",
    )
    parser.add_argument("--force", action="store_true", help="覆盖已存在的 CSV")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    snapshot_path = Path(args.from_snapshot) if args.from_snapshot else find_latest_snapshot()
    if snapshot_path is None or not snapshot_path.exists():
        raise SystemExit(
            "没有找到运行快照；先运行 python main.py --preview，"
            "或用 --from-snapshot 指定 run-YYYY-MM-DD.json"
        )

    data, sample = _load_snapshot(snapshot_path, args.n)
    run_date = data.get("run_date") or snapshot_path.parent.name
    output = Path(args.output) if args.output else Path("data") / f"labels-{run_date}.csv"
    if output.exists() and not args.force:
        raise SystemExit(f"{output} 已存在；确认要覆盖请加 --force")

    write_labels_csv(sample, output)
    print()
    print(f"已从 {snapshot_path} 生成 {len(sample)} 篇待标注样本：{output.resolve()}")
    print("填写 label（4=必读 / 3=有用 / 2=一般 / 1=噪音）和 reason 两列。")
    print("提示：用 Excel 打开时选 UTF-8，或直接用编辑器编辑 CSV。")


if __name__ == "__main__":
    main()
