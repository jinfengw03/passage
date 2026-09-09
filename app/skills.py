from pathlib import Path
import yaml

DIRECTORY = Path(__file__).resolve().parent.parent / "skills"


def catalog():
    result = []
    for path in sorted(DIRECTORY.glob("*/SKILL.md")):
        _, header, body = path.read_text().split("---", 2)
        metadata = yaml.safe_load(header)
        result.append({"name": metadata["name"], "description": metadata["description"],
                       "body": body.strip()})
    return result


def load(name):
    for skill in catalog():
        if skill["name"] == name:
            return skill
    raise ValueError("未找到该 Skill")
