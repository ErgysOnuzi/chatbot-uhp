"""Pyetësori i përdorshmërisë: pohimet dhe përmbledhja e përgjigjeve."""

import json
from statistics import mean

SURVEY_STATEMENTS = [
    "Chatbot-i ishte i lehtë për t'u përdorur.",
    "Përgjigjet ishin të qarta dhe të kuptueshme.",
    "Përgjigjet ishin të sakta.",
    "Shqipja e përgjigjeve ishte korrekte.",
    "Përgjigjet erdhën mjaftueshëm shpejt.",
    "Burimi i treguar te përgjigjja më ndihmoi.",
    "Do ta përdorja chatbot-in në vend që ta pyes administratën.",
    "Do t'ua rekomandoja chatbot-in kolegëve.",
]

PROGRAMS = ["TIT", "Dizajnimi i Softuerëve", "Master", "Tjetër"]


def summarize(rows: list[tuple[str, str | None, str | None]]) -> dict:
    """rows: (answers_json, program, comment). Kthen mesataret dhe shpërndarjen për çdo pohim."""
    answers = [json.loads(a) for a, _, _ in rows]
    statements = []
    for i, text in enumerate(SURVEY_STATEMENTS):
        values = [a[i] for a in answers if i < len(a)]
        statements.append({
            "statement": text,
            "mean": round(mean(values), 2) if values else None,
            "distribution": [values.count(score) for score in range(1, 6)],
            "agree_share": round(100 * sum(v >= 4 for v in values) / len(values), 1) if values else None,
        })
    programs: dict[str, int] = {}
    for _, program, _ in rows:
        key = program or "Pa u shënuar"
        programs[key] = programs.get(key, 0) + 1
    return {
        "responses": len(rows),
        "statements": statements,
        "programs": programs,
        "comments": [c for _, _, c in rows if c],
    }
