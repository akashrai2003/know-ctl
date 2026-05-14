from __future__ import annotations

import hashlib


def compute_input_hash(
    stage_name: str,
    input_ids: list[int],
    model_id: str,
    version: int,
) -> str:
    """Deterministic SHA-256 hash for stage checkpoint input fingerprint."""
    parts = [
        stage_name,
        ",".join(str(i) for i in sorted(input_ids)),
        model_id,
        str(version),
    ]
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
