"""Interface d'antivirus obligatoire pour tout stockage de document —
`StubScanner` (toujours "clean") est actif par defaut dans ce lot ;
`ClamAVScanner` est ecrit mais desactive (`settings.CLAMAV_ENABLED=False`)
tant que ClamAV n'est pas deploye. L'interface reste appelee
systematiquement dans `store_document()` : seule l'implementation change."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import IO, Literal

ScanStatus = Literal["clean", "infected", "error"]


@dataclass
class ScanResult:
    status: ScanStatus
    details: str = ""


class AntivirusScanner(ABC):
    @abstractmethod
    def scan(self, file: IO[bytes]) -> ScanResult: ...


class StubScanner(AntivirusScanner):
    def scan(self, file: IO[bytes]) -> ScanResult:
        return ScanResult(status="clean", details="stub — scan non exécuté")


class ClamAVScanner(AntivirusScanner):
    """Necessite un demon ClamAV accessible (host/port configurables) —
    non deploye dans ce lot. Ecrite pour que le branchement futur se
    limite a activer `CLAMAV_ENABLED` sans toucher a `store_document()`."""

    def __init__(self, host: str = "localhost", port: int = 3310) -> None:
        self.host = host
        self.port = port

    def scan(self, file: IO[bytes]) -> ScanResult:
        try:
            import clamd

            client = clamd.ClamdNetworkSocket(host=self.host, port=self.port)
            result = client.instream(file)
            status = result.get("stream", (None, None))[0]
            if status == "OK":
                return ScanResult(status="clean")
            return ScanResult(status="infected", details=str(result))
        except Exception as exc:  # noqa: BLE001 — degrade en erreur de scan, jamais un crash d'upload
            return ScanResult(status="error", details=str(exc))


def get_scanner() -> AntivirusScanner:
    from django.conf import settings

    if getattr(settings, "CLAMAV_ENABLED", False):
        return ClamAVScanner()
    return StubScanner()
