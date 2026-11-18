"""Move the emulated_hue block of configuration.yaml into packages/alexa.yaml
and add the EnOcean Alexa names.

All existing emulated_hue settings and entities are kept; entries from the
names file are added (they win for the same entity_id). expose_by_default is
not changed. Without --apply nothing is written (dry run).

Usage (inside the Home Assistant container):
  python3 merge_emulated_hue.py /config emulated_hue_entities.yaml [--apply]
"""

from __future__ import annotations

import pathlib
import re
import shutil
import sys

import yaml


def split_block(text: str) -> tuple[str, str, str]:
    """Return (before, emulated_hue block, after) of configuration.yaml."""
    lines = text.splitlines(keepends=True)
    start = next(
        (i for i, line in enumerate(lines) if re.match(r"^emulated_hue:\s*(#.*)?$", line)),
        None,
    )
    if start is None:
        raise SystemExit("no top-level 'emulated_hue:' in configuration.yaml")
    end = start + 1
    while end < len(lines) and (
        lines[end].strip() == "" or lines[end].startswith((" ", "\t", "#"))
    ):
        end += 1
    # Trailing blank/comment lines belong to what follows.
    while end > start + 1 and (lines[end - 1].strip() == "" or lines[end - 1].startswith("#")):
        end -= 1
    return "".join(lines[:start]), "".join(lines[start:end]), "".join(lines[end:])


def main(argv: list[str]) -> int:
    config_dir = pathlib.Path(argv[1])
    names_file = pathlib.Path(argv[2])
    apply = "--apply" in argv[3:]

    configuration = config_dir / "configuration.yaml"
    package = config_dir / "packages" / "alexa.yaml"
    if package.exists():
        raise SystemExit(f"{package} exists already - nothing changed")

    before, block, after = split_block(configuration.read_text(encoding="utf-8"))
    current = yaml.safe_load(block)["emulated_hue"] or {}
    names = yaml.safe_load(names_file.read_text(encoding="utf-8"))

    entities = dict(current.get("entities") or {})
    kept = [e for e in entities if e not in names]
    entities.update(names)
    merged = {**current, "entities": entities}

    print("settings kept:", {k: v for k, v in current.items() if k != "entities"})
    print("expose_by_default:", current.get("expose_by_default", "not set (= true)"))
    print("entities before:", len(current.get("entities") or {}), "after:", len(entities))
    print("non-EnOcean entities kept:", kept)

    out = (
        "# Alexa via local Hue emulation. Moved from configuration.yaml by\n"
        "# tools/merge_emulated_hue.py; EnOcean names from\n"
        "# ha-config/alexa/emulated_hue_entities.yaml.\n"
        + yaml.safe_dump({"emulated_hue": merged}, allow_unicode=True, sort_keys=False)
    )
    if not apply:
        print("--- dry run, packages/alexa.yaml would be: ---")
        print(out)
        return 0

    backup = config_dir / "packages_archiv" / "configuration.yaml.bak-before-alexa"
    backup.parent.mkdir(exist_ok=True)
    shutil.copy2(configuration, backup)
    package.write_text(out, encoding="utf-8")
    configuration.write_text(before + after, encoding="utf-8")
    print(f"written {package}; removed block from {configuration}; backup {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
