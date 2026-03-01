"""Ghost token generator.

Produces collision-proof, fixed-width tokens with type-specific prefixes.
Deterministic: the same symbol always gets the same token within a session.

Token format:
    gv_001  → variables and parameters
    gf_001  → functions and methods
    gt_001  → types (classes, structs, enums, typedefs)
    gc_001  → constants (scrubbed numeric literals)
    gs_001  → strings (scrubbed string literals)
    gm_001  → macros
    gn_001  → namespaces
"""

KIND_PREFIXES = {
    "variable": "gv",
    "parameter": "gv",
    "field": "gv",
    "function": "gf",
    "method": "gf",
    "class": "gt",
    "struct": "gt",
    "enum": "gt",
    "enum_constant": "gv",
    "typedef": "gt",
    "type_alias": "gt",
    "constant": "gc",
    "string": "gs",
    "macro": "gm",
    "namespace": "gn",
}


class TokenGenerator:
    """Generates unique ghost tokens for user-defined symbols.

    Each symbol kind gets its own counter and prefix, ensuring no collisions.
    Tokens are zero-padded to 3 digits for consistent width.
    """

    def __init__(self):
        self._counters: dict[str, int] = {}
        self._assigned: dict[str, str] = {}

    def get_token(self, original_name: str, kind: str, scope: str = "") -> str:
        """Get or create a ghost token for a symbol.

        Args:
            original_name: The original symbol name.
            kind: Symbol kind (variable, function, class, etc.).
            scope: Qualified scope (e.g., "ClassName::method") for disambiguation.

        Returns:
            Ghost token string like "gv_001".
        """
        qualified = f"{scope}::{original_name}" if scope else original_name
        key = f"{kind}:{qualified}"

        if key in self._assigned:
            return self._assigned[key]

        prefix = KIND_PREFIXES.get(kind, "gx")
        count = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = count

        token = f"{prefix}_{count:03d}"
        self._assigned[key] = token
        return token

    def get_all_assignments(self) -> dict[str, str]:
        """Return a copy of all token assignments (key → token)."""
        return dict(self._assigned)

    def reset(self):
        """Reset all counters and assignments."""
        self._counters.clear()
        self._assigned.clear()
