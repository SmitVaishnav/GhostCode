"""Abstract base parser for language-specific AST walkers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SymbolLocation:
    """A specific location of a symbol in source code."""
    file: str
    line: int
    col: int
    offset: int
    end_offset: int


@dataclass
class Symbol:
    """A user-defined symbol extracted from source code."""
    name: str
    kind: str
    scope: str = ""
    locations: list[SymbolLocation] = field(default_factory=list)

    @property
    def qualified_name(self) -> str:
        return f"{self.scope}::{self.name}" if self.scope else self.name


@dataclass
class Comment:
    """A comment to be stripped."""
    offset: int
    end_offset: int
    line: int


@dataclass
class ParseResult:
    """Result of parsing a source file."""
    symbols: list[Symbol]
    comments: list[Comment]
    source_code: str
    file_path: str
    warnings: list[dict] = field(default_factory=list)


class BaseParser(ABC):
    """Abstract base class for language-specific parsers."""

    @abstractmethod
    def parse(self, file_path: str) -> ParseResult:
        """Parse a source file and extract user-defined symbols.

        Args:
            file_path: Path to the source file.

        Returns:
            ParseResult containing all symbols, comments, and metadata.
        """
        ...

    @abstractmethod
    def is_user_defined(self, name: str, **kwargs) -> bool:
        """Check if a symbol is user-defined vs stdlib/keyword."""
        ...
