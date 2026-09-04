"""Static guardrail for project-owned files, not a security certification."""
from __future__ import annotations
import re
from pathlib import Path

SKIP={".venv","venv","__pycache__","build","dist","node_modules","data","models","tests"}
PATTERNS=(re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), re.compile(r"(?:api[_-]?key|secret|password)\s*=\s*['\"][^'\"]{12,}['\"]",re.I))

def project_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and not any(part in SKIP for part in path.parts):
            yield path

def findings(root: Path) -> list[str]:
    result=[]
    ignored=(root/".gitignore").read_text(encoding="utf-8") if (root/".gitignore").is_file() else ""
    if ".env" not in ignored: result.append(".env is not ignored")
    for path in project_files(root):
        if path == Path(__file__) or path.suffix not in {".py",".md",".example",".yml",".yaml",".conf"}: continue
        text=path.read_text(encoding="utf-8",errors="ignore")
        if "use_container_width" in text: result.append(f"deprecated Streamlit API: {path.relative_to(root)}")
        normalized = "\n".join(line for line in text.lower().splitlines() if not any(marker in line for marker in ("your-key", "choose-a-unique-password", "development-only-password")))
        if any(pattern.search(normalized) for pattern in PATTERNS): result.append(f"credential-like literal: {path.relative_to(root)}")
    return result

def main() -> int:
    root=Path(__file__).resolve().parents[1]; result=findings(root)
    print("SECURITY CHECK " + ("OK" if not result else "FINDINGS"))
    for item in result: print("- " + item)
    return 0 if not result else 1

if __name__=="__main__": raise SystemExit(main())
