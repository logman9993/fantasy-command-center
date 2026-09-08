"""Offline repository health checks used locally and in CI."""
from pathlib import Path
import ast, json

ROOT=Path(__file__).resolve().parent
for path in [ROOT/"app.py",ROOT/"fcc/application.py",ROOT/"fcc/cache.py",ROOT/"fcc/http.py",ROOT/"fcc/scoring.py"]:
    ast.parse(path.read_text(encoding="utf-8"),filename=str(path))
manifest=json.loads((ROOT/"espn-extension/manifest.json").read_text())
assert manifest["manifest_version"]==3
assert manifest["version"]=="0.2.6"
assert (ROOT/".github/workflows/checks.yml").exists()
assert (ROOT/"tests").exists()
print("SELF TEST PASS")
