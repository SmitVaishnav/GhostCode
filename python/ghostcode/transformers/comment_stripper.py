"""Comment stripper.

Removes all comments from source code. Comments are the #1 IP leak vector.
A comment like "// Samsung S24 thermal throttling workaround" reveals more
than any variable name ever could.

Uses AST-provided comment locations for C++ (precise offsets from libclang).
Uses regex-based stripping for Python (# comments and docstrings).

Strips from end to start to preserve byte offsets, same strategy as the
symbol renamer.
"""

from ..parsers.base import Comment


class CommentStripper:
    """Removes all comments from source code."""

    def strip(self, source: str, comments: list[Comment]) -> tuple[str, int]:
        """Remove all comments from source code.

        Args:
            source: The source code string.
            comments: List of Comment objects with byte offsets.

        Returns:
            Tuple of (stripped_source, count_of_comments_removed).
        """
        if not comments:
            return source, 0

        # Sort by offset descending — remove from end to preserve earlier offsets
        sorted_comments = sorted(comments, key=lambda c: c.offset, reverse=True)

        count = 0
        for comment in sorted_comments:
            before = source[:comment.offset]
            after = source[comment.end_offset:]

            # Check if comment is on its own line (only whitespace before it)
            line_start = before.rfind("\n") + 1
            prefix = before[line_start:]

            if prefix.strip() == "":
                # Comment is on its own line — remove the entire line
                # including leading whitespace and trailing newline
                after_stripped = after.lstrip(" \t")
                if after_stripped.startswith("\n"):
                    after = after_stripped[1:]
                source = before[:line_start] + after
            else:
                # Comment is inline (code before it on same line)
                # Remove the comment but keep the code
                # Also strip trailing whitespace before the comment
                source = before.rstrip(" \t") + after

            count += 1

        return source, count
