import json

from app.survey import SURVEY_STATEMENTS, summarize


def test_summary_means_distribution_and_comments():
    n = len(SURVEY_STATEMENTS)
    rows = [
        (json.dumps([5] * n), "TIT", "Shumë i dobishëm"),
        (json.dumps([3] * n), "TIT", None),
        (json.dumps([4] * n), None, ""),
    ]
    result = summarize(rows)
    assert result["responses"] == 3
    first = result["statements"][0]
    assert first["mean"] == 4.0
    assert first["distribution"] == [0, 0, 1, 1, 1]
    assert first["agree_share"] == 66.7
    assert result["programs"] == {"TIT": 2, "Pa u shënuar": 1}
    assert result["comments"] == ["Shumë i dobishëm"]


def test_empty_summary():
    result = summarize([])
    assert result["responses"] == 0
    assert result["statements"][0]["mean"] is None
