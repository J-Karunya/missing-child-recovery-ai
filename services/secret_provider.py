"""Injectable secret boundary."""
from __future__ import annotations
import os

class SecretProvider:
    def get_secret(self, name: str) -> str | None:
        raise NotImplementedError

    def require_secret(self, name: str) -> str:
        value = self.get_secret(name)
        if not value:
            raise RuntimeError(f"Required secret {name} is unavailable.")
        return value

class EnvironmentSecretProvider(SecretProvider):
    def get_secret(self, name: str) -> str | None:
        return os.getenv(name) or None
