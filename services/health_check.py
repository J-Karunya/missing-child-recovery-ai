"""Safe operational checks; never exposes secrets or data."""
from __future__ import annotations
try:
    from .config import DATABASE_PATH, ALERTS_DIR, configuration_check, ENVIRONMENT_MODE
    from .review_store import ReviewStore
except ImportError:
    from config import DATABASE_PATH, ALERTS_DIR, configuration_check, ENVIRONMENT_MODE
    from review_store import ReviewStore

def check():
    results={"database":"FAIL","evidence_directory":"FAIL", "configuration":"FAIL"}
    try:
        store=ReviewStore(DATABASE_PATH); store.initialize(); results["database"]="OK"
    except Exception:
        pass
    config = configuration_check()
    allowed = {"OK"} if ENVIRONMENT_MODE in {"STAGING", "PRODUCTION"} else {"OK", "MISSING"}
    results["configuration"] = "OK" if all(value in allowed for value in config.values()) else "FAIL"
    try:
        ALERTS_DIR.mkdir(parents=True,exist_ok=True); results["evidence_directory"]="OK"
    except Exception:
        pass
    return results

if __name__=="__main__":
    outcome=check()
    print(" ".join(f"{k}={v}" for k,v in outcome.items()))
    raise SystemExit(0 if all(v=="OK" for v in outcome.values()) else 1)
