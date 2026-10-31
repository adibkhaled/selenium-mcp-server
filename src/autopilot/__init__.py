"""
Selenium Autopilot
------------------
AI-powered Selenium test automation framework.

Provides:
- Browser automation
- AI-powered test generation
- Test planning
- Failure analysis and self-healing
- Diagnostics and reporting
- OpenAI-compatible LLM integration
"""

__version__ = "0.1.0"

# Environment configuration
from .config import load_environment

load_environment()

# Browser automation
from .browser import Autopilot, AutopilotConfig
from .locators import Locator
from .waits import AutopilotTimeoutError

# Diagnostics
from .diagnostics import DiagnosticsReport, capture_diagnostics

# Test generation
from .generation import (
    GeneratedProject,
    GenerationError,
    TestGenerator,
)

# Failure analysis and self-healing
from .healing import (
    FailureAnalysis,
    FailureAnalyzer,
    FailureCategory,
    FailureReport,
    HealingError,
    HealingProposal,
    propose_locator_healing,
)

# Test planning
from .planning import (
    PlanningError,
    TestPlan,
    TestPlanner,
    TestScenario,
)

# LLM providers
from .provider import (
    OpenAICompatibleProvider,
    ProviderError,
)

# Test reporting
from .reporting import (
    ReportError,
    TestFailure,
    TestResult,
    load_test_result,
    parse_junit_xml,
)


__all__ = [
    # Version
    "__version__",

    # Browser automation
    "Autopilot",
    "AutopilotConfig",
    "AutopilotTimeoutError",
    "Locator",

    # Diagnostics
    "DiagnosticsReport",
    "capture_diagnostics",

    # Test generation
    "GeneratedProject",
    "GenerationError",
    "TestGenerator",

    # Failure analysis and self-healing
    "FailureAnalysis",
    "FailureAnalyzer",
    "FailureCategory",
    "FailureReport",
    "HealingError",
    "HealingProposal",
    "propose_locator_healing",

    # Test planning
    "PlanningError",
    "TestPlan",
    "TestPlanner",
    "TestScenario",

    # LLM providers
    "OpenAICompatibleProvider",
    "ProviderError",

    # Reporting
    "ReportError",
    "TestFailure",
    "TestResult",
    "load_test_result",
    "parse_junit_xml",
]