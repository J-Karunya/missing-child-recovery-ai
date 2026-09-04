"""Provider boundary for approved malware scanning; unavailable is fail-closed."""
from __future__ import annotations
from typing import Protocol

class UploadScanner(Protocol):
    def scan(self, content: bytes, filename: str) -> str: ...

class UnavailableScanner:
    def scan(self, content, filename): return "UNAVAILABLE"

class ClamAVScanner(UnavailableScanner):
    """Integration placeholder; deployment must inject an approved client."""

class UploadScanService:
    def __init__(self, scanner: UploadScanner | None = None): self.scanner=scanner or UnavailableScanner()
    def status(self, content, filename):
        result=self.scanner.scan(content,filename)
        return {"SCAN_UNAVAILABLE":"UNAVAILABLE","CLEAN":"CLEAN","REJECTED":"INFECTED","INFECTED":"INFECTED","UNAVAILABLE":"UNAVAILABLE","ERROR":"ERROR"}.get(result,"ERROR")
    def processable(self,content,filename): return self.status(content,filename)=="CLEAN"
