from decimal import Decimal, localcontext

from app.models.account_ledger import LedgerBalance


def reconcile_ledger(replayed: dict, observed: dict) -> dict:
    snapshot = LedgerBalance.model_validate(observed)
    if (
        snapshot.account_id != replayed["account_id"]
        or snapshot.as_of.isoformat() != replayed["as_of"]
    ):
        raise ValueError("Reconciliation requires the same account and closing date")
    residuals = {}
    with localcontext() as context:
        context.prec = 60
        for name in ("cash", "positions", "receivables", "payables"):
            actual = getattr(snapshot, name)
            expected = replayed["balances"][name]
            residuals[name] = {
                key: actual.get(key, Decimal("0")) - expected.get(key, Decimal("0"))
                for key in sorted(actual.keys() | expected.keys())
            }
    differs = any(value != 0 for values in residuals.values() for value in values.values())
    return {
        "status": "incomplete" if replayed["issues"] else ("mismatch" if differs else "matched"),
        "balances_match": not differs,
        "residuals": residuals,
        "observed_hash": snapshot.source_record_hash,
        "issues": replayed["issues"],
        "tolerance": "0",
        "coverage_verified": False,
        "return_rate": None,
    }
