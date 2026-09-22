"""Read the documented local CSV contract; no broker-specific format inference."""

import csv
from io import StringIO


def read_events_csv(text: str) -> list[dict]:
    reader = csv.DictReader(StringIO(text.lstrip("\ufeff")))
    if not reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise ValueError("CSV requires unique column names")
    optional = {
        "supersedes_hash",
        "effective_at",
        "market",
        "symbol",
        "side",
        "quantity",
        "gross_amount",
        "fee",
        "tax",
        "net_cash_amount",
        "settlement_date",
        "counter_currency",
        "counter_amount",
    }
    result = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("CSV row width does not match header")
        for key in optional & row.keys():
            if row[key] == "":
                row[key] = None
        if str(row.get("revision", "")).isdigit():
            row["revision"] = int(row["revision"])
        if row.get("settlement_confirmed") in {"true", "false"}:
            row["settlement_confirmed"] = row["settlement_confirmed"] == "true"
        result.append(row)
    return result
