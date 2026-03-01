"""Python AST parser using the built-in ast module.

Walks the Python AST to identify user-defined symbols (functions, classes,
variables, parameters, attributes) and distinguishes them from stdlib/builtins
and framework symbols.

Uses the same two-pass strategy as the C++ parser:
    Pass 1: AST walk to discover user-defined symbol names.
    Pass 2: Token scan to find every occurrence with exact byte offsets.

Special handling:
    - Keeps dunder methods (__init__, __str__, etc.)
    - Keeps decorator names
    - Tracks imports to avoid renaming imported modules
    - String correlation: flags string literals matching symbol names
"""

import ast
import builtins
import keyword
import os
import re

from .base import BaseParser, Comment, ParseResult, Symbol, SymbolLocation

# Python builtins that should never be renamed
PYTHON_BUILTINS = set(dir(builtins)) | set(keyword.kwlist) | {
    "self", "cls", "super", "type", "object",
    "print", "len", "range", "enumerate", "zip", "map", "filter",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr", "delattr",
    "property", "staticmethod", "classmethod",
    "open", "input", "str", "int", "float", "bool", "list", "dict",
    "set", "tuple", "bytes", "bytearray", "memoryview",
    "None", "True", "False", "Ellipsis", "NotImplemented",
    "__name__", "__main__", "__file__", "__doc__", "__all__",
    "__init__", "__del__", "__repr__", "__str__", "__bytes__",
    "__format__", "__lt__", "__le__", "__eq__", "__ne__", "__gt__",
    "__ge__", "__hash__", "__bool__", "__getattr__", "__getattribute__",
    "__setattr__", "__delattr__", "__dir__", "__get__", "__set__",
    "__delete__", "__init_subclass__", "__set_name__", "__slots__",
    "__dict__", "__weakref__", "__class__", "__bases__", "__mro__",
    "__subclasses__", "__call__", "__len__", "__length_hint__",
    "__getitem__", "__setitem__", "__delitem__", "__missing__",
    "__iter__", "__next__", "__reversed__", "__contains__",
    "__add__", "__radd__", "__iadd__", "__sub__", "__rsub__",
    "__mul__", "__rmul__", "__imul__", "__truediv__", "__floordiv__",
    "__mod__", "__pow__", "__and__", "__or__", "__xor__",
    "__lshift__", "__rshift__", "__neg__", "__pos__", "__abs__",
    "__invert__", "__enter__", "__exit__", "__await__", "__aiter__",
    "__anext__", "__aenter__", "__aexit__",
}

# Common framework base classes and functions to not rename
FRAMEWORK_SYMBOLS = {
    # Django
    "models", "Model", "Form", "View", "CharField", "IntegerField",
    "FloatField", "BooleanField", "DateTimeField", "ForeignKey",
    "ManyToManyField", "OneToOneField", "Manager", "QuerySet",
    # Flask
    "Flask", "Blueprint", "request", "Response", "jsonify",
    "render_template", "redirect", "url_for", "abort",
    # FastAPI
    "FastAPI", "APIRouter", "Depends", "HTTPException", "Body", "Query",
    # SQLAlchemy
    "Column", "String", "Integer", "Float", "Boolean", "DateTime",
    "ForeignKey", "relationship", "backref", "Base",
    # Pydantic
    "BaseModel", "Field", "validator",
    # PyTorch
    "Module", "Tensor", "nn", "optim", "DataLoader", "Dataset",
    "forward", "backward",
    # Common test frameworks
    "TestCase", "setUp", "tearDown", "test_",
}


class PythonParser(BaseParser):
    """Python AST parser.

    Two-pass strategy:
        Pass 1: ast.NodeVisitor to discover user-defined symbol names.
        Pass 2: regex token scan to find all occurrences with byte offsets.
    """

    def __init__(self):
        self._source_file: str = ""
        self._imports: set[str] = set()

    def parse(self, file_path: str) -> ParseResult:
        self._source_file = os.path.abspath(file_path)

        with open(file_path, encoding="utf-8", errors="replace") as f:
            source_code = f.read()

        tree = ast.parse(source_code, filename=file_path)

        # Pass 1: Discover symbols
        user_symbols: dict[str, Symbol] = {}
        warnings: list[dict] = []
        self._imports = set()

        self._collect_imports(tree)
        self._discover_symbols(tree, user_symbols, warnings)

        # Pass 2: Find all occurrences
        self._find_all_occurrences(source_code, user_symbols)

        # Extract comments
        comments = self._extract_comments(source_code)

        return ParseResult(
            symbols=list(user_symbols.values()),
            comments=comments,
            source_code=source_code,
            file_path=file_path,
            warnings=warnings,
        )

    def _collect_imports(self, tree: ast.AST):
        """Collect all imported names so we don't rename them."""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    self._imports.add(name)
                    # Also add top-level module
                    self._imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self._imports.add(node.module.split(".")[0])
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    self._imports.add(name)

    def _discover_symbols(self, tree: ast.AST, symbols: dict,
                          warnings: list, scope: str = ""):
        """Walk AST to discover user-defined symbol names."""
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                name = node.name
                if self.is_user_defined(name):
                    kind = "method" if scope else "function"
                    if name not in symbols:
                        symbols[name] = Symbol(name=name, kind=kind, scope=scope)

                    # Parameters
                    for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                        arg_name = arg.arg
                        if self.is_user_defined(arg_name):
                            if arg_name not in symbols:
                                symbols[arg_name] = Symbol(
                                    name=arg_name, kind="parameter",
                                    scope=f"{scope}::{name}" if scope else name,
                                )

                    if node.args.vararg and self.is_user_defined(node.args.vararg.arg):
                        vname = node.args.vararg.arg
                        if vname not in symbols:
                            symbols[vname] = Symbol(
                                name=vname, kind="parameter",
                                scope=f"{scope}::{name}" if scope else name,
                            )

                    if node.args.kwarg and self.is_user_defined(node.args.kwarg.arg):
                        kname = node.args.kwarg.arg
                        if kname not in symbols:
                            symbols[kname] = Symbol(
                                name=kname, kind="parameter",
                                scope=f"{scope}::{name}" if scope else name,
                            )

                    # Recurse into function body
                    func_scope = f"{scope}::{name}" if scope else name
                    self._discover_symbols(node, symbols, warnings, func_scope)

                    # Local variables via assignment
                    self._collect_assignments(node, symbols, warnings, func_scope)

            elif isinstance(node, ast.ClassDef):
                name = node.name
                if self.is_user_defined(name):
                    if name not in symbols:
                        symbols[name] = Symbol(name=name, kind="class", scope=scope)

                    class_scope = f"{scope}::{name}" if scope else name
                    self._discover_symbols(node, symbols, warnings, class_scope)

            elif isinstance(node, ast.AnnAssign) and node.target:
                # Annotated assignments (e.g., dataclass fields: model_name: str)
                if isinstance(node.target, ast.Name):
                    name = node.target.id
                    if self.is_user_defined(name) and name not in symbols:
                        symbols[name] = Symbol(
                            name=name, kind="field", scope=scope,
                        )

            elif isinstance(node, ast.Assign):
                # Module-level assignments
                self._process_assignment(node, symbols, scope)

    def _collect_assignments(self, func_node: ast.AST, symbols: dict,
                             warnings: list, scope: str):
        """Collect variable assignments inside a function body."""
        for node in ast.walk(func_node):
            if isinstance(node, ast.Assign):
                self._process_assignment(node, symbols, scope)
            elif isinstance(node, ast.AnnAssign) and node.target:
                if isinstance(node.target, ast.Name):
                    name = node.target.id
                    if self.is_user_defined(name) and name not in symbols:
                        symbols[name] = Symbol(
                            name=name, kind="variable", scope=scope,
                        )
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name):
                    name = node.target.id
                    if self.is_user_defined(name) and name not in symbols:
                        symbols[name] = Symbol(
                            name=name, kind="variable", scope=scope,
                        )

    def _process_assignment(self, node: ast.Assign, symbols: dict, scope: str):
        """Process an assignment and collect variable names."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                name = target.id
                if self.is_user_defined(name) and name not in symbols:
                    symbols[name] = Symbol(
                        name=name, kind="variable", scope=scope,
                    )
            elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
                for elt in target.elts:
                    if isinstance(elt, ast.Name):
                        name = elt.id
                        if self.is_user_defined(name) and name not in symbols:
                            symbols[name] = Symbol(
                                name=name, kind="variable", scope=scope,
                            )
            elif isinstance(target, ast.Attribute):
                # self.attribute_name → collect attribute_name
                if (isinstance(target.value, ast.Name)
                        and target.value.id in ("self", "cls")):
                    name = target.attr
                    if self.is_user_defined(name) and name not in symbols:
                        symbols[name] = Symbol(
                            name=name, kind="field", scope=scope,
                        )

    def _find_all_occurrences(self, source_code: str, symbols: dict):
        """Find every occurrence of each symbol with exact byte offsets."""
        for name, symbol in symbols.items():
            pattern = re.compile(r"\b" + re.escape(name) + r"\b")
            for match in pattern.finditer(source_code):
                offset = match.start()
                end_offset = match.end()
                line = source_code[:offset].count("\n") + 1

                # Skip if inside a string literal
                if self._is_inside_string(source_code, offset):
                    continue
                # Skip if inside a comment
                if self._is_inside_comment(source_code, offset):
                    continue
                # Skip if part of an import statement
                if self._is_on_import_line(source_code, offset):
                    continue
                # Skip if it's a decorator
                if self._is_decorator(source_code, offset):
                    continue

                symbol.locations.append(SymbolLocation(
                    file=self._source_file,
                    line=line,
                    col=offset - source_code.rfind("\n", 0, offset),
                    offset=offset,
                    end_offset=end_offset,
                ))

    def _is_inside_string(self, source: str, offset: int) -> bool:
        """Check if offset is inside a string literal."""
        # Check for triple-quoted strings first
        before = source[:offset]
        # Count triple quotes
        for triple in ['"""', "'''"]:
            count = before.count(triple)
            if count % 2 == 1:
                return True

        # Check single-line strings
        line_start = before.rfind("\n") + 1
        line_prefix = source[line_start:offset]
        in_str = False
        quote_ch = None
        i = 0
        while i < len(line_prefix):
            ch = line_prefix[i]
            if not in_str:
                if ch in ('"', "'"):
                    in_str = True
                    quote_ch = ch
            else:
                if ch == "\\":
                    i += 1
                elif ch == quote_ch:
                    in_str = False
            i += 1
        return in_str

    def _is_inside_comment(self, source: str, offset: int) -> bool:
        """Check if offset is inside a # comment."""
        line_start = source.rfind("\n", 0, offset) + 1
        line_prefix = source[line_start:offset]
        # Check if there's an unquoted # before this position
        in_str = False
        quote_ch = None
        for ch in line_prefix:
            if not in_str:
                if ch == "#":
                    return True
                if ch in ('"', "'"):
                    in_str = True
                    quote_ch = ch
            else:
                if ch == quote_ch:
                    in_str = False
        return False

    def _is_on_import_line(self, source: str, offset: int) -> bool:
        """Check if offset is on an import line."""
        line_start = source.rfind("\n", 0, offset) + 1
        line_end = source.find("\n", offset)
        if line_end == -1:
            line_end = len(source)
        line = source[line_start:line_end].strip()
        return line.startswith("import ") or line.startswith("from ")

    def _is_decorator(self, source: str, offset: int) -> bool:
        """Check if offset is on a decorator line."""
        line_start = source.rfind("\n", 0, offset) + 1
        line = source[line_start:offset + 50].strip()
        return line.startswith("@")

    def is_user_defined(self, name: str, **kwargs) -> bool:
        """Check if a name is user-defined vs builtin/keyword/imported."""
        if not name:
            return False
        if name in PYTHON_BUILTINS:
            return False
        if name in self._imports:
            return False
        if name in FRAMEWORK_SYMBOLS:
            return False
        if name.startswith("__") and name.endswith("__"):
            return False
        if name.startswith("_") and len(name) == 1:
            return False  # _ is throwaway
        return True

    def _extract_comments(self, source_code: str) -> list[Comment]:
        """Extract all comments (# lines and docstrings)."""
        comments = []

        # Line comments
        for match in re.finditer(r"#[^\n]*", source_code):
            # Make sure it's not inside a string
            if not self._is_inside_string(source_code, match.start()):
                comments.append(Comment(
                    offset=match.start(),
                    end_offset=match.end(),
                    line=source_code[:match.start()].count("\n") + 1,
                ))

        # Docstrings (triple-quoted strings that are expression statements)
        tree = ast.parse(source_code)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    doc_node = body[0]
                    # Find the docstring in source
                    start_line = doc_node.lineno - 1  # 0-indexed
                    end_line = doc_node.end_lineno  # 1-indexed, exclusive
                    lines = source_code.split("\n")
                    start_offset = sum(len(lines[i]) + 1 for i in range(start_line))
                    end_offset = sum(len(lines[i]) + 1 for i in range(end_line))
                    # Trim trailing newline
                    end_offset = min(end_offset, len(source_code))
                    comments.append(Comment(
                        offset=start_offset,
                        end_offset=end_offset,
                        line=doc_node.lineno,
                    ))

        return comments
