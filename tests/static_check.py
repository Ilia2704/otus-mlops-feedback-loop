from pathlib import Path
import ast
import json
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRECTORIES = {".git", ".venv", "__pycache__", ".pytest_cache"}


def project_files(pattern: str):
    for path in ROOT.rglob(pattern):
        if not any(part in IGNORED_DIRECTORIES for part in path.relative_to(ROOT).parts):
            yield path

# 1. Every Python file parses.
for path in project_files("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

# 2. Every YAML document parses.
for path in project_files("*.yaml"):
    list(yaml.safe_load_all(path.read_text(encoding="utf-8")))

# 3. Grafana JSON embedded in ConfigMap parses.
dashboard = yaml.safe_load((ROOT / "infra/k8s/01_monitoring/grafana-dashboard.yaml").read_text())
json.loads(dashboard["data"]["titanic.json"])

# 4. Root lecture READMEs have slide, goal, architecture and launch section.
for name in [
    "README_01_MONITORING.md",
    "README_02_DATA_DRIFT.md",
    "README_03_FEEDBACK_LOOP.md",
    "README_04_ALERTING.md",
]:
    text = (ROOT / name).read_text(encoding="utf-8")
    for token in ["Цель", "Архитектура", "Слайд", "Запуск"]:
        assert token in text, (name, token)
    for image in re.findall(r"!\[[^]]*\]\(([^)]+)\)", text):
        assert (ROOT / image).exists(), (name, image)

print("static checks: OK")
