"""Metrics for cascade detection and attribution against scenario ground truth."""

from __future__ import annotations

from collections.abc import Iterable


def precision_recall(outcomes: Iterable[tuple[bool, bool]]) -> dict:
    """outcomes: (predicted_cascade, true_cascade) pairs."""
    tp = fp = fn = tn = 0
    for predicted, truth in outcomes:
        if predicted and truth:
            tp += 1
        elif predicted and not truth:
            fp += 1
        elif not predicted and truth:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "precision": precision, "recall": recall}


def source_attribution(pred_node: str | None, true_node: str | None) -> bool | None:
    if true_node is None:
        return None
    return pred_node == true_node


def path_f1(pred_path: Iterable[str], true_path: Iterable[str]) -> float | None:
    pred, truth = set(pred_path), set(true_path)
    if not truth:
        return None
    if not pred:
        return 0.0
    overlap = len(pred & truth)
    precision = overlap / len(pred)
    recall = overlap / len(truth)
    return 0.0 if (precision + recall) == 0 else 2 * precision * recall / (precision + recall)


def blast_radius_error(pred_radius: float, true_affected: int, total: int) -> float | None:
    if not total:
        return None
    return abs(pred_radius - true_affected / total)


def summarize(rows: list[dict]) -> dict:
    """Aggregate per-scenario rows into headline numbers."""
    det = precision_recall((r["predicted_cascade"], r["true_cascade"]) for r in rows)
    attributions = [r["source_correct"] for r in rows if r.get("source_correct") is not None]
    f1s = [r["path_f1"] for r in rows if r.get("path_f1") is not None]
    radius_errors = [r["blast_radius_error"] for r in rows if r.get("blast_radius_error") is not None]
    delays = [r["detection_delay"] for r in rows if r.get("detection_delay") is not None]
    overheads = [r["overhead"] for r in rows if r.get("overhead") is not None]
    mean = lambda xs: (sum(xs) / len(xs)) if xs else None
    return {
        "scenarios": len(rows),
        "cascade_detection": det,
        "source_attribution_accuracy": mean([1.0 if a else 0.0 for a in attributions]),
        "propagation_path_f1": mean(f1s),
        "blast_radius_error": mean(radius_errors),
        "detection_delay_steps": mean(delays),
        "runtime_overhead": mean(overheads),
        "outcome_match": mean([1.0 if r.get("outcome_match") else 0.0 for r in rows]),
    }
