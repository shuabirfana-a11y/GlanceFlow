from __future__ import annotations

from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager


FONT_PATH = Path("C:/Windows/Fonts/msyh.ttc")
if FONT_PATH.is_file():
    font_manager.fontManager.addfont(str(FONT_PATH))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(FONT_PATH)).get_name()
plt.rcParams["axes.unicode_minus"] = False


def _finish(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _note(ax, sample_count: int) -> None:
    ax.set_title(f"{ax.get_title()}\nn={sample_count}；Windows 本地 CPU 模拟器，非实体眼镜", pad=10)


def generate_figures(
    output_dir: Path,
    system_metrics: list[dict],
    ablation_metrics: list[dict],
    full_confusion: dict[str, dict[str, int]],
    latency_rows: list[dict],
    failure_cases: list[dict],
    reliability: dict,
    sample_count: int,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    labels = [item["system_id"] for item in system_metrics]
    keys = ["erroneous_execution_rate", "valid_coverage_rate", "false_rejection_rate", "package_complete_accuracy"]
    names = ["错误执行率", "有效覆盖率", "误拒率", "日程包完全正确率"]
    x = np.arange(len(labels)); width = .18
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for index, (key, name) in enumerate(zip(keys, names, strict=True)):
        values = [(item[key]["value"] or 0) * 100 for item in system_metrics]
        ax.bar(x + (index - 1.5) * width, values, width, label=name)
    ax.set_xticks(x, labels); ax.set_ylabel("百分比（%）"); ax.set_title("三个系统核心指标同集对比"); ax.legend(ncol=2); ax.set_ylim(0, 105); _note(ax, sample_count)
    path = output_dir / "01_system_core_metrics.png"; _finish(fig, path); paths.append(path)

    statuses = list(full_confusion)
    matrix = np.array([[full_confusion[actual][predicted] for predicted in statuses] for actual in statuses])
    fig, ax = plt.subplots(figsize=(8.5, 7))
    image = ax.imshow(matrix, cmap="YlGn", vmin=0)
    for row in range(len(statuses)):
        for column in range(len(statuses)):
            ax.text(column, row, str(matrix[row, column]), ha="center", va="center")
    ax.set_xticks(range(len(statuses)), statuses, rotation=25, ha="right"); ax.set_yticks(range(len(statuses)), statuses)
    ax.set_xlabel("预测状态"); ax.set_ylabel("真实状态"); ax.set_title("Full System 四状态混淆矩阵"); fig.colorbar(image, ax=ax); _note(ax, sample_count)
    path = output_dir / "02_safety_confusion_matrix.png"; _finish(fig, path); paths.append(path)

    for number, key, title, filename in (
        (3, "erroneous_execution_rate", "七项消融：错误执行率", "03_ablation_error_rate.png"),
        (4, "valid_coverage_rate", "七项消融：有效覆盖率", "04_ablation_coverage_rate.png"),
    ):
        fig, ax = plt.subplots(figsize=(10, 5.2))
        names_ = [item["system_id"] for item in ablation_metrics]
        values = [(item[key]["value"] or 0) * 100 for item in ablation_metrics]
        bars = ax.barh(names_, values, color="#4d9f89" if number == 4 else "#d78264")
        ax.bar_label(bars, fmt="%.1f%%", padding=3); ax.set_xlim(0, max(105, max(values, default=0) + 12)); ax.set_xlabel("百分比（%）"); ax.set_title(title); _note(ax, sample_count)
        path = output_dir / filename; _finish(fig, path); paths.append(path)

    full_latency = [row for row in latency_rows if row["system_id"] == "full_system"]
    fig, axes = plt.subplots(2, 1, figsize=(11, 9))
    for ax, input_type, title in zip(
        axes, ("IMAGE", "VIDEO"), ("图片输入", "视频输入"), strict=True,
    ):
        rows = [row for row in full_latency if row["input_type"] == input_type]
        stage_names = [row["stage"].replace("_ms", "") for row in rows]
        medians = [row["median_ms"] for row in rows]
        p90 = [row["p90_ms"] for row in rows]
        x = np.arange(len(stage_names))
        ax.plot(x, medians, marker="o", linewidth=2, label="中位数")
        ax.plot(x, p90, marker="s", linewidth=2, label="P90")
        ax.set_xticks(x, stage_names, rotation=20, ha="right")
        ax.set_yscale("log")
        ax.set_ylabel("毫秒（对数刻度）")
        ax.set_title(f"{title}：仅统计实际执行阶段")
        ax.legend()
        for index, row in enumerate(rows):
            ax.annotate(
                f"n={row['effective_sample_count']}",
                (index, max(row["median_ms"], row["p90_ms"])),
                xytext=(0, 6), textcoords="offset points", ha="center", fontsize=8,
            )
    fig.suptitle(f"Full System Windows 本地 CPU 模拟器耗时；总样本 n={sample_count}，非实体眼镜")
    path = output_dir / "05_stage_latency.png"; _finish(fig, path); paths.append(path)

    counts = Counter(case["error_layer"] or "outcome_mismatch" for case in failure_cases)
    fig, ax = plt.subplots(figsize=(8.5, 5)); bars = ax.bar(counts.keys(), counts.values(), color="#bd7a52")
    ax.bar_label(bars); ax.set_ylabel("案例数"); ax.set_title("代表性失败案例层级分布"); ax.tick_params(axis="x", rotation=25); _note(ax, sample_count)
    path = output_dir / "06_failure_type_distribution.png"; _finish(fig, path); paths.append(path)

    reliability_keys = ["readback_consistency_rate", "rollback_success_rate", "undo_success_rate"]
    reliability_names = ["回读一致", "回滚成功", "撤销成功"]
    values = [reliability[key]["numerator"] for key in reliability_keys]
    denominators = [reliability[key]["denominator"] for key in reliability_keys]
    fig, ax = plt.subplots(figsize=(7.5, 4.8)); bars = ax.bar(reliability_names, values, color=["#4d9f89", "#6998c5", "#9b7fc2"])
    ax.bar_label(bars, labels=[f"{value}/{total} 次" for value, total in zip(values, denominators, strict=True)])
    ax.set_ylim(0, max(denominators) + 2); ax.set_ylabel("满足预期的试验次数"); ax.set_title("隔离内存日历功能路径试验（非大样本统计）"); _note(ax, sample_count)
    path = output_dir / "07_transaction_reliability.png"; _finish(fig, path); paths.append(path)
    return paths
