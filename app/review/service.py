from datetime import datetime, timezone
from hashlib import sha256
from time import monotonic

from app.business import DomainIssue
from app.config import RULE_VERSION
from app.modules.pipeline import run
from app.review import lineage


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def describe(store, run_id):
    """A stored run plus the old sign-offs it should be read against.

    The prior summary is derived at read time instead of being stored in the
    content-addressed report, so rerunning the same bytes keeps a stable report
    and never appends pending events.
    """
    current = store.load(run_id)
    current["prior"] = lineage.summarize(current, store.recent())
    return current


def execute(store, data):
    start = monotonic()
    fingerprint = sha256(data).hexdigest()
    run_id = sha256(f"{RULE_VERSION}:{fingerprint}".encode()).hexdigest()
    try:
        return store.load(run_id)
    except DomainIssue as error:
        if error.code != "RUN_NOT_FOUND":
            raise
    report = run(data)
    report["manifest"] = dict(
        sha256=fingerprint,
        version=RULE_VERSION,
        created=now(),
        duration_ms=round((monotonic() - start) * 1000, 3),
        bytes=len(data),
        run_id=run_id,
    )
    return store.register(run_id, report)


def review(store, run_id, values):
    if not isinstance(values, dict):
        raise DomainIssue("REVIEW_FIELDS")
    revision, status, note = (values.get(key) for key in ("revision", "status", "note"))
    if (
        type(revision) is not int
        or revision < 0
        or status not in ("APPROVED", "HELD")
        or not isinstance(note, str)
        or not (3 <= len(note.strip()) <= 200)
    ):
        raise DomainIssue("REVIEW_FIELDS")
    current = store.load(run_id)
    if revision != current["revision"]:
        raise DomainIssue("STALE_REVIEW")
    if current["status"] == "APPROVED":
        raise DomainIssue("RUN_FINALIZED")
    if status == "APPROVED":
        # Approve on time even if late events are carried, but nothing with a
        # blocking record or a failed group may go out.
        trade = current["report"].get("handover") or {}
        releasable = current["report"]["balance"]["releasable"]
        if not releasable or trade.get("blocking", 0) > 0:
            raise DomainIssue("UNRESOLVED_ISSUES")
    return store.revise(run_id, revision, status, note.strip(), now())
