"""Derive judge eval verdict (pass/fail) from a stored report document."""


def eval_result_from_doc(doc: dict) -> str | None:
    """Return normalized verdict: pass, fail, review, or raw string; None if not judged."""
    if doc.get("_eval_result") is not None:
        value = doc["_eval_result"]
    else:
        eo = ((doc.get("judge") or {}).get("metrics") or {}).get("expected_outcome")
        if isinstance(eo, dict):
            value = eo.get("value")
        else:
            value = eo
    if value is None:
        return None
    v = str(value).strip().lower()
    if v == "pass":
        return "pass"
    if v in ("fail", "failed"):
        return "fail"
    if v == "review_required":
        return "review"
    return v
