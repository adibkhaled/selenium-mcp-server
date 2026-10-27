from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .generation import GenerationError, TestGenerator
from .planning import PlanningError, TestPlan, TestPlanner
from .provider import ProviderError, provider_from_environment


_MAX_INPUT_BYTES = 1_000_000


def _read_text(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Could not read UTF-8 input file {path}: {exc}") from exc
    if len(content.encode("utf-8")) > _MAX_INPUT_BYTES:
        raise ValueError(f"Input file exceeds the 1 MB limit: {path}")
    return content


def _write_plan(path: Path, plan: TestPlan, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Plan output already exists: {path}. Pass --overwrite after reviewing it."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(json.dumps(plan.to_dict(), indent=2) + "\n")
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autopilot",
        description="Plan and generate Selenium pytest tests from requirements.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    plan = commands.add_parser("plan", help="Create a structured JSON test plan.")
    plan.add_argument("--requirements", type=Path, required=True)
    plan.add_argument(
        "--source",
        type=Path,
        action="append",
        default=[],
        help="Relevant source file to provide as context; may be repeated.",
    )
    plan.add_argument("--output", type=Path, default=Path("artifacts/test-plan.json"))
    plan.add_argument("--overwrite", action="store_true")

    generate = commands.add_parser(
        "generate",
        help="Generate Selenium Page Objects and pytest tests from a reviewed plan.",
    )
    generate.add_argument("--plan", type=Path, required=True)
    generate.add_argument("--output", type=Path, default=Path("generated_tests"))
    generate.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace files in the generated project after reviewing existing output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        provider = provider_from_environment()
        if args.command == "plan":
            requirements = _read_text(args.requirements)
            source_files = {str(path): _read_text(path) for path in args.source}
            test_plan = TestPlanner(provider).create_plan(requirements, source_files)
            _write_plan(args.output, test_plan, args.overwrite)
            print(json.dumps({"plan": str(args.output), "scenario_count": len(test_plan.scenarios)}))
            return 0

        plan = TestPlan.from_dict(json.loads(_read_text(args.plan)))
        generated = TestGenerator(provider).generate(
            plan,
            args.output,
            overwrite=args.overwrite,
        )
        print(
            json.dumps(
                {
                    "output_dir": str(generated.output_dir),
                    "files": [str(path) for path in generated.files],
                    "notes": list(generated.notes),
                    "review_required": True,
                },
                indent=2,
            )
        )
        return 0
    except (
        FileExistsError,
        GenerationError,
        PlanningError,
        ProviderError,
        ValueError,
        OSError,
        json.JSONDecodeError,
    ) as exc:
        print(f"autopilot: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
