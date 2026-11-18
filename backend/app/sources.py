"""Zgjedhja e burimeve që i shfaqen studentit poshtë përgjigjes."""


def select_sources(hits: list[tuple], margin: float = 0.08, limit: int = 3) -> list[dict]:
    """Merr (document_id, titulli, distanca[, source_url]) për secilën pjesë të gjetur.

    Shfaqen vetëm dokumentet që janë pothuajse aq afër pyetjes sa pjesa më e mirë
    (brenda `margin`), dhe jo më shumë se `limit`. Kështu nuk shfaqen si burim dokumente
    që u gjetën vetëm si kontekst i largët.
    """
    if not hits:
        return []
    best = min(hit[2] for hit in hits)
    selected: dict[int, dict] = {}
    for hit in sorted(hits, key=lambda h: h[2]):
        document_id, title, distance = hit[0], hit[1], hit[2]
        source_url = hit[3] if len(hit) > 3 else None
        if distance > best + margin or len(selected) >= limit:
            break
        selected.setdefault(document_id, {"id": document_id, "title": title, "source_url": source_url})
    return list(selected.values())
