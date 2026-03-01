"""Explanation translator.

Analyzes the AI's translated response and adds contextual annotations:

1. Naming advice detection — AI says "rename gv_01 to something descriptive"
   which becomes "rename userCount to something descriptive" (nonsensical).
   Detects and annotates these.

2. Stub speculation detection — AI references a function that was sent as
   a stub (no implementation). Flags that the AI is guessing about behavior
   it never saw.

3. New symbol flagging — marks AI-introduced variables in explanations.
"""

import re
from dataclasses import dataclass

from ..mapping.ghost_map import GhostMap


@dataclass
class Annotation:
    """An annotation to add to the translated explanation."""
    type: str  # "naming_advice", "stub_speculation", "new_symbol"
    location: str  # description of where in the text
    original_text: str  # the relevant sentence/phrase
    note: str  # the annotation message


# Patterns that indicate naming advice
NAMING_ADVICE_PATTERNS = [
    r"(?:rename|renaming)\s+(?:`)?{name}(?:`)?",
    r"(?:`)?{name}(?:`)?\s+(?:is a |has a )?(?:misleading|confusing|unclear|bad|poor)\s+(?:name|naming)",
    r"(?:consider|try|suggest)\s+(?:calling|naming|renaming)\s+(?:`)?{name}(?:`)?",
    r"(?:better|clearer|more descriptive)\s+name\s+(?:for|than)\s+(?:`)?{name}(?:`)?",
    r"(?:`)?{name}(?:`)?\s+(?:should|could|might)\s+be\s+(?:renamed|called|named)",
    r"(?:variable|function|class|method)\s+name\s+(?:`)?{name}(?:`)?",
]

# Patterns that indicate the AI is speculating about behavior
SPECULATION_PATTERNS = [
    r"(?:might|may|could|probably|likely|possibly)\s+(?:be |cause |have |return |throw )",
    r"(?:I'm not sure|it's unclear|hard to tell|without seeing)",
    r"(?:assuming|if I had to guess|based on the name)",
    r"(?:the implementation of|inside|within)\s+(?:`)?{name}(?:`)?",
    r"(?:make sure|verify|check|ensure)\s+(?:that\s+)?(?:`)?{name}(?:`)?",
]


class ExplanationTranslator:
    """Analyzes translated AI responses and adds contextual annotations."""

    def __init__(self, ghost_map: GhostMap, stubs: list[str] | None = None):
        """
        Args:
            ghost_map: The bidirectional ghost map.
            stubs: List of function names that were sent as stubs (no body).
        """
        self._map = ghost_map
        self._forward = ghost_map.forward_map()
        self._stubs = set(stubs or [])
        # Build reverse: original_name → ghost_token
        self._reverse = {v: k for k, v in self._forward.items()}

    def annotate(self, translated_text: str) -> tuple[str, list[Annotation]]:
        """Analyze translated text and add annotations.

        Args:
            translated_text: The AI response after token replacement.

        Returns:
            Tuple of (annotated_text, list_of_annotations).
        """
        annotations = []

        # Detect naming advice
        annotations.extend(self._detect_naming_advice(translated_text))

        # Detect stub speculation
        annotations.extend(self._detect_stub_speculation(translated_text))

        # Apply annotations to text
        annotated = self._apply_annotations(translated_text, annotations)

        return annotated, annotations

    def _detect_naming_advice(self, text: str) -> list[Annotation]:
        """Detect sentences where the AI gives naming advice about ghost tokens.

        After translation, "rename gv_001 to count" becomes
        "rename userCount to count" — which is nonsensical.
        """
        annotations = []
        # Check each mapped symbol
        for original_name, ghost_token in self._reverse.items():
            for pattern_template in NAMING_ADVICE_PATTERNS:
                pattern = pattern_template.format(name=re.escape(original_name))
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    # Extract the surrounding sentence
                    sentence = self._extract_sentence(text, match.start())
                    annotations.append(Annotation(
                        type="naming_advice",
                        location=f"near '{original_name}'",
                        original_text=sentence,
                        note=(
                            f"AI was commenting on the ghost token name "
                            f"'{ghost_token}', not your original name "
                            f"'{original_name}'. This suggestion may not apply."
                        ),
                    ))
                    break  # One match per symbol is enough

        return annotations

    def _detect_stub_speculation(self, text: str) -> list[Annotation]:
        """Detect when the AI speculates about functions sent as stubs."""
        annotations = []

        for stub_ghost_token in self._stubs:
            original_name = self._forward.get(stub_ghost_token)
            if not original_name:
                continue

            # Check if the AI references this function
            if original_name not in text:
                continue

            # Check for speculation patterns near the reference
            for pattern_template in SPECULATION_PATTERNS:
                pattern = pattern_template.format(name=re.escape(original_name))
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    sentence = self._extract_sentence(text, match.start())
                    annotations.append(Annotation(
                        type="stub_speculation",
                        location=f"about '{original_name}'",
                        original_text=sentence,
                        note=(
                            f"'{original_name}' was sent as a stub (no "
                            f"implementation). AI is inferring behavior "
                            f"without seeing the full code. Verify manually."
                        ),
                    ))
                    break

            # Even without speculation patterns, flag any substantive
            # discussion of a stubbed function
            sentences = text.split(".")
            for sentence in sentences:
                if original_name in sentence and len(sentence.strip()) > 30:
                    # Check it's not just a brief mention
                    word_count = len(sentence.split())
                    if word_count > 10:
                        already_flagged = any(
                            a.type == "stub_speculation"
                            and original_name in a.location
                            for a in annotations
                        )
                        if not already_flagged:
                            annotations.append(Annotation(
                                type="stub_speculation",
                                location=f"about '{original_name}'",
                                original_text=sentence.strip(),
                                note=(
                                    f"'{original_name}' was sent as a stub. "
                                    f"AI reasoning about its behavior may be "
                                    f"inaccurate."
                                ),
                            ))

        return annotations

    def _extract_sentence(self, text: str, position: int) -> str:
        """Extract the sentence containing a given position."""
        # Find sentence boundaries
        # Look backwards for sentence start
        start = position
        while start > 0 and text[start - 1] not in ".!?\n":
            start -= 1

        # Look forwards for sentence end
        end = position
        while end < len(text) and text[end] not in ".!?\n":
            end += 1

        sentence = text[start:end].strip()
        # Truncate if too long
        if len(sentence) > 150:
            sentence = sentence[:150] + "..."
        return sentence

    def _apply_annotations(self, text: str, annotations: list[Annotation]) -> str:
        """Insert annotation markers into the text."""
        if not annotations:
            return text

        annotated = text

        # Add annotations as footnotes at the end
        if annotations:
            annotated += "\n\n---\n"
            annotated += "**GhostCode Annotations:**\n\n"

            for i, ann in enumerate(annotations, 1):
                icon = {
                    "naming_advice": "~~",
                    "stub_speculation": "!!",
                    "new_symbol": "++",
                }.get(ann.type, "**")

                annotated += f"[{icon} {i}] {ann.note}\n"
                annotated += f"   Context: \"{ann.original_text[:80]}...\"\n\n"

        return annotated
