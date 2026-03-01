"""Configuration system.

Three-tier config hierarchy (highest priority first):
    1. CLI flags (--level 3, --function update_matrix)
    2. Repo config (.ghostcode.yaml in project root)
    3. User config (~/.ghostcode/config.yaml)
    4. Defaults

Repo config is controlled by the security team. Developers can't
override its constraints (e.g., min_scrub_level).

Example .ghostcode.yaml:
    min_scrub_level: 3
    enforce_audit: true
    block_level_1: true
    encrypt_maps: true
    allowed_llm_endpoints:
      - "http://internal-llm.company.com:8080"
    banned_patterns:
      - "*.key"
      - "*.pem"
      - "*credentials*"
    pre_hide_hook: "scripts/compliance_check.sh"
"""

import os
from dataclasses import dataclass, field

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    import json


REPO_CONFIG_NAME = ".ghostcode.yaml"
USER_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".ghostcode")
USER_CONFIG_PATH = os.path.join(USER_CONFIG_DIR, "config.yaml")


@dataclass
class GhostConfig:
    """Resolved configuration for a GhostCode invocation."""
    # Privacy
    min_scrub_level: int = 1
    default_scrub_level: int = 2
    block_level_1: bool = False

    # Security
    encrypt_maps: bool = False
    enforce_audit: bool = True

    # Restrictions
    banned_patterns: list[str] = field(default_factory=list)
    allowed_llm_endpoints: list[str] = field(default_factory=list)

    # Hooks
    pre_hide_hook: str = ""

    # Paths
    map_dir: str = ""
    audit_dir: str = ""

    def validate_level(self, requested_level: int) -> int:
        """Validate and possibly override the requested privacy level.

        Returns the effective level, raising ValueError if the request
        violates repo policy.
        """
        if self.block_level_1 and requested_level == 1:
            raise ValueError(
                f"Repository policy blocks Level 1 (names-only mode). "
                f"Minimum level: {self.min_scrub_level}. "
                f"Contact your security team for exceptions."
            )
        if requested_level < self.min_scrub_level:
            raise ValueError(
                f"Repository policy requires minimum scrub level "
                f"{self.min_scrub_level}. Requested: {requested_level}. "
                f"Contact your security team for exceptions."
            )
        return requested_level

    def check_banned(self, file_path: str) -> bool:
        """Check if a file matches any banned pattern.

        Returns True if the file is banned (should not be processed).
        """
        import fnmatch
        basename = os.path.basename(file_path)
        for pattern in self.banned_patterns:
            if fnmatch.fnmatch(basename, pattern):
                return True
            if fnmatch.fnmatch(file_path, pattern):
                return True
        return False


def _load_yaml_or_json(filepath: str) -> dict:
    """Load a config file (YAML preferred, JSON fallback)."""
    if not os.path.exists(filepath):
        return {}

    with open(filepath, encoding="utf-8", errors="replace") as f:
        content = f.read()

    if not content.strip():
        return {}

    if HAS_YAML:
        return yaml.safe_load(content) or {}
    else:
        # Fallback: try JSON
        if filepath.endswith(".json"):
            return json.loads(content)
        return {}


def _find_repo_config(start_dir: str = ".") -> str | None:
    """Walk up the directory tree to find .ghostcode.yaml."""
    current = os.path.abspath(start_dir)
    while True:
        candidate = os.path.join(current, REPO_CONFIG_NAME)
        if os.path.exists(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


def load_config(start_dir: str = ".") -> GhostConfig:
    """Load configuration from all tiers and merge.

    Priority: repo config > user config > defaults.
    Repo config CONSTRAINS (can only make stricter, not more lenient).
    """
    config = GhostConfig()

    # Tier 3: User config
    user_data = _load_yaml_or_json(USER_CONFIG_PATH)
    if user_data:
        _apply_config(config, user_data)

    # Tier 2: Repo config (overrides user, can only be stricter)
    repo_path = _find_repo_config(start_dir)
    if repo_path:
        repo_data = _load_yaml_or_json(repo_path)
        if repo_data:
            _apply_repo_config(config, repo_data)

    return config


def _apply_config(config: GhostConfig, data: dict):
    """Apply user-level config values."""
    if "default_scrub_level" in data:
        config.default_scrub_level = int(data["default_scrub_level"])
    if "encrypt_maps" in data:
        config.encrypt_maps = bool(data["encrypt_maps"])
    if "enforce_audit" in data:
        config.enforce_audit = bool(data["enforce_audit"])
    if "map_dir" in data:
        config.map_dir = str(data["map_dir"])
    if "audit_dir" in data:
        config.audit_dir = str(data["audit_dir"])


def _apply_repo_config(config: GhostConfig, data: dict):
    """Apply repo-level config (can only make things stricter)."""
    if "min_scrub_level" in data:
        level = int(data["min_scrub_level"])
        config.min_scrub_level = max(config.min_scrub_level, level)
    if "block_level_1" in data:
        config.block_level_1 = config.block_level_1 or bool(data["block_level_1"])
    if "enforce_audit" in data:
        config.enforce_audit = config.enforce_audit or bool(data["enforce_audit"])
    if "encrypt_maps" in data:
        config.encrypt_maps = config.encrypt_maps or bool(data["encrypt_maps"])
    if "banned_patterns" in data:
        config.banned_patterns.extend(data["banned_patterns"])
    if "allowed_llm_endpoints" in data:
        config.allowed_llm_endpoints = data["allowed_llm_endpoints"]
    if "pre_hide_hook" in data:
        config.pre_hide_hook = str(data["pre_hide_hook"])
