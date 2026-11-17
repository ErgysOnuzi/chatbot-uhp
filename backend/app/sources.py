"""Zgjedhja e burimeve që i shfaqen studentit poshtë përgjigjes."""


def select_sources(hits: list[tuple[int, str, float]], margin: float = 0.08, limit: int = 3) -> list[dict]:
    """Merr (document_id, titulli, distanca) të renditura sipas distancës.

    Shfaqen vetëm dokumentet që janë pothuajse aq afër pyetjes sa pjesa më e mirë
    (brenda `margin`), dhe jo më shumë se `limit`. Kështu nuk shfaqen si burim dokumente
    që u gjetën vetëm si kontekst i largët.
    """
    if not hits:
        return []
    best = min(distance for _, _, distance in hits)
    selected: dict[int, dict] = {}
    for document_id, title, distance in sorted(hits, key=lambda h: h[2]):
        if distance > best + margin or len(selected) >= limit:
            break
        selected.setdefault(document_id, {"id": document_id, "title": title})
    return list(selected.values())
