from typing import Any, Iterable


def held_assets(assets: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return assets with a strictly positive position quantity."""
    held = []
    for asset in assets:
        try:
            quantity = float(asset.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if quantity > 0:
            held.append(asset)
    return held
