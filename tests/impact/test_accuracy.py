from breakscope.impact import Confidence
from tests.impact.accuracy import DOC, detected, ground_truth, render, run, score


def test_precision_and_recall_on_corpus() -> None:
    report, truth = run(), ground_truth()
    default = score(report, truth, Confidence.MEDIUM)
    assert default.precision == 1.0, sorted(detected(report, Confidence.MEDIUM) - truth)
    assert default.recall >= 0.85, sorted(truth - detected(report, Confidence.MEDIUM))
    assert score(report, truth, Confidence.LOW).precision >= 0.9


def test_accuracy_doc_is_up_to_date() -> None:
    expected = render(run(), ground_truth())
    assert DOC.read_text(encoding="utf-8") == expected, (
        "docs/accuracy.md is stale: run `python tests/impact/accuracy.py`"
    )
