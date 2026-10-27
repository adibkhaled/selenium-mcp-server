from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .generation import GenerationError, TestGenerator
from .healing import FailureAnalysis, FailureAnalyzer, FailureReport, HealingError, propose_locator_healing
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


def _write_json(path: Path, value: dict[str, object], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"Output already exists: {path}. Pass --overwrite after reviewing it."
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
            temporary.write(json.dumps(value, indent=2) + "\n")
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _read_failure_report(path: Path) -> FailureReport:
    try:
        value = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failure report is not valid JSON: {exc.msg}") from exc
    return FailureReport.from_dict(value)


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

    analyze = commands.add_parser(
        "analyze",
        help="Classify a Selenium failure report and save structured analysis.",
    )
    analyze.add_argument("--report", type=Path, required=True)
    analyze.add_argument("--output", type=Path, default=Path("artifacts/failure-analysis.json"))
    analyze.add_argument("--overwrite", action="store_true")

    heal = commands.add_parser(
        "heal",
        help="Create a human-reviewed locator repair proposal from failure evidence.",
    )
    heal.add_argument("--report", type=Path, required=True)
    heal.add_argument("--source", type=Path, required=True)
    heal.add_argument("--output", type=Path, default=Path("artifacts/healing-proposal.json"))
    heal.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            requirements = _read_text(args.requirements)
            source_files = {str(path): _read_text(path) for path in args.source}
            test_plan = TestPlanner(provider_from_environment()).create_plan(
                requirements,
                source_files,
            )
            _write_plan(args.output, test_plan, args.overwrite)
            print(json.dumps({"plan": str(args.output), "scenario_count": len(test_plan.scenarios)}))
            return 0

        if args.command == "analyze":
            report = _read_failure_report(args.report)
            analysis = FailureAnalyzer().analyze(report)
            _write_json(args.output, analysis.to_dict(), args.overwrite)
            print(json.dumps({"analysis": str(args.output), **analysis.to_dict()}))
            return 0

        if args.command == "heal":
            report = _read_failure_report(args.report)
            proposal = propose_locator_healing(
                report,
                args.source,
                provider_from_environment(),
            )
            result = proposal.to_dict()
            _write_json(args.output, result, args.overwrite)
            print(
                json.dumps(
                    {
                        "proposal": str(args.output),
                        "human_review_required": True,
                        "applied": False,
                        "uniqueness": proposal.uniqueness,
                        "validation": proposal.validation,
                    }
                )
            )
            return 0

        plan = TestPlan.from_dict(json.loads(_read_text(args.plan)))
        generated = TestGenerator(provider_from_environment()).generate(
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
        HealingError,
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
