"""Generation d'identifiants UUIDv7 (RFC 9562) — cles primaires normatives
de toute entite du socle, jamais d'auto-increment expose."""

from __future__ import annotations

import uuid

from uuid6 import uuid7 as _uuid7


def uuid7() -> uuid.UUID:
    return _uuid7()
