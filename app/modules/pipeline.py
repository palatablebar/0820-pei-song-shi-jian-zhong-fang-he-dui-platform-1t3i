from app.business import DomainIssue
from app.intake.service import inspect
from app.modules.calculate import compute
from app.modules.grouping import case_groups
from app.modules.policy import policy
from app.modules.prepare import plan, prepare
from app.modules.reconcile import balance
from app.modules.scope import case_scope, handover, pending_summary, scope_summary


def evaluate(rows, stage):
    case = {
        "case": rows[0]["case"],
        "records": [r["record"] for r in rows],
        "status": "READY",
    }
    verdict = plan(rows)
    case["scope"] = case_scope(verdict)
    try:
        case["prep"], payload = prepare(rows, verdict)
        if stage >= 3:
            case["measure"] = compute(payload)
        if stage >= 4:
            case.update(policy(case["measure"]))
    except DomainIssue as error:
        case["status"] = error.code
        if error.details:
            case["issues"] = error.details
    return case


def run(data, stage=5):
    intake = inspect(data)
    output = {"intake": {k: v for k, v in intake.items() if k != "rows"}}
    if stage == 1:
        return output
    cases = [evaluate(rows, stage) for _, rows in case_groups(intake["rows"])]
    output["cases"] = cases
    if stage >= 2:
        output["scope"] = scope_summary(cases)
        output["pending"] = pending_summary(cases)
    if stage >= 5:
        output["balance"] = balance(intake, cases)
        output["handover"] = handover(output["scope"], output["pending"], output["balance"])
    return output
