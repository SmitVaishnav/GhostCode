"""Smart literal scrubber.

Classifies every literal in source code by IP risk level and scrubs
accordingly. Not a binary scrub/keep — uses a three-bucket system:

    SCRUB   → replaced with gc_XXX / gs_XXX, stored in map
    KEEP    → left as-is, zero security value in scrubbing
    FLAG    → left as-is but reported to developer for review

Classification categories:
    Category 1 — Domain Fingerprints (ALWAYS scrub):
        Business strings, file paths, URLs, error messages, log strings
    Category 2 — Structural Constants (SELECTIVELY scrub):
        Matrix dimensions, buffer sizes, iteration bounds
    Category 3 — Algorithmic Constants (CONTEXT-DEPENDENT):
        Magic numbers, learning rates, physics constants
    Category 4 — Truly Generic (NEVER scrub):
        0, 1, -1, nullptr, true, false, empty string
"""

import math
import re
from dataclasses import dataclass, field
from enum import Enum

from ..mapping.ghost_map import GhostMap


class ScrubAction(Enum):
    SCRUB = "scrub"
    KEEP = "keep"
    FLAG = "flag"


@dataclass
class LiteralInfo:
    """A literal found in source code with classification."""
    value: str
    kind: str  # "string", "number", "char"
    offset: int
    end_offset: int
    line: int
    action: ScrubAction = ScrubAction.KEEP
    reason: str = ""
    context: str = ""  # "printf", "arithmetic", "loop_bound", "assignment", etc.
    ghost_token: str = ""


@dataclass
class ScrubResult:
    """Result of literal scrubbing."""
    source: str
    scrubbed: list[LiteralInfo] = field(default_factory=list)
    kept: list[LiteralInfo] = field(default_factory=list)
    flagged: list[LiteralInfo] = field(default_factory=list)


# Well-known mathematical constants (value → name)
KNOWN_MATH_CONSTANTS = {
    3.14159: "pi",
    3.141592653589793: "pi",
    2.71828: "e",
    2.718281828459045: "e",
    1.4142135623730951: "sqrt2",
    0.6931471805599453: "ln2",
    1.6180339887498949: "phi",
    6.283185307179586: "2pi",
}

# Domain indicator patterns in strings
DOMAIN_INDICATORS = re.compile(
    r"(/|\\\\|\.com|\.org|\.net|\.io|_id|_key|_token|_secret|"
    r"_password|_auth|api/|http|ftp://|\.json|\.xml|\.csv|\.dat|"
    r"@|\.conf|\.cfg|\.env)",
    re.IGNORECASE,
)

# Printf/log function names
PRINT_FUNCTIONS = {
    "printf", "fprintf", "sprintf", "snprintf", "syslog",
    "LOG", "LOG_ERROR", "LOG_WARNING", "LOG_INFO", "LOG_DEBUG",
    "cout", "cerr", "clog", "print", "println", "logging",
    "logger", "log", "warn", "error", "info", "debug",
}

# Generic integers that are never worth scrubbing
GENERIC_INTEGERS = {0, 1, -1, 2, -2}

# Known format specifier pattern
FORMAT_SPEC_PATTERN = re.compile(r"%[-+0 #]*\d*\.?\d*[diouxXeEfFgGaAcspn%]")


def _is_close_to_known_constant(value: float) -> str | None:
    """Check if a float is close to a known math constant."""
    for const_val, name in KNOWN_MATH_CONSTANTS.items():
        if abs(value - const_val) < 1e-6:
            return name
    return None


class LiteralScrubber:
    """Smart literal classifier and scrubber.

    Analyzes each literal's value, type, and surrounding context to
    determine whether it should be scrubbed, kept, or flagged.
    """

    def __init__(self, ghost_map: GhostMap):
        self._map = ghost_map
        self._symbol_names: set[str] = set()

    def set_known_symbols(self, names: set[str]):
        """Set known symbol names for string correlation detection."""
        self._symbol_names = names

    def scrub(self, source: str, file_path: str = "") -> ScrubResult:
        """Find and classify all literals in source code.

        Args:
            source: The source code (already symbol-renamed).
            file_path: Original file path for context.

        Returns:
            ScrubResult with transformed source and classification lists.
        """
        literals = self._extract_literals(source)
        self._classify_all(literals, source)

        result = ScrubResult(source=source)

        # Separate by action
        to_scrub = []
        for lit in literals:
            if lit.action == ScrubAction.SCRUB:
                result.scrubbed.append(lit)
                to_scrub.append(lit)
            elif lit.action == ScrubAction.FLAG:
                result.flagged.append(lit)
            else:
                result.kept.append(lit)

        # Apply scrubbing (end to start to preserve offsets)
        transformed = source
        to_scrub.sort(key=lambda l: l.offset, reverse=True)

        for lit in to_scrub:
            if lit.kind == "string":
                # Store unquoted value in map so reveal doesn't double-quote
                unquoted = lit.value.strip('"')
                token = self._map.add_symbol(
                    original=unquoted, kind="string",
                    source_file=file_path,
                )
                lit.ghost_token = token

                replacement = f'"{token}"'
            else:
                token = self._map.add_symbol(
                    original=lit.value, kind="constant",
                    source_file=file_path,
                )
                lit.ghost_token = token
                replacement = token

            transformed = (
                transformed[:lit.offset] + replacement + transformed[lit.end_offset:]
            )

        result.source = transformed
        return result

    def _extract_literals(self, source: str) -> list[LiteralInfo]:
        """Extract all string and numeric literals from source."""
        literals = []

        # String literals (double-quoted)
        for match in re.finditer(r'"([^"\\]|\\.)*"', source):
            literals.append(LiteralInfo(
                value=match.group(),
                kind="string",
                offset=match.start(),
                end_offset=match.end(),
                line=source[:match.start()].count("\n") + 1,
            ))

        # Numeric literals (int and float, including hex)
        # Match hex first, then float, then int
        num_pattern = re.compile(
            r"\b(0[xX][0-9a-fA-F]+[uUlL]*"  # hex
            r"|[0-9]+\.[0-9]*(?:[eE][+-]?[0-9]+)?[fFlL]*"  # float
            r"|[0-9]*\.[0-9]+(?:[eE][+-]?[0-9]+)?[fFlL]*"  # float (.5)
            r"|[0-9]+[eE][+-]?[0-9]+[fFlL]*"  # scientific
            r"|[0-9]+[uUlL]*"  # integer
            r")\b"
        )
        for match in num_pattern.finditer(source):
            # Skip if inside a string
            if self._is_inside_string(source, match.start()):
                continue
            # Skip if part of an identifier (e.g., gv_001)
            before_char = source[match.start() - 1] if match.start() > 0 else " "
            if before_char == "_":
                continue

            literals.append(LiteralInfo(
                value=match.group(),
                kind="number",
                offset=match.start(),
                end_offset=match.end(),
                line=source[:match.start()].count("\n") + 1,
            ))

        return literals

    def _classify_all(self, literals: list[LiteralInfo], source: str):
        """Classify each literal into SCRUB/KEEP/FLAG."""
        for lit in literals:
            if lit.kind == "string":
                self._classify_string(lit, source)
            else:
                self._classify_number(lit, source)

    def _classify_string(self, lit: LiteralInfo, source: str):
        """Classify a string literal."""
        value = lit.value.strip('"')

        # Empty or single char → KEEP
        if len(value) <= 1:
            lit.action = ScrubAction.KEEP
            lit.reason = "trivial string"
            return

        # Check if inside a #include → KEEP (handled by preprocessor)
        line_start = source.rfind("\n", 0, lit.offset) + 1
        line = source[line_start:source.find("\n", lit.offset)].strip()
        if line.startswith("#include"):
            lit.action = ScrubAction.KEEP
            lit.reason = "include directive"
            return

        # Check context: is this in a print/log call?
        lit.context = self._get_string_context(source, lit.offset)

        # Domain indicators → SCRUB
        if DOMAIN_INDICATORS.search(value):
            lit.action = ScrubAction.SCRUB
            lit.reason = "domain indicator detected"
            return

        # String correlation: matches a known symbol name
        for sym_name in self._symbol_names:
            if len(sym_name) > 2 and sym_name in value:
                lit.action = ScrubAction.SCRUB
                lit.reason = f"contains symbol name '{sym_name}'"
                return

        # Print/log context → SCRUB (these describe business logic)
        if lit.context == "printf":
            lit.action = ScrubAction.SCRUB
            lit.reason = "log/print string (business context)"
            return

        # Long descriptive strings (>20 chars) are likely business context
        if len(value) > 20:
            lit.action = ScrubAction.SCRUB
            lit.reason = "long descriptive string"
            return

        # Medium strings → FLAG for developer review
        if len(value) > 5:
            lit.action = ScrubAction.FLAG
            lit.reason = "medium-length string (review recommended)"
            return

        # Short non-trivial strings → KEEP
        lit.action = ScrubAction.KEEP
        lit.reason = "short string"

    def _classify_number(self, lit: LiteralInfo, source: str):
        """Classify a numeric literal."""
        raw = lit.value.rstrip("fFlLuU")

        # Parse the numeric value
        try:
            if raw.startswith("0x") or raw.startswith("0X"):
                num_val = int(raw, 16)
            elif "." in raw or "e" in raw.lower():
                num_val = float(raw)
            else:
                num_val = int(raw)
        except ValueError:
            lit.action = ScrubAction.KEEP
            lit.reason = "unparseable literal"
            return

        # Generic integers → KEEP
        if isinstance(num_val, int) and num_val in GENERIC_INTEGERS:
            lit.action = ScrubAction.KEEP
            lit.reason = "generic integer"
            return

        # Known math constants → KEEP
        if isinstance(num_val, float):
            const_name = _is_close_to_known_constant(num_val)
            if const_name:
                lit.action = ScrubAction.KEEP
                lit.reason = f"known constant ({const_name})"
                return

        # Common float literals used as defaults → KEEP
        if isinstance(num_val, float) and num_val in (0.0, 1.0, -1.0, 0.5, 2.0):
            lit.action = ScrubAction.KEEP
            lit.reason = "common float default"
            return

        # Determine context
        lit.context = self._get_number_context(source, lit.offset)

        # Hex literals with no common meaning → SCRUB (likely domain-specific)
        if isinstance(num_val, int) and (raw.startswith("0x") or raw.startswith("0X")):
            lit.action = ScrubAction.SCRUB
            lit.reason = "hex literal (potentially domain-specific)"
            return

        # Large integers (> 100) → FLAG
        if isinstance(num_val, int) and abs(num_val) > 100:
            lit.action = ScrubAction.FLAG
            lit.reason = "large integer (review recommended)"
            lit.context = lit.context or "unknown"
            return

        # Small-medium integers (3-100) in loop bounds → FLAG
        if isinstance(num_val, int) and 3 <= abs(num_val) <= 100:
            if lit.context == "loop_bound":
                lit.action = ScrubAction.FLAG
                lit.reason = "loop bound dimension"
            else:
                lit.action = ScrubAction.KEEP
                lit.reason = "small integer"
            return

        # Non-trivial floats → FLAG
        if isinstance(num_val, float) and num_val not in (0.0, 1.0, -1.0, 0.5):
            lit.action = ScrubAction.FLAG
            lit.reason = "non-trivial float (review recommended)"
            return

        lit.action = ScrubAction.KEEP
        lit.reason = "generic value"

    def _get_string_context(self, source: str, offset: int) -> str:
        """Determine the context of a string literal (printf, assignment, etc.)."""
        # Look backwards for a function call
        before = source[max(0, offset - 80):offset].rstrip()
        # Match function_name( ... possibly with args before our string
        # Simple heuristic: find the last identifier before a '('
        match = re.search(r"(\w+)\s*\([^)]*$", before)
        if match:
            func_name = match.group(1)
            if func_name in PRINT_FUNCTIONS or "log" in func_name.lower() or "print" in func_name.lower():
                return "printf"
        # Check for << operator (C++ stream)
        if "<<" in before[-30:]:
            return "printf"
        return "other"

    def _get_number_context(self, source: str, offset: int) -> str:
        """Determine the context of a numeric literal."""
        # Check if it's in a for loop condition
        line_start = source.rfind("\n", 0, offset) + 1
        line = source[line_start:source.find("\n", offset)]
        stripped = line.strip()

        if stripped.startswith("for") or "for (" in line[:offset - line_start]:
            return "loop_bound"

        # Check if it's in a comparison
        after = source[offset:offset + 20]
        before = source[max(0, offset - 10):offset]
        if any(op in before + after for op in ["<", ">", "<=", ">=", "==", "!="]):
            return "comparison"

        # Check if in arithmetic
        if any(op in before + after for op in ["*", "/", "+", "-", "%"]):
            return "arithmetic"

        return "assignment"

    def _scrub_format_string(self, quoted_string: str) -> str:
        """Scrub a printf format string: keep format specifiers, remove text.

        'printf("Sensor %d reported %.2f at cycle %d\\n")'
        becomes: '"%d %.2f %d\\n"'
        """
        inner = quoted_string.strip('"')

        # Extract format specifiers and escape sequences
        parts = []
        i = 0
        while i < len(inner):
            if inner[i] == "%" and i + 1 < len(inner):
                # Find the end of the format specifier
                match = FORMAT_SPEC_PATTERN.match(inner[i:])
                if match:
                    parts.append(match.group())
                    i += len(match.group())
                    continue
            elif inner[i] == "\\" and i + 1 < len(inner):
                # Keep escape sequences (\n, \t, etc.)
                parts.append(inner[i:i + 2])
                i += 2
                continue
            i += 1

        if parts:
            return '"' + " ".join(parts) + '"'
        return '""'

    def _is_inside_string(self, source: str, offset: int) -> bool:
        """Check if offset is inside a string literal."""
        line_start = source.rfind("\n", 0, offset) + 1
        line_prefix = source[line_start:offset]
        # Count unescaped double quotes
        count = 0
        i = 0
        while i < len(line_prefix):
            if line_prefix[i] == '"' and (i == 0 or line_prefix[i - 1] != "\\"):
                count += 1
            i += 1
        return count % 2 == 1

    def summary(self, result: ScrubResult) -> str:
        """Generate a human-readable summary of scrub results."""
        lines = []
        if result.scrubbed:
            lines.append(f"\n  SCRUBBED ({len(result.scrubbed)} literals):")
            for lit in result.scrubbed:
                # Show quoted value for strings
                display_val = f'"{lit.value.strip(chr(34))}"' if lit.kind == "string" else lit.value
                display = display_val[:40] + "..." if len(display_val) > 40 else display_val
                lines.append(f"    {display:45s} → {lit.ghost_token:10s} ({lit.reason})")

        if result.kept:
            kept_vals = [l.value for l in result.kept[:10]]
            lines.append(f"\n  KEPT ({len(result.kept)} literals): {', '.join(kept_vals)}")

        if result.flagged:
            lines.append(f"\n  FLAGGED for review ({len(result.flagged)} literals):")
            for lit in result.flagged:
                lines.append(f"    Line {lit.line:4d}: {lit.value:20s} — {lit.reason}")

        return "\n".join(lines)
