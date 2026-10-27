from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver


@dataclass(frozen=True)
class DiagnosticsReport:
    screenshot: str | None
    dom_snapshot: str | None
    metadata: str | None
    errors: tuple[str, ...]


def capture_diagnostics(
    driver: WebDriver,
    output_dir: str | Path,
    failed_action: str | None = None,
) -> DiagnosticsReport:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = f"failure-{timestamp}-{uuid4().hex[:8]}"
    paths = {
        "screenshot": directory / f"{prefix}.png",
        "dom_snapshot": directory / f"{prefix}.html",
        "metadata": directory / f"{prefix}.json",
    }
    errors: list[str] = []
    screenshot: str | None = None
    dom_snapshot: str | None = None

    try:
        if driver.save_screenshot(str(paths["screenshot"])):
            screenshot = str(paths["screenshot"])
        else:
            errors.append("WebDriver did not save the screenshot.")
    except WebDriverException as exc:
        errors.append(f"Screenshot failed ({type(exc).__name__}): {exc}")

    try:
        paths["dom_snapshot"].write_text(driver.page_source, encoding="utf-8")
        dom_snapshot = str(paths["dom_snapshot"])
    except (OSError, WebDriverException) as exc:
        errors.append(f"DOM snapshot failed ({type(exc).__name__}): {exc}")

    capabilities: dict[str, Any] = getattr(driver, "capabilities", {}) or {}
    metadata = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "browser": capabilities.get("browserName", "unknown"),
        "browser_version": capabilities.get("browserVersion"),
        "url": _read_driver_value(driver, "current_url", errors),
        "title": _read_driver_value(driver, "title", errors),
        "failed_action": failed_action,
        "errors": errors,
    }
    try:
        paths["metadata"].write_text(
            json.dumps(metadata, indent=2, default=str),
            encoding="utf-8",
        )
        metadata_path: str | None = str(paths["metadata"])
    except OSError as exc:
        errors.append(f"Metadata write failed ({type(exc).__name__}): {exc}")
        metadata_path = None

    return DiagnosticsReport(screenshot, dom_snapshot, metadata_path, tuple(errors))


def _read_driver_value(driver: WebDriver, name: str, errors: list[str]) -> Any:
    try:
        return getattr(driver, name)
    except WebDriverException as exc:
        errors.append(f"Could not read {name} ({type(exc).__name__}): {exc}")
        return None
