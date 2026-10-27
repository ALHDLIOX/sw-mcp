"""CLI for repeatable SW engineering drawings; change JSON, not Python."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.drawing_recipe import load_recipe


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument(
        "--model", type=Path, help="Override sourceModel in the reusable recipe"
    )
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--version", type=int)
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    load_recipe(args.recipe)
    if args.validate_only:
        print("Recipe validation passed")
        return 0
    if args.out_dir is None:
        parser.error("--out-dir is required unless --validate-only is used")
    from scripts.native_drawing import generate_drawing

    result = generate_drawing(
        args.recipe, args.out_dir, source_model=args.model, version=args.version
    )
    print(
        json.dumps(
            {k: result.get(k) for k in ("status", "outputs", "error")},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
