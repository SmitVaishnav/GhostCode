"""Pre-Send Risk Report.

Analyzes ghost output to produce a risk assessment before the developer
sends code to an LLM. Shows what's protected, what's exposed, and how
much domain context the LLM can still infer.

The report answers the developer's key question:
    "Is this safe enough to paste into ChatGPT?"
"""

import re
from dataclasses import dataclass, field
from enum import Enum

import click

from .mapping.ghost_map import GhostMap
from .transformers.literal_scrubber import ScrubResult


class ExposureLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


# ── Structural Pattern Detectors ────────────────────────────────────
# Each detector is (pattern_name, regex, description).
# These run against the ghost source to identify algorithmic patterns
# that remain visible even after symbol renaming.

STRUCTURAL_PATTERNS = [
    (
        "matrix_operation",
        re.compile(r"\[.*?\]\s*\[.*?\]", re.MULTILINE),
        "matrix/2D array indexing",
    ),
    (
        "exponential_decay",
        re.compile(r"\bexp\s*\(", re.MULTILINE),
        "exponential function (exp)",
    ),
    (
        "sorting",
        re.compile(r"\b(sort|sorted|std::sort|qsort)\s*\(", re.MULTILINE),
        "sorting operation",
    ),
    (
        "recursion",
        re.compile(
            r"def\s+(\w+)\s*\([^)]*\).*?\n(?:.*?\n)*?.*?\b\1\s*\(",
            re.MULTILINE,
        ),
        "recursive function",
    ),
    (
        "loop_iteration",
        re.compile(
            r"\b(for|while)\s*[\(:]|\bfor\s+\w+\s+in\b",
            re.MULTILINE,
        ),
        "loop iteration",
    ),
    (
        "file_io",
        re.compile(
            r"\b(fopen|fread|fwrite|open|read|write|ifstream|ofstream)\s*\(",
            re.MULTILINE,
        ),
        "file I/O operations",
    ),
    (
        "network_io",
        re.compile(
            r"\b(socket|connect|send|recv|requests\.\w+|urllib|httpx|aiohttp)\s*[\(.]",
            re.MULTILINE,
        ),
        "network I/O",
    ),
    (
        "crypto",
        re.compile(
            r"\b(sha256|sha512|md5|hmac|encrypt|decrypt|AES|RSA|hashlib)\b",
            re.MULTILINE | re.IGNORECASE,
        ),
        "cryptographic operations",
    ),
    (
        "ml_training",
        re.compile(
            r"\b(backward|gradient|loss|optimizer|train|epoch|batch_size)\b",
            re.MULTILINE,
        ),
        "ML training loop",
    ),
    (
        "database",
        re.compile(
            r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|cursor|execute|commit)\b",
            re.MULTILINE,
        ),
        "database operations",
    ),
    (
        "threshold_check",
        re.compile(
            r"if\s*\(?\s*\w+\s*[<>]=?\s*\w+",
            re.MULTILINE,
        ),
        "threshold/boundary check",
    ),
]


@dataclass
class RiskReport:
    """Structured risk assessment of a ghost hide operation."""

    # Privacy config
    privacy_level: int = 1
    file_count: int = 1

    # Symbol breakdown
    total_symbols: int = 0
    variables_count: int = 0
    functions_count: int = 0
    types_count: int = 0
    constants_count: int = 0
    strings_count: int = 0
    macros_count: int = 0

    # Literal stats
    literals_scrubbed: int = 0
    literals_flagged: int = 0
    literals_kept: int = 0

    # Comments
    comments_handled: int = 0
    comments_mode: str = "stripped"  # "stripped" or "anonymized"

    # Isolation
    function_isolated: bool = False
    isolated_function: str = ""

    # Structural analysis
    patterns_detected: list[str] = field(default_factory=list)

    # Risk assessment
    exposure_level: ExposureLevel = ExposureLevel.LOW
    exposure_reasons: list[str] = field(default_factory=list)

    # Warnings
    warnings_count: int = 0

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dict for VS Code extension."""
        return {
            "privacy_level": self.privacy_level,
            "file_count": self.file_count,
            "total_symbols": self.total_symbols,
            "symbols_by_kind": {
                "variables": self.variables_count,
                "functions": self.functions_count,
                "types": self.types_count,
                "constants": self.constants_count,
                "strings": self.strings_count,
                "macros": self.macros_count,
            },
            "literals": {
                "scrubbed": self.literals_scrubbed,
                "flagged": self.literals_flagged,
                "kept": self.literals_kept,
            },
            "comments": {
                "count": self.comments_handled,
                "mode": self.comments_mode,
            },
            "function_isolated": self.function_isolated,
            "isolated_function": self.isolated_function,
            "patterns_detected": self.patterns_detected,
            "exposure_level": self.exposure_level.value,
            "exposure_reasons": self.exposure_reasons,
            "warnings_count": self.warnings_count,
        }


# Mapping from symbol kind to the report field
_KIND_FIELD_MAP = {
    "variable": "variables_count",
    "parameter": "variables_count",
    "field": "variables_count",
    "function": "functions_count",
    "method": "functions_count",
    "class": "types_count",
    "struct": "types_count",
    "enum": "types_count",
    "typedef": "types_count",
    "type_alias": "types_count",
    "constant": "constants_count",
    "string": "strings_count",
    "macro": "macros_count",
    "namespace": "variables_count",
}


class RiskAnalyzer:
    """Builds a RiskReport from the data produced by the hide pipeline."""

    def analyze(
        self,
        ghost_map: GhostMap,
        ghost_source: str,
        level: int,
        comment_count: int = 0,
        keep_comments: bool = False,
        scrub_result: ScrubResult | None = None,
        function_isolated: str | None = None,
        dim_count: int = 0,
        file_count: int = 1,
    ) -> RiskReport:
        """Analyze the hide result and produce a risk report.

        Args:
            ghost_map: The completed ghost map with all symbols.
            ghost_source: The ghost output source code.
            level: Privacy level used (1-4).
            comment_count: Number of comments stripped/anonymized.
            keep_comments: Whether comments were anonymized vs stripped.
            scrub_result: Literal scrubbing result (level 2+).
            function_isolated: Name of isolated function (level 3+).
            dim_count: Number of dimensions generalized (level 4).
            file_count: Number of files processed.

        Returns:
            RiskReport with full analysis.
        """
        report = RiskReport(
            privacy_level=level,
            file_count=file_count,
        )

        # ── Symbol breakdown ──────────────────────────────────────
        report.total_symbols = ghost_map.symbol_count
        for entry in ghost_map._entries.values():
            field_name = _KIND_FIELD_MAP.get(entry.kind, "variables_count")
            current = getattr(report, field_name)
            setattr(report, field_name, current + 1)

        # ── Literal stats ─────────────────────────────────────────
        if scrub_result:
            report.literals_scrubbed = len(scrub_result.scrubbed)
            report.literals_flagged = len(scrub_result.flagged)
            report.literals_kept = len(scrub_result.kept)

        # ── Comments ──────────────────────────────────────────────
        report.comments_handled = comment_count
        report.comments_mode = "anonymized" if keep_comments else "stripped"

        # ── Isolation ─────────────────────────────────────────────
        if function_isolated:
            report.function_isolated = True
            report.isolated_function = function_isolated

        # ── Structural pattern detection ──────────────────────────
        report.patterns_detected = self._detect_patterns(ghost_source)

        # ── Warnings ──────────────────────────────────────────────
        report.warnings_count = len(ghost_map.warnings)

        # ── Domain exposure assessment ────────────────────────────
        report.exposure_level, report.exposure_reasons = (
            self._assess_exposure(report)
        )

        return report

    def _detect_patterns(self, ghost_source: str) -> list[str]:
        """Detect structural/algorithmic patterns in ghost source."""
        detected = []
        for name, pattern, description in STRUCTURAL_PATTERNS:
            if pattern.search(ghost_source):
                detected.append(description)
        return detected

    def _assess_exposure(
        self, report: RiskReport
    ) -> tuple[ExposureLevel, list[str]]:
        """Compute domain exposure level with explanations."""
        reasons: list[str] = []
        score = 0  # Higher = more exposed

        # Level 1 means no literal scrubbing — strings leak domain
        if report.privacy_level == 1:
            score += 3
            reasons.append("Level 1: string literals not scrubbed")

        # Flagged literals are developer-reviewable but still present
        if report.literals_flagged > 5:
            score += 2
            reasons.append(
                f"{report.literals_flagged} literals flagged for review "
                f"(still present in ghost output)"
            )
        elif report.literals_flagged > 0:
            score += 1
            reasons.append(
                f"{report.literals_flagged} literal(s) flagged for review"
            )

        # No function isolation at level 3+ means full file visible
        if report.privacy_level >= 3 and not report.function_isolated:
            score += 1
            reasons.append(
                "Level 3+ but no function isolation — full file structure visible"
            )

        # Many structural patterns compound to reveal the domain
        pattern_count = len(report.patterns_detected)
        if pattern_count >= 4:
            score += 2
            reasons.append(
                f"{pattern_count} structural patterns visible — "
                f"pattern co-occurrence may narrow domain"
            )
        elif pattern_count >= 2:
            score += 1
            reasons.append(
                f"{pattern_count} structural patterns visible"
            )

        # Warnings indicate potential leaks
        if report.warnings_count > 0:
            score += 1
            reasons.append(
                f"{report.warnings_count} warning(s) from parser"
            )

        # Classify
        if score >= 4:
            return ExposureLevel.HIGH, reasons
        elif score >= 2:
            return ExposureLevel.MEDIUM, reasons
        else:
            if not reasons:
                reasons.append("All symbols and literals scrubbed")
            return ExposureLevel.LOW, reasons


def format_risk_report_cli(report: RiskReport) -> str:
    """Format a RiskReport as a styled CLI output string.

    Returns a string that can be printed with click.echo().
    """
    lines: list[str] = []

    # Exposure color
    color_map = {
        ExposureLevel.LOW: "green",
        ExposureLevel.MEDIUM: "yellow",
        ExposureLevel.HIGH: "red",
    }
    exposure_color = color_map[report.exposure_level]

    # Box header
    lines.append("")
    lines.append(click.style("  ═══ GhostCode Risk Report ═══", fg="cyan", bold=True))
    lines.append("")

    # Core stats
    lines.append(
        f"  {click.style('Privacy Level:', bold=True):30s} "
        f"{report.privacy_level}"
    )
    if report.file_count > 1:
        lines.append(
            f"  {click.style('Files:', bold=True):30s} "
            f"{report.file_count}"
        )
    lines.append(
        f"  {click.style('Symbols scrubbed:', bold=True):30s} "
        f"{report.total_symbols}"
    )

    # Symbol breakdown
    breakdown_parts = []
    if report.variables_count:
        breakdown_parts.append(f"{report.variables_count} vars")
    if report.functions_count:
        breakdown_parts.append(f"{report.functions_count} funcs")
    if report.types_count:
        breakdown_parts.append(f"{report.types_count} types")
    if report.constants_count:
        breakdown_parts.append(f"{report.constants_count} consts")
    if report.strings_count:
        breakdown_parts.append(f"{report.strings_count} strings")
    if report.macros_count:
        breakdown_parts.append(f"{report.macros_count} macros")
    if breakdown_parts:
        lines.append(
            f"  {click.style('  Breakdown:', bold=False):30s} "
            f"{', '.join(breakdown_parts)}"
        )

    # Literals
    if report.privacy_level >= 2:
        lines.append(
            f"  {click.style('Literals scrubbed:', bold=True):30s} "
            f"{report.literals_scrubbed}"
        )
        if report.literals_flagged > 0:
            lines.append(
                f"  {click.style('Literals flagged:', bold=True):30s} "
                f"{click.style(str(report.literals_flagged), fg='yellow')}"
                f" ← developer must decide"
            )
        lines.append(
            f"  {click.style('Literals kept:', bold=True):30s} "
            f"{report.literals_kept}"
        )

    # Comments
    lines.append(
        f"  {click.style(f'Comments {report.comments_mode}:', bold=True):30s} "
        f"{report.comments_handled}"
    )

    # Isolation
    if report.function_isolated:
        lines.append(
            f"  {click.style('Function isolated:', bold=True):30s} "
            f"{report.isolated_function}"
        )

    # Structural patterns
    if report.patterns_detected:
        lines.append("")
        lines.append(
            f"  {click.style('Structural patterns visible:', bold=True)}"
        )
        for pattern in report.patterns_detected:
            lines.append(f"    • {pattern}")

    # Domain exposure
    lines.append("")
    exposure_text = click.style(
        report.exposure_level.value, fg=exposure_color, bold=True
    )
    lines.append(
        f"  {click.style('Estimated domain exposure:', bold=True):30s} "
        f"{exposure_text}"
    )
    for reason in report.exposure_reasons:
        lines.append(
            f"    {click.style('→', fg=exposure_color)} {reason}"
        )

    # Warnings
    if report.warnings_count > 0:
        lines.append(
            f"  {click.style('Warnings:', bold=True):30s} "
            f"{click.style(str(report.warnings_count), fg='yellow')}"
        )

    lines.append("")
    lines.append(click.style("  ═══════════════════════════════", fg="cyan", bold=True))

    return "\n".join(lines)
