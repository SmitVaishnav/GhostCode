"""Function isolator and dependency stubber.

Extracts a single target function from a source file and replaces all
other code with minimal type stubs. This dramatically reduces the
structural fingerprint by breaking co-occurrence of patterns.

The AI sees one anonymous function with opaque dependencies, not the
full system architecture. This is the core of Level 3 privacy.

Strategy:
    1. Find the target function in the AST.
    2. Extract its full implementation.
    3. Collect all types and functions it references.
    4. Generate opaque stubs for user-defined dependencies.
    5. Keep standard library includes as-is.
    6. Assemble: includes + stubs + target function.
"""

import ast
import re
import textwrap


class CppIsolator:
    """Isolates a single C++ function with dependency stubs."""

    def isolate(self, source: str, function_name: str) -> str | None:
        """Extract a function and stub its dependencies.

        Args:
            source: Full source code.
            function_name: Name of the function to isolate.

        Returns:
            Isolated source with stubs, or None if function not found.
        """
        # Extract includes
        includes = self._extract_includes(source)

        # Find the target function
        func_body = self._extract_function(source, function_name)
        if func_body is None:
            return None

        # Find all identifiers in the function that look like function calls
        called_functions = self._find_function_calls(func_body)

        # Find class/struct context if method
        class_context = self._find_class_context(source, function_name)

        # Build stubs for called functions (exclude the target itself)
        stubs = []
        for func in called_functions:
            if func != function_name:
                stub = self._find_function_signature(source, func)
                if stub:
                    stubs.append(stub + ";")

        # Find type declarations referenced
        type_stubs = self._find_type_stubs(source, func_body)

        # Assemble
        parts = []
        if includes:
            parts.append("\n".join(includes))
            parts.append("")

        if type_stubs:
            parts.append("// Type declarations (stubs)")
            parts.extend(type_stubs)
            parts.append("")

        if class_context:
            parts.append(f"// Class context (stub)")
            parts.append(class_context)
            parts.append("")

        if stubs:
            parts.append("// Dependency stubs")
            parts.extend(stubs)
            parts.append("")

        parts.append("// Target function")
        parts.append(func_body)

        return "\n".join(parts)

    def _extract_includes(self, source: str) -> list[str]:
        """Extract all #include directives."""
        return [line for line in source.split("\n")
                if line.strip().startswith("#include")]

    def _extract_function(self, source: str, name: str) -> str | None:
        """Extract a complete function definition by matching braces."""
        # Find function signature
        # Match: return_type name(params) { ... }
        # Also match: return_type ClassName::name(params) { ... }
        pattern = re.compile(
            r"^[ \t]*(?:[\w:*&<>, ]+\s+)?(?:\w+::)?" + re.escape(name)
            + r"\s*\([^)]*\)(?:\s*(?:const|override|noexcept|final))*\s*\{",
            re.MULTILINE,
        )
        match = pattern.search(source)
        if not match:
            return None

        start = match.start()
        # Find matching closing brace
        brace_count = 0
        i = match.end() - 1  # start at the opening brace
        while i < len(source):
            if source[i] == "{":
                brace_count += 1
            elif source[i] == "}":
                brace_count -= 1
                if brace_count == 0:
                    return source[start:i + 1]
            i += 1
        return None

    def _find_function_calls(self, func_body: str) -> set[str]:
        """Find all function call identifiers in a function body."""
        # Match: identifier( but not keywords
        calls = set()
        for match in re.finditer(r"\b([a-zA-Z_]\w*)\s*\(", func_body):
            name = match.group(1)
            cpp_keywords = {"if", "for", "while", "switch", "catch", "return",
                           "sizeof", "typeof", "decltype", "static_cast",
                           "dynamic_cast", "const_cast", "reinterpret_cast"}
            if name not in cpp_keywords:
                calls.add(name)
        return calls

    def _find_function_signature(self, source: str, name: str) -> str | None:
        """Find just the signature (no body) of a function."""
        pattern = re.compile(
            r"^[ \t]*((?:[\w:*&<>, ]+\s+)?(?:\w+::)?" + re.escape(name)
            + r"\s*\([^)]*\))(?:\s*(?:const|override|noexcept|final))*",
            re.MULTILINE,
        )
        match = pattern.search(source)
        if match:
            return match.group(0).strip()
        return None

    def _find_class_context(self, source: str, func_name: str) -> str | None:
        """If the function is a class method, generate a minimal class stub."""
        # Check if function is inside a class
        pattern = re.compile(
            r"class\s+(\w+)\s*(?::\s*[^{]*)?\{",
            re.MULTILINE,
        )
        for match in pattern.finditer(source):
            class_start = match.start()
            class_name = match.group(1)
            # Check if our function is within this class
            brace_count = 0
            i = source.index("{", class_start)
            while i < len(source):
                if source[i] == "{":
                    brace_count += 1
                elif source[i] == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        class_body = source[class_start:i + 1]
                        if func_name in class_body:
                            # Return a minimal class stub without the target function
                            return f"class {class_name}; // stub"
                        break
                i += 1
        return None

    def _find_type_stubs(self, source: str, func_body: str) -> list[str]:
        """Find user-defined types referenced in the function and stub them."""
        stubs = []
        # Find class/struct declarations in the source
        for match in re.finditer(r"\b(class|struct)\s+(\w+)\s*[{;]", source):
            type_kind = match.group(1)
            type_name = match.group(2)
            # Check if this type is referenced in our function
            if re.search(r"\b" + re.escape(type_name) + r"\b", func_body):
                stubs.append(f"{type_kind} {type_name}; // stub")
        return stubs


class PythonIsolator:
    """Isolates a single Python function with dependency stubs."""

    def isolate(self, source: str, function_name: str) -> str | None:
        """Extract a Python function and stub its dependencies.

        Args:
            source: Full source code.
            function_name: Name of the function/method to isolate.

        Returns:
            Isolated source with stubs, or None if function not found.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return None

        # Extract imports
        imports = self._extract_imports(source, tree)

        # Find the target function
        target_node = self._find_function(tree, function_name)
        if target_node is None:
            return None

        # Extract function source (dedent to remove class-level indentation)
        func_source = self._extract_node_source(source, target_node)
        if not func_source:
            return None
        func_source = textwrap.dedent(func_source)

        # Find called functions
        called = self._find_calls(target_node)

        # Build stubs
        stubs = []
        for call_name in called:
            if call_name != function_name:
                stub_node = self._find_function(tree, call_name)
                if stub_node:
                    sig = self._get_function_signature(source, stub_node)
                    if sig:
                        # Dedent to remove class-level indentation
                        sig_stripped = textwrap.dedent(sig)
                        stubs.append(f"{sig_stripped}\n    pass  # stub")

        # Find class context
        class_stub = self._find_class_context(tree, source, function_name)

        # Assemble
        parts = []
        if imports:
            parts.extend(imports)
            parts.append("")

        if class_stub:
            parts.append("# Class context (stub)")
            parts.append(class_stub)
            parts.append("")

        if stubs:
            parts.append("# Dependency stubs")
            parts.extend(stubs)
            parts.append("")

        parts.append("# Target function")
        parts.append(func_source)

        return "\n".join(parts)

    def _extract_imports(self, source: str, tree: ast.AST) -> list[str]:
        """Extract import statements."""
        imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(self._extract_node_source(source, node))
        return [i for i in imports if i]

    def _find_function(self, tree: ast.AST, name: str) -> ast.AST | None:
        """Find a function/method node by name."""
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == name:
                    return node
        return None

    def _extract_node_source(self, source: str, node: ast.AST) -> str | None:
        """Extract the source code for an AST node."""
        if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
            return None
        lines = source.split("\n")
        start = node.lineno - 1
        end = node.end_lineno
        return "\n".join(lines[start:end])

    def _get_function_signature(self, source: str, node: ast.AST) -> str | None:
        """Get just the def line of a function."""
        if not hasattr(node, "lineno"):
            return None
        lines = source.split("\n")
        sig_line = lines[node.lineno - 1]
        # Handle multi-line signatures
        if ")" not in sig_line:
            for i in range(node.lineno, min(node.lineno + 5, len(lines))):
                sig_line += "\n" + lines[i]
                if ")" in lines[i]:
                    break
        return sig_line.rstrip(":")  + ":"

    def _find_calls(self, func_node: ast.AST) -> set[str]:
        """Find all function calls within a function."""
        calls = set()
        for node in ast.walk(func_node):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    calls.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    calls.add(node.func.attr)
        return calls

    def _find_class_context(self, tree: ast.AST, source: str,
                            func_name: str) -> str | None:
        """If function is a method, generate a minimal class stub."""
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for item in node.body:
                    if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                            and item.name == func_name):
                        return f"class {node.name}:  # stub\n    pass"
        return None
