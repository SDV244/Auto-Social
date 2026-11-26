"""Hard monthly spend cap. Every paid call records an estimated cost here first."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, cap_usd: float, path: str | Path = ".budget.json"):
        self.cap = cap_usd
        self.path = Path(path)

    def _month(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())
        return {}

    def spent(self) -> float:
        return float(self._load().get(self._month(), 0.0))

    def charge(self, amount_usd: float, label: str = "") -> float:
        """Reserve `amount_usd`; raise BudgetExceeded instead of overspending."""
        if self.spent() + amount_usd > self.cap:
            raise BudgetExceeded(
                f"{label or 'charge'} of ${amount_usd:.2f} would exceed the "
                f"${self.cap:.2f} monthly cap (spent ${self.spent():.2f})"
            )
        data = self._load()
        data[self._month()] = round(self.spent() + amount_usd, 4)
        self.path.write_text(json.dumps(data, indent=2))
        return data[self._month()]


def openrouter_balance() -> float | None:
    """Remaining OpenRouter credits in USD (account total minus usage), or None if it cannot be read."""
    import os

    import httpx

    headers = {}
    if os.environ.get("OPENROUTER_API_KEY"):  # in the cloud sandbox the proxy injects the key
        headers["Authorization"] = f"Bearer {os.environ['OPENROUTER_API_KEY']}"
    try:
        d = httpx.get("https://openrouter.ai/api/v1/credits", headers=headers, timeout=20).json()["data"]
        return float(d["total_credits"]) - float(d["total_usage"])
    except Exception:
        return None
