"""Load PC Kite settings without BOM errors or interpolation of token values."""

from pathlib import Path

from dotenv import dotenv_values

FIELDS = ("KITE_API_KEY", "KITE_API_SECRET", "KITE_ACCESS_TOKEN")


def load_pc_kite_credentials(root: Path) -> dict[str, str]:
    values = dotenv_values(
        root / "private" / "kite.env", encoding="utf-8-sig", interpolate=False
    )
    return {
        name: values[name].strip()
        for name in FIELDS
        if isinstance(values.get(name), str) and values[name].strip()
    }
