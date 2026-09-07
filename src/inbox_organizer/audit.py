from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import PlannedOperation


def append_audit(path: str | Path, provider: str, operation: PlannedOperation, status: str) -> None:
    """Audit metadata only; subjects and bodies are intentionally excluded."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "message_id_sha256": hashlib.sha256(operation.provider_id.encode()).hexdigest(),
        "category": operation.category.value,
        "confidence": operation.confidence,
        "action": operation.action.value,
        "destination": operation.destination,
        "status": status,
    }
    with target.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")

