import json


def artifact(run):
    report = run["report"]
    packet = {
        "schema": "review-evidence/1",
        "manifest": report["manifest"],
        "balance": report["balance"],
        "scope": report.get("scope"),
        "pending": report.get("pending"),
        "handover": report.get("handover"),
        "cases": report["cases"],
        "intake": report["intake"],
        "review": {key: run[key] for key in ("status", "revision", "note", "reviewed")},
    }
    return (
        json.dumps(packet, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
