"""Explicit, bounded CSV normalization; not a broker-specific statement adapter.

Raw documents remain outside persistence. A document/row key only deduplicates the
same document; overlapping statements require separate reconciliation.
"""

import csv
import hashlib
from io import StringIO
import json
import re

from pydantic import ValidationError

from app.models.account_ledger import LedgerEvent

SCHEMA_VERSION = "statement_csv_v1"
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
GENERATED = {"account_id", "observed_at", "source_type", "source_key", "source_record_hash"}
MAPPABLE = set(LedgerEvent.model_fields) - GENERATED
OPTIONAL = {key for key, field in LedgerEvent.model_fields.items() if not field.is_required()}


def _hash(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _validate_mapping(mapping):
    if not isinstance(mapping, dict) or set(mapping) - {
        "version",
        "columns",
        "constants",
        "value_maps",
    }:
        raise ValueError("Invalid statement mapping")
    if mapping.get("version") != SCHEMA_VERSION:
        raise ValueError("Unsupported statement mapping version")
    columns = mapping.get("columns", {})
    constants = mapping.get("constants", {})
    transforms = mapping.get("value_maps", {})
    if any(not isinstance(item, dict) for item in (columns, constants, transforms)):
        raise ValueError("Mapping sections must be objects")
    if (set(columns) | set(constants)) - MAPPABLE or set(columns) & set(constants):
        raise ValueError("Invalid or conflicting mapped fields")
    if any(not isinstance(value, str) or not value for value in columns.values()):
        raise ValueError("Mapped headers must be nonempty strings")
    if any(
        value is not None and type(value) not in {str, int, bool} for value in constants.values()
    ):
        raise ValueError("Constants must use explicit scalar values; decimals must be strings")
    if set(transforms) - set(columns):
        raise ValueError("Value maps require a mapped column")
    for table in transforms.values():
        if not isinstance(table, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in table.items()
        ):
            raise ValueError("Value maps must map strings to strings")
    return columns, constants, transforms


def normalize_statement(raw: bytes, *, account_id: str, observed_at: str, mapping: dict) -> dict:
    """Validate mapped rows and return safe normalized evidence without I/O effects."""
    columns, constants, transforms = _validate_mapping(mapping)
    if not isinstance(raw, bytes) or len(raw) > MAX_DOCUMENT_BYTES:
        raise ValueError("Statement must be UTF-8 bytes within 5 MiB")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("Statement must be UTF-8") from None
    try:
        reader = csv.reader(StringIO(text, newline=""), strict=True)
        headers = next(reader, [])
        if (
            not headers
            or any(not header for header in headers)
            or len(headers) != len(set(headers))
        ):
            raise ValueError("CSV requires unique nonempty headers")
        if set(columns.values()) - set(headers):
            raise ValueError("CSV is missing mapped columns")
        rows = list(reader)
        if any(len(row) != len(headers) for row in rows):
            raise ValueError("CSV row width does not match header")
    except csv.Error:
        raise ValueError("Invalid CSV document") from None
    document_hash = hashlib.sha256(raw).hexdigest()
    result = {
        "document_hash": document_hash,
        "mapping_hash": _hash(mapping),
        "schema_version": SCHEMA_VERSION,
        "coverage_verified": False,
        "events": [],
        "errors": [],
        "sources": [],
    }
    for number, values in enumerate(rows, start=1):
        row = dict(zip(headers, values))
        row_hash = _hash(row)
        source_key = f"{document_hash}:{number}"
        data = dict(constants)
        for field, header in columns.items():
            value = row[header]
            data[field] = transforms.get(field, {}).get(value, value)
        for field in OPTIONAL & data.keys():
            if data[field] == "":
                data[field] = None
        if isinstance(data.get("revision"), str) and re.fullmatch(r"[0-9]+", data["revision"]):
            data["revision"] = int(data["revision"])
        if data.get("settlement_confirmed") in ("true", "false"):
            data["settlement_confirmed"] = data["settlement_confirmed"] == "true"
        basis = "mapped" if "event_key" in data else "document_row"
        data.setdefault("event_key", source_key)
        data.setdefault("quality", "provisional")
        data.update(
            account_id=account_id,
            observed_at=observed_at,
            source_type="statement",
            source_key=source_key,
            source_record_hash=row_hash,
        )
        source = {
            "source_key": source_key,
            "payload_hash": row_hash,
            "payload": {},
            "row_number": number,
            "document_hash": document_hash,
            "event_key_basis": basis,
        }
        try:
            # Dates must already use the public contract, never guessed locale formats.
            for field in ("event_date", "settlement_date"):
                if data.get(field) is not None and (
                    not isinstance(data[field], str)
                    or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", data[field])
                ):
                    raise ValueError("Invalid date format")
            event = LedgerEvent.model_validate(data).model_dump(mode="json")
            source["payload"] = event.copy()
            result["events"].append(event)
        except (ValidationError, ValueError) as exc:
            fields = (
                sorted(
                    {
                        str(error["loc"][0])
                        for error in exc.errors()
                        if error["loc"] and error["loc"][0] in LedgerEvent.model_fields
                    }
                )
                if isinstance(exc, ValidationError)
                else ["event_date", "settlement_date"]
            )
            result["errors"].append({"row": number, "fields": fields, "reason": "invalid_event"})
        result["sources"].append(source)
    return result
