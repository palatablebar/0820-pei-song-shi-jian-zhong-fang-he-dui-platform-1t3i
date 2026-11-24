"""Read-back summaries for one sign-off.

The workbench has to show, for the batch being signed right now, three things:
what is inside the sign-off scope, what is being carried or blocked, and what
the previous sign-off for the same business group left behind.

All of it is derived from the per-case verdict so that re-executing an
unchanged source is idempotent: a retry regenerates the same lists instead of
appending new pending rows.
"""

CARRY = "CARRY"  # late event, kept for the next batch, does not block today
BLOCK = "BLOCK"  # record or group that must be resolved before signing


def _empty_scope():
    return {
        "cutoff": {},
        "signed": [],
        "deferred": [],
        "conflicts": [],
        "counts": {"signed": 0, "deferred": 0, "conflicts": 0},
    }


def case_scope(verdict):
    signed = verdict["signed"]
    deferred = verdict["deferred"]
    conflicts = verdict["conflicts"]
    return {
        "cutoff": {str(p): c for p, c in sorted(verdict["ceilings"].items())},
        "signed": signed,
        "deferred": deferred,
        "conflicts": conflicts,
        "counts": {
            "signed": len(signed),
            "deferred": len(deferred),
            "conflicts": len(conflicts),
        },
    }


def scope_summary(cases):
    cutoff = {}
    per_case = {}
    signed, deferred, conflicts, blocked = [], [], [], []
    for case in cases:
        code = case["case"]
        scope = case.get("scope") or _empty_scope()
        passable = case["status"] == "READY"
        per_case[code] = {
            "status": case["status"],
            "cutoff": dict(sorted(scope["cutoff"].items())),
            "deferred": scope["counts"]["deferred"],
            "conflicts": scope["counts"]["conflicts"],
            "signed": scope["counts"]["signed"] if passable else 0,
            "blocked": 0 if passable else scope["counts"]["signed"],
        }
        for partition, ceiling in scope["cutoff"].items():
            cutoff[partition] = max(ceiling, cutoff.get(partition, ceiling))
        if passable:
            signed.extend(dict(ref, blocked=False) for ref in scope["signed"])
        else:
            blocked.extend(dict(ref, blocked=True) for ref in scope["signed"])
        deferred.extend(scope["deferred"])
        conflicts.extend(scope["conflicts"])
    return {
        "cutoff": dict(sorted(cutoff.items())),
        "items": signed,
        "blocked": blocked,
        "cases": per_case,
        "counts": {
            "signed": len(signed),
            "deferred": len(deferred),
            "conflicts": len(conflicts),
            "blocked": len(blocked),
        },
    }


def pending_summary(cases):
    """Events that need an operator after this batch.

    Carried late events are recorded so the next handover can pick them up, but
    they do not block an on-time sign-off. Same-key/same-sequence conflicts do
    block it. The list is a pure function of the source, so retrying the same
    bytes yields the same rows instead of piling up duplicates.

    Source rows rejected at intake stay in ``intake.isolation``; group-level
    verdicts (a missing expected row, a value mismatch) stay in ``balance``.
    """
    items = []
    for case in cases:
        scope = case.get("scope") or {}
        for ref in scope.get("deferred", []):
            items.append(dict(ref, source=CARRY, blocking=False))
        for ref in scope.get("conflicts", []):
            items.append(dict(ref, source=BLOCK, blocking=True))
    carried = sum(1 for item in items if item["source"] == CARRY)
    blocking = sum(1 for item in items if item["blocking"])
    return {
        "items": items,
        "count": len(items),
        "carried": carried,
        "blocking_count": blocking,
        "blocking": blocking > 0,
    }


def handover(scope, pending, checks):
    """Make the on-time vs. wait-for-complete trade-off explicit.

    ``signable`` mirrors the release gate. ``carried`` events were past the
    watermark and are not part of this sign-off, so their presence is the
    trade-off an on-time signer accepts; they still show up for the next
    handover. ``blocking`` items have to be resolved first.
    """
    carried = pending["carried"]
    blocking = pending["blocking_count"]
    signable = bool(checks["releasable"])
    if not signable:
        decision = "BLOCKED"
    elif carried:
        decision = "SIGN_NOW_CARRY"
    else:
        decision = "SIGN_NOW_COMPLETE"
    return {
        "decision": decision,
        "signable": signable,
        "complete": carried == 0 and blocking == 0,
        "on_time": signable,
        "carried": carried,
        "blocking": blocking,
        "signed": scope["counts"]["signed"],
        "cutoff": scope["cutoff"],
        "note": (
            "存在待处理记录，暂不能签发"
            if not signable
            else (
                f"可按时签发；{carried} 条滞后事件结转下批"
                if carried
                else "可按时签发；当前批次已齐"
            )
        ),
    }
