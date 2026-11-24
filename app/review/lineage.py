"""Prior-signature read-back for the handover.

A night-shift operator needs to see what earlier hands already signed for the
same business groups before deciding whether to sign the current batch on time
or hold it until the late events arrive. The prior view is derived only from
runs created *before* the current one, so replaying the current run is stable.
"""


def case_codes(report):
    return [case["case"] for case in report.get("cases", [])]


def _signed_for(report, codes):
    scope = report.get("scope") or {}
    per_case = scope.get("cases") or {}
    return {
        code: {
            "signed": (per_case.get(code) or {}).get("signed", 0),
            "blocked": (per_case.get(code) or {}).get("blocked", 0),
            "deferred": (per_case.get(code) or {}).get("deferred", 0),
            "conflicts": (per_case.get(code) or {}).get("conflicts", 0),
            "cutoff": (per_case.get(code) or {}).get("cutoff", {}),
        }
        for code in codes
    }


def earlier(current_id, runs):
    """Runs older than ``current_id`` that share at least one business group.

    ``runs`` arrives newest first (see ``Store.recent``), so position in the
    list is the ordering; this avoids ties between runs created in the same
    millisecond.
    """
    position = next(
        (index for index, row in enumerate(runs) if row["id"] == current_id), None
    )
    if position is None:
        return []
    codes = set(case_codes(runs[position]["report"]))
    if not codes:
        return []
    keep = []
    for row in runs[position + 1 :]:
        shared = [code for code in case_codes(row["report"]) if code in codes]
        if shared:
            keep.append((row, shared))
    return keep


def summarize(current, runs):
    """Prior signatures grouped by business group, newest first."""
    entries = []
    groups = {}
    for row, shared in earlier(current["id"], runs)[:10]:
        report = row["report"]
        entry = {
            "id": row["id"],
            "created": row["created"],
            "status": row["status"],
            "revision": row["revision"],
            "note": row["note"],
            "reviewed": row["reviewed"],
            "cases": shared,
            "scope": _signed_for(report, shared),
            "releasable": (report.get("balance") or {}).get("releasable"),
        }
        entries.append(entry)
        for code in shared:
            groups.setdefault(
                code,
                {
                    "id": row["id"],
                    "status": row["status"],
                    "revision": row["revision"],
                    "note": row["note"],
                    "reviewed": row["reviewed"],
                    **entry["scope"][code],
                },
            )
    return {"runs": entries, "groups": groups}
