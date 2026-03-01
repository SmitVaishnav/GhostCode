"""C++ AST parser using libclang.

Strategy: Two-pass approach.
  Pass 1 (AST): Walk the clang AST to identify which symbols are user-defined.
                Collect their names, kinds, and scopes.
  Pass 2 (Token): Scan ALL tokens in the source file. For each identifier token,
                  check if it matches a known user-defined symbol. If yes, record
                  its exact byte offset.

This two-pass approach is more robust than trying to get exact offsets from the
AST alone, because libclang's reference cursors can miss implicit references
(e.g., member access via implicit 'this->') or report imprecise locations.
"""

import os
import re
import subprocess

try:
    from clang.cindex import (
        Config,
        CursorKind,
        Index,
        TokenKind,
        TranslationUnit,
    )
    _CLANG_AVAILABLE = True
except ImportError:
    _CLANG_AVAILABLE = False

from .base import BaseParser, Comment, ParseResult, Symbol, SymbolLocation

# Cursor kinds / kind map are only populated when clang is available
if _CLANG_AVAILABLE:
    # Cursor kinds that represent user-definable symbols
    USER_SYMBOL_KINDS = {
        CursorKind.VAR_DECL,
        CursorKind.PARM_DECL,
        CursorKind.FUNCTION_DECL,
        CursorKind.CXX_METHOD,
        CursorKind.CONSTRUCTOR,
        CursorKind.DESTRUCTOR,
        CursorKind.CLASS_DECL,
        CursorKind.STRUCT_DECL,
        CursorKind.FIELD_DECL,
        CursorKind.ENUM_DECL,
        CursorKind.ENUM_CONSTANT_DECL,
        CursorKind.NAMESPACE,
        CursorKind.TYPEDEF_DECL,
        CursorKind.TYPE_ALIAS_DECL,
        CursorKind.CLASS_TEMPLATE,
        CursorKind.FUNCTION_TEMPLATE,
    }

    # Map from CursorKind to our simplified kind string
    KIND_MAP = {
        CursorKind.VAR_DECL: "variable",
        CursorKind.PARM_DECL: "parameter",
        CursorKind.FUNCTION_DECL: "function",
        CursorKind.CXX_METHOD: "method",
        CursorKind.CONSTRUCTOR: "method",
        CursorKind.DESTRUCTOR: "method",
        CursorKind.CLASS_DECL: "class",
        CursorKind.STRUCT_DECL: "struct",
        CursorKind.FIELD_DECL: "field",
        CursorKind.ENUM_DECL: "enum",
        CursorKind.ENUM_CONSTANT_DECL: "enum_constant",
        CursorKind.NAMESPACE: "namespace",
        CursorKind.TYPEDEF_DECL: "typedef",
        CursorKind.TYPE_ALIAS_DECL: "type_alias",
        CursorKind.CLASS_TEMPLATE: "class",
        CursorKind.FUNCTION_TEMPLATE: "function",
    }
else:
    USER_SYMBOL_KINDS = set()
    KIND_MAP = {}

# Common system include paths on macOS
SYSTEM_PATHS = (
    "/usr/include",
    "/usr/lib",
    "/usr/local/include",
    "/Library/Developer",
    "/Applications/Xcode.app",
    "/opt/homebrew",
    "/usr/local/Cellar",
)

# C++ keywords that should never be renamed
CPP_KEYWORDS = {
    "alignas", "alignof", "and", "and_eq", "asm", "auto", "bitand",
    "bitor", "bool", "break", "case", "catch", "char", "char8_t",
    "char16_t", "char32_t", "class", "compl", "concept", "const",
    "consteval", "constexpr", "constinit", "const_cast", "continue",
    "co_await", "co_return", "co_yield", "decltype", "default", "delete",
    "do", "double", "dynamic_cast", "else", "enum", "explicit", "export",
    "extern", "false", "float", "for", "friend", "goto", "if", "inline",
    "int", "long", "mutable", "namespace", "new", "noexcept", "not",
    "not_eq", "nullptr", "operator", "or", "or_eq", "private", "protected",
    "public", "register", "reinterpret_cast", "requires", "return", "short",
    "signed", "sizeof", "static", "static_assert", "static_cast", "struct",
    "switch", "template", "this", "thread_local", "throw", "true", "try",
    "typedef", "typeid", "typename", "union", "unsigned", "using",
    "virtual", "void", "volatile", "wchar_t", "while", "xor", "xor_eq",
    "override", "final",
    # Common builtins
    "main", "argc", "argv", "NULL", "size_t", "ptrdiff_t",
    "int8_t", "int16_t", "int32_t", "int64_t",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t",
    "string", "cout", "cin", "cerr", "endl", "std",
}


def _find_libclang():
    """Attempt to locate libclang on macOS."""
    common_paths = [
        "/opt/homebrew/opt/llvm/lib/libclang.dylib",
        "/usr/local/opt/llvm/lib/libclang.dylib",
        "/Library/Developer/CommandLineTools/usr/lib/libclang.dylib",
        "/Applications/Xcode.app/Contents/Developer/Toolchains/"
        "XcodeDefault.xctoolchain/usr/lib/libclang.dylib",
    ]
    for path in common_paths:
        if os.path.exists(path):
            return path
    return None


def _get_sdk_path() -> str | None:
    """Get the macOS SDK path for C++ stdlib headers."""
    try:
        result = subprocess.run(
            ["xcrun", "--show-sdk-path"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_clang_args() -> list[str]:
    """Build clang args including proper SDK include paths."""
    args = ["-std=c++17", "-x", "c++"]
    sdk = _get_sdk_path()
    if sdk:
        args.extend([
            f"-isysroot", sdk,
            f"-I{sdk}/usr/include/c++/v1",
            f"-I{sdk}/usr/include",
        ])
    return args


class CppParser(BaseParser):
    """C++ AST parser using libclang.

    Two-pass strategy:
        Pass 1: AST walk to discover user-defined symbol names and kinds.
        Pass 2: Token scan to find every occurrence with exact byte offsets.
    """

    def __init__(self):
        if not _CLANG_AVAILABLE:
            raise RuntimeError(
                "C/C++ parsing requires the 'libclang' package. "
                "Install it with: pip install libclang"
            )
        libclang_path = _find_libclang()
        if libclang_path and not Config.loaded:
            Config.set_library_file(libclang_path)
        self._index = Index.create()
        self._source_file: str = ""

    def parse(self, file_path: str) -> ParseResult:
        self._source_file = os.path.abspath(file_path)

        with open(file_path) as f:
            source_code = f.read()

        tu = self._index.parse(
            file_path,
            args=_get_clang_args(),
            options=TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD,
        )

        # Pass 1: Walk AST to discover user-defined symbols
        user_symbols: dict[str, Symbol] = {}
        warnings: list[dict] = []
        self._discover_symbols(tu.cursor, user_symbols, warnings)

        # Pass 2: Scan source for all occurrences of discovered symbols
        self._find_all_occurrences(source_code, user_symbols)

        # Extract comments
        comments = self._extract_comments(tu, source_code)

        return ParseResult(
            symbols=list(user_symbols.values()),
            comments=comments,
            source_code=source_code,
            file_path=file_path,
            warnings=warnings,
        )

    def _discover_symbols(self, cursor, symbols: dict, warnings: list):
        """Pass 1: Walk AST to discover all user-defined symbol names."""
        if cursor.location.file:
            filepath = str(cursor.location.file)
            if self._is_system_header(filepath):
                return
            if os.path.abspath(filepath) != self._source_file:
                return

        if cursor.kind in USER_SYMBOL_KINDS:
            name = cursor.spelling
            if name and not name.startswith("operator") and name not in CPP_KEYWORDS:
                if self._is_in_source_file(cursor):
                    scope = self._get_scope(cursor)
                    kind = KIND_MAP.get(cursor.kind, "variable")

                    # For constructors/destructors, use the class scope
                    if cursor.kind in (CursorKind.CONSTRUCTOR, CursorKind.DESTRUCTOR):
                        # Don't create a separate symbol for constructors —
                        # the class name symbol already covers it
                        pass
                    else:
                        key = name  # Use simple name as key for token matching
                        if key not in symbols:
                            symbols[key] = Symbol(
                                name=name, kind=kind, scope=scope
                            )

        for child in cursor.get_children():
            self._discover_symbols(child, symbols, warnings)

    def _find_all_occurrences(self, source_code: str, symbols: dict):
        """Pass 2: Find every occurrence of each user symbol in source code.

        Uses word-boundary regex to find exact positions. This catches ALL
        references including implicit this->, initializer lists, and any
        other context the AST walk might miss.
        """
        for name, symbol in symbols.items():
            pattern = re.compile(r"\b" + re.escape(name) + r"\b")
            for match in pattern.finditer(source_code):
                offset = match.start()
                end_offset = match.end()

                # Determine line number
                line = source_code[:offset].count("\n") + 1

                # Skip if this is inside a string literal or #include
                if self._is_inside_string(source_code, offset):
                    continue
                if self._is_inside_include(source_code, offset):
                    continue
                # Skip if preceded by :: from std namespace (e.g., std::vector)
                if self._is_std_qualified(source_code, offset):
                    continue

                symbol.locations.append(SymbolLocation(
                    file=self._source_file,
                    line=line,
                    col=offset - source_code.rfind("\n", 0, offset),
                    offset=offset,
                    end_offset=end_offset,
                ))

    def _is_inside_string(self, source: str, offset: int) -> bool:
        """Check if an offset is inside a string literal."""
        # Find the line containing this offset
        line_start = source.rfind("\n", 0, offset) + 1
        line_end = source.find("\n", offset)
        if line_end == -1:
            line_end = len(source)
        line = source[line_start:line_end]
        pos_in_line = offset - line_start

        # Count unescaped quotes before this position
        in_string = False
        quote_char = None
        i = 0
        while i < pos_in_line:
            ch = line[i]
            if not in_string:
                if ch in ('"', "'"):
                    in_string = True
                    quote_char = ch
            else:
                if ch == "\\" :
                    i += 1  # skip escaped char
                elif ch == quote_char:
                    in_string = False
            i += 1

        return in_string

    def _is_inside_include(self, source: str, offset: int) -> bool:
        """Check if an offset is on a #include line."""
        line_start = source.rfind("\n", 0, offset) + 1
        line_end = source.find("\n", offset)
        if line_end == -1:
            line_end = len(source)
        line = source[line_start:line_end].strip()
        return line.startswith("#include")

    def _is_std_qualified(self, source: str, offset: int) -> bool:
        """Check if the identifier is preceded by 'std::'."""
        # Look for 'std::' immediately before the identifier
        prefix_start = max(0, offset - 5)
        prefix = source[prefix_start:offset]
        return prefix.endswith("std::")

    def _get_scope(self, cursor) -> str:
        """Get the qualified scope of a cursor."""
        parts = []
        parent = cursor.semantic_parent
        while parent and parent.kind != CursorKind.TRANSLATION_UNIT:
            if parent.spelling:
                parts.append(parent.spelling)
            parent = parent.semantic_parent
        return "::".join(reversed(parts))

    def _is_in_source_file(self, cursor) -> bool:
        """Check if cursor is in the file being parsed."""
        if not cursor.location.file:
            return False
        return os.path.abspath(str(cursor.location.file)) == self._source_file

    def is_user_defined(self, name: str, **kwargs) -> bool:
        if name in CPP_KEYWORDS:
            return False
        cursor = kwargs.get("cursor")
        if cursor and cursor.location.file:
            if self._is_system_header(str(cursor.location.file)):
                return False
        return True

    def _is_system_header(self, filepath: str) -> bool:
        abspath = os.path.abspath(filepath)
        return any(abspath.startswith(sp) for sp in SYSTEM_PATHS)

    def _extract_comments(self, tu, source_code: str) -> list[Comment]:
        """Extract all comments using libclang tokenization."""
        comments = []
        for token in tu.cursor.get_tokens():
            if token.kind == TokenKind.COMMENT:
                extent = token.extent
                comments.append(Comment(
                    offset=extent.start.offset,
                    end_offset=extent.end.offset,
                    line=token.location.line,
                ))
        return comments
