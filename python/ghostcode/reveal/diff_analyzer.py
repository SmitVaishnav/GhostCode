"""AST diff analyzer and confidence scoring.

Compares the ghost code that was sent to the AI against the code the AI
returned. Classifies structural changes and assigns a confidence score
for how safe the auto-reveal is.

Change categories:
    MODIFIED        — existing function body changed (the fix)
    NEW_FUNCTION    — AI created a new function
    DELETED         — AI removed a function
    SIGNATURE_CHANGE — AI changed a function's parameters
    NEW_VARIABLE    — AI introduced a new variable
"""

import difflib
import re
from dataclasses import dataclass, field
from enum import Enum


class ChangeType(Enum):
    MODIFIED = "modified"
    NEW_FUNCTION = "new_function"
    DELETED_FUNCTION = "deleted_function"
    SIGNATURE_CHANGE = "signature_change"
    NEW_VARIABLE = "new_variable"
    NEW_DEPENDENCY = "new_dependency"


class Confidence(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class StructuralChange:
    """A single structural change between sent and received code."""
    type: ChangeType
    name: str
    detail: str = ""


@dataclass
class ChangeBlock:
    """A contiguous block of changed lines between original and modified code."""
    start_line: int  # 0-indexed line in the new/modified code
    end_line: int    # exclusive
    original_lines: list[str]
    new_lines: list[str]
    block_type: str = "modified"  # "modified", "added", or "deleted"


@dataclass
class DiffResult:
    """Result of comparing sent vs received code."""
    changes: list[StructuralChange] = field(default_factory=list)
    confidence: Confidence = Confidence.HIGH
    confidence_score: int = 100
    confidence_reason: str = ""
    new_symbols: list[str] = field(default_factory=list)
    new_dependencies: list[str] = field(default_factory=list)


class DiffAnalyzer:
    """Compares sent ghost code against AI's modified version."""

    def analyze(self, sent_code: str, received_code: str) -> DiffResult:
        """Compare structural differences between sent and received code.

        Args:
            sent_code: The ghost code that was sent to the AI.
            received_code: The code the AI returned (still in ghost form).

        Returns:
            DiffResult with changes, confidence, and new symbols.
        """
        result = DiffResult()

        # Extract functions from both
        sent_functions = self._extract_functions(sent_code)
        received_functions = self._extract_functions(received_code)

        sent_names = set(sent_functions.keys())
        received_names = set(received_functions.keys())

        # New functions
        for name in received_names - sent_names:
            result.changes.append(StructuralChange(
                type=ChangeType.NEW_FUNCTION,
                name=name,
                detail=f"AI created new function '{name}'",
            ))

        # Deleted functions
        for name in sent_names - received_names:
            result.changes.append(StructuralChange(
                type=ChangeType.DELETED_FUNCTION,
                name=name,
                detail=f"AI removed function '{name}'",
            ))

        # Modified functions
        for name in sent_names & received_names:
            sent_body = sent_functions[name]
            received_body = received_functions[name]
            if sent_body != received_body:
                # Check if signature changed
                sent_sig = self._extract_signature(sent_body)
                received_sig = self._extract_signature(received_body)
                if sent_sig != received_sig:
                    result.changes.append(StructuralChange(
                        type=ChangeType.SIGNATURE_CHANGE,
                        name=name,
                        detail=f"Signature changed: {sent_sig} → {received_sig}",
                    ))
                else:
                    result.changes.append(StructuralChange(
                        type=ChangeType.MODIFIED,
                        name=name,
                        detail="Body modified (the fix)",
                    ))

        # New variables (ghost-pattern tokens in received but not sent)
        sent_tokens = set(re.findall(r"\bg[vftcsnmx]_\d{3}\b", sent_code))
        received_tokens = set(re.findall(r"\bg[vftcsnmx]_\d{3}\b", received_code))
        new_tokens = received_tokens - sent_tokens
        result.new_symbols = sorted(new_tokens)
        for token in new_tokens:
            result.changes.append(StructuralChange(
                type=ChangeType.NEW_VARIABLE,
                name=token,
                detail=f"AI introduced new symbol '{token}'",
            ))

        # New dependencies
        sent_deps = set(self._extract_dependencies(sent_code))
        received_deps = set(self._extract_dependencies(received_code))
        result.new_dependencies = sorted(received_deps - sent_deps)
        for dep in result.new_dependencies:
            result.changes.append(StructuralChange(
                type=ChangeType.NEW_DEPENDENCY,
                name=dep,
                detail=f"AI added dependency: {dep}",
            ))

        # Calculate confidence score
        self._score_confidence(result)

        return result

    def _extract_functions(self, code: str) -> dict[str, str]:
        """Extract function names and bodies from code."""
        functions = {}

        # C++ style: type name(params) { ... }
        cpp_pattern = re.compile(
            r"(?:[\w:*&<>, ]+\s+)?(\w+)\s*\([^)]*\)(?:\s*(?:const|override|noexcept|final))*\s*\{",
        )

        for match in cpp_pattern.finditer(code):
            name = match.group(1)
            # Skip keywords
            if name in ("if", "for", "while", "switch", "catch", "return"):
                continue
            # Find matching brace
            start = match.start()
            brace_pos = code.index("{", match.start())
            depth = 0
            i = brace_pos
            while i < len(code):
                if code[i] == "{":
                    depth += 1
                elif code[i] == "}":
                    depth -= 1
                    if depth == 0:
                        functions[name] = code[start:i + 1]
                        break
                i += 1

        # Python style: def name(params):
        py_pattern = re.compile(r"def\s+(\w+)\s*\([^)]*\)\s*(?:->.*?)?:")
        for match in py_pattern.finditer(code):
            name = match.group(1)
            start = match.start()
            # Find the end by indentation
            body_start = match.end()
            lines = code[body_start:].split("\n")
            end_offset = body_start
            if lines and lines[0].strip() == "":
                end_offset += len(lines[0]) + 1
                lines = lines[1:]

            # Get indentation of first body line
            body_indent = None
            for line in lines:
                if line.strip():
                    body_indent = len(line) - len(line.lstrip())
                    break

            if body_indent is not None:
                for line in lines:
                    if line.strip() and (len(line) - len(line.lstrip())) < body_indent:
                        break
                    end_offset += len(line) + 1

            functions[name] = code[start:end_offset]

        return functions

    def _extract_signature(self, func_code: str) -> str:
        """Extract just the signature line from a function."""
        # C++
        match = re.match(
            r"((?:[\w:*&<>, ]+\s+)?\w+\s*\([^)]*\)(?:\s*(?:const|override|noexcept|final))*)",
            func_code.strip(),
        )
        if match:
            return match.group(1).strip()

        # Python
        match = re.match(r"(def\s+\w+\s*\([^)]*\))", func_code.strip())
        if match:
            return match.group(1).strip()

        return func_code.split("\n")[0].strip()

    def _extract_dependencies(self, code: str) -> list[str]:
        """Extract #include and import statements."""
        deps = []
        for line in code.split("\n"):
            stripped = line.strip()
            if (stripped.startswith("#include")
                    or stripped.startswith("import ")
                    or stripped.startswith("from ")):
                deps.append(stripped)
        return deps

    def _score_confidence(self, result: DiffResult):
        """Calculate confidence score based on changes detected."""
        score = 100

        for change in result.changes:
            if change.type == ChangeType.MODIFIED:
                score -= 5  # Expected — this is the fix
            elif change.type == ChangeType.NEW_VARIABLE:
                score -= 5
            elif change.type == ChangeType.NEW_FUNCTION:
                score -= 15
            elif change.type == ChangeType.DELETED_FUNCTION:
                score -= 20
            elif change.type == ChangeType.SIGNATURE_CHANGE:
                score -= 10
            elif change.type == ChangeType.NEW_DEPENDENCY:
                score -= 3

        score = max(0, score)

        if score >= 80:
            result.confidence = Confidence.HIGH
            result.confidence_reason = "Surgical fix — safe to auto-apply"
        elif score >= 50:
            result.confidence = Confidence.MEDIUM
            result.confidence_reason = "Moderate changes — review recommended"
        else:
            result.confidence = Confidence.LOW
            result.confidence_reason = (
                "Significant structural changes — manual review required"
            )

        result.confidence_score = score

    def detect_change_blocks(self, original: str, modified: str) -> list[ChangeBlock]:
        """Detect contiguous blocks of changes between original and modified code.

        Uses difflib.SequenceMatcher to find change opcodes, then merges
        consecutive blocks within a 1-line gap into single blocks.
        """
        orig_lines = original.splitlines()
        mod_lines = modified.splitlines()

        matcher = difflib.SequenceMatcher(None, orig_lines, mod_lines)
        raw_blocks: list[ChangeBlock] = []

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                continue

            if tag == "replace":
                block_type = "modified"
            elif tag == "insert":
                block_type = "added"
            elif tag == "delete":
                block_type = "deleted"
            else:
                continue

            raw_blocks.append(ChangeBlock(
                start_line=j1,
                end_line=j2,
                original_lines=orig_lines[i1:i2],
                new_lines=mod_lines[j1:j2],
                block_type=block_type,
            ))

        # Merge consecutive blocks within 1-line gap
        if not raw_blocks:
            return []

        merged: list[ChangeBlock] = [raw_blocks[0]]
        for block in raw_blocks[1:]:
            prev = merged[-1]
            if block.start_line - prev.end_line <= 1:
                # Merge: extend the previous block
                gap_lines = []
                if block.start_line > prev.end_line:
                    gap_lines = mod_lines[prev.end_line:block.start_line]
                merged[-1] = ChangeBlock(
                    start_line=prev.start_line,
                    end_line=block.end_line,
                    original_lines=prev.original_lines + gap_lines + block.original_lines,
                    new_lines=prev.new_lines + gap_lines + block.new_lines,
                    block_type="modified" if prev.original_lines or block.original_lines else "added",
                )
            else:
                merged.append(block)

        return merged

    def describe_change(self, block: ChangeBlock) -> str:
        """Generate a concise human-readable description of a change block."""
        new_text = "\n".join(block.new_lines)
        orig_text = "\n".join(block.original_lines)

        # Pure addition (no original lines)
        if not block.original_lines:
            return self._describe_addition(block.new_lines)

        # Pure deletion
        if not block.new_lines:
            return f"removed {len(block.original_lines)} lines"

        # Modification — try specific heuristics
        desc = self._describe_modification(block.original_lines, block.new_lines)
        if desc:
            return desc

        # Fallback
        return f"modified {len(block.new_lines)} lines"

    def _describe_addition(self, lines: list[str]) -> str:
        """Describe newly added lines."""
        joined = "\n".join(lines)
        stripped = [l.strip() for l in lines if l.strip()]

        # New function definition
        for line in stripped:
            match = re.match(r"def\s+(\w+)\s*\(", line)
            if match:
                return f"new helper function '{match.group(1)}'"
            # C++ function
            match = re.match(r"(?:[\w:*&<>, ]+\s+)?(\w+)\s*\([^)]*\)\s*\{", line)
            if match and match.group(1) not in ("if", "for", "while", "switch", "catch"):
                return f"new helper function '{match.group(1)}'"

        # Import / include
        if all(l.startswith(("import ", "from ", "#include")) for l in stripped if l):
            deps = ", ".join(stripped)
            return f"added dependency: {deps}"

        # try/except block
        if any("try:" in l or "try {" in l for l in stripped):
            return "error handling"

        # Null-safety patterns
        if any(".get(" in l or "is None" in l or "is not None" in l for l in stripped):
            return "null-safety check"

        # Conditional wrapping
        if any(l.startswith("if ") or l.startswith("if(") for l in stripped):
            return "added conditional check"

        return f"added {len(lines)} lines"

    def _describe_modification(self, orig_lines: list[str], new_lines: list[str]) -> str | None:
        """Try to describe a modification with a specific heuristic. Returns None for fallback."""
        orig_stripped = [l.strip() for l in orig_lines if l.strip()]
        new_stripped = [l.strip() for l in new_lines if l.strip()]

        # Null-safety: .get() pattern introduced
        if any(".get(" in l for l in new_stripped) and not any(".get(" in l for l in orig_stripped):
            return "null-safety check with .get()"

        # try/except added around existing code
        if any("try:" in l or "try {" in l for l in new_stripped) and not any("try:" in l or "try {" in l for l in orig_stripped):
            return "error handling"

        # Wrapped in conditional
        if any(l.startswith("if ") or l.startswith("if(") for l in new_stripped) and not any(l.startswith("if ") or l.startswith("if(") for l in orig_stripped):
            return "wrapped in conditional check"

        # Single operator change (e.g., '+' to '-')
        if len(orig_stripped) == 1 and len(new_stripped) == 1:
            o, n = orig_stripped[0], new_stripped[0]
            # Find single-character operator differences
            if len(o) == len(n):
                diffs = [(oc, nc) for oc, nc in zip(o, n) if oc != nc]
                if len(diffs) == 1:
                    oc, nc = diffs[0]
                    if oc in "+-*/%<>=!&|^" or nc in "+-*/%<>=!&|^":
                        return f"changed '{oc}' to '{nc}'"

        # New function in modified block
        for line in new_stripped:
            match = re.match(r"def\s+(\w+)\s*\(", line)
            if match and not any(match.group(1) in l for l in orig_stripped):
                return f"new helper function '{match.group(1)}'"

        # Import added
        new_imports = [l for l in new_stripped if l.startswith(("import ", "from ", "#include"))]
        old_imports = [l for l in orig_stripped if l.startswith(("import ", "from ", "#include"))]
        added_imports = set(new_imports) - set(old_imports)
        if added_imports:
            return f"added dependency: {', '.join(added_imports)}"

        return None
