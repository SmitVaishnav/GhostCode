"""Comment anonymizer.

Instead of stripping comments entirely, this replaces the comment content
with a ghost comment token while preserving the comment syntax. The AI
sees valid comments/docstrings, not bare dunder variables.

Example:
    # Apple A15 thermal throttling for iPhone 13 Pro
becomes:
    # [gc_001]
And docstrings become:
    \"\"\"[gc_001]\"\"\"
On reveal both are restored to their originals.
"""

from ..mapping.ghost_map import GhostMap
from ..parsers.base import Comment


class CommentAnonymizer:
    """Replaces comment content with ghost tokens, stores originals in map."""

    def __init__(self, ghost_map: GhostMap):
        self._ghost_map = ghost_map
        self._counter = 0

    def anonymize(self, source: str, comments: list[Comment]) -> tuple[str, int]:
        """Replace each comment's content with a restorable ghost token.

        Keeps the comment syntax intact so AI recognizes them as comments,
        not variables. # comments stay as # [gc_XXX], docstrings stay as
        triple-quoted strings.

        Args:
            source: The source code string.
            comments: List of Comment objects with byte offsets.

        Returns:
            Tuple of (anonymized_source, count_of_comments_anonymized).
        """
        if not comments:
            return source, 0

        # Ensure the map has a comment storage dict
        if "original_comments" not in self._ghost_map._metadata:
            self._ghost_map._metadata["original_comments"] = {}

        comment_store = self._ghost_map._metadata["original_comments"]

        # Sort by offset descending to preserve earlier offsets
        sorted_comments = sorted(comments, key=lambda c: c.offset, reverse=True)

        count = 0
        for comment in sorted_comments:
            comment_text = source[comment.offset:comment.end_offset]

            # Generate a unique comment token
            self._counter += 1
            token = f"[gc_{self._counter:03d}]"

            # Build replacement that preserves comment syntax
            stripped = comment_text.lstrip()
            leading = comment_text[:len(comment_text) - len(stripped)]

            if stripped.startswith('"""') or stripped.startswith("'''"):
                # Docstring — keep triple quotes so AI sees a valid docstring
                # Preserve newline structure so code after docstring stays on its own line
                quote = stripped[:3]
                replacement = f'{leading}{quote}{token}{quote}\n'
                # Store the stripped version (without leading whitespace) since
                # the replacement already preserves leading whitespace.
                # Strip trailing \n to avoid double newline on reveal
                # (the ghost file replacement already has \n after the closing quotes)
                comment_store[token] = stripped.rstrip('\n')
            elif stripped.startswith("#"):
                # Python # comment — keep the # so AI sees a comment
                replacement = f'{leading}# {token}'
                comment_store[token] = comment_text
            elif stripped.startswith("//"):
                # C++ // comment
                replacement = f'{leading}// {token}'
                comment_store[token] = comment_text
            elif stripped.startswith("/*"):
                # C block comment
                replacement = f'{leading}/* {token} */'
                comment_store[token] = comment_text
            else:
                # Unknown — wrap in comment syntax for safety
                replacement = f'{leading}# {token}'
                comment_store[token] = comment_text

            source = source[:comment.offset] + replacement + source[comment.end_offset:]
            count += 1

        return source, count
