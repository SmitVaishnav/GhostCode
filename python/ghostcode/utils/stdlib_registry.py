"""Standard library and framework symbol registry.

Maintains lists of known stdlib/framework symbols that should NEVER
be renamed. Used as a fallback when AST-based classification is
insufficient (e.g., unresolved templates, dynamic Python).

Profiles:
    - C++ STL
    - Python builtins
    - Django, Flask, FastAPI, SQLAlchemy, Pydantic, PyTorch
"""

# ── C++ Standard Library ──────────────────────────────────────────

CPP_STL_NAMESPACES = {
    "std", "std::chrono", "std::filesystem", "std::regex",
    "std::this_thread", "std::placeholders",
}

CPP_STL_TYPES = {
    # Containers
    "vector", "list", "deque", "array", "forward_list",
    "set", "multiset", "unordered_set", "unordered_multiset",
    "map", "multimap", "unordered_map", "unordered_multimap",
    "stack", "queue", "priority_queue",
    # Strings
    "string", "wstring", "u16string", "u32string",
    "string_view", "basic_string",
    # Smart pointers
    "unique_ptr", "shared_ptr", "weak_ptr", "auto_ptr",
    # Utilities
    "pair", "tuple", "optional", "variant", "any",
    "function", "reference_wrapper",
    # IO
    "iostream", "istream", "ostream", "fstream",
    "ifstream", "ofstream", "stringstream",
    "istringstream", "ostringstream",
    # Iterators
    "iterator", "const_iterator", "reverse_iterator",
    # Threading
    "thread", "mutex", "lock_guard", "unique_lock",
    "condition_variable", "future", "promise", "atomic",
    # Memory
    "allocator",
    # Exceptions
    "exception", "runtime_error", "logic_error",
    "invalid_argument", "out_of_range", "overflow_error",
}

CPP_STL_FUNCTIONS = {
    # Algorithms
    "sort", "find", "find_if", "count", "count_if",
    "transform", "for_each", "copy", "move",
    "fill", "replace", "remove", "remove_if",
    "unique", "reverse", "rotate", "shuffle",
    "min", "max", "minmax", "clamp",
    "accumulate", "reduce", "inner_product",
    "binary_search", "lower_bound", "upper_bound",
    "merge", "partition", "nth_element",
    # IO
    "cout", "cin", "cerr", "clog", "endl", "flush",
    "getline", "put", "get",
    # Math
    "abs", "sqrt", "pow", "exp", "log", "log2", "log10",
    "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "ceil", "floor", "round", "fmod",
    # Memory
    "make_unique", "make_shared", "make_pair", "make_tuple",
    # String
    "to_string", "stoi", "stol", "stof", "stod",
    # Utility
    "swap", "exchange", "forward", "move",
    "static_cast", "dynamic_cast", "const_cast", "reinterpret_cast",
    # C stdlib
    "printf", "fprintf", "sprintf", "snprintf",
    "malloc", "calloc", "realloc", "free",
    "memcpy", "memset", "memmove", "memcmp",
    "strlen", "strcmp", "strncmp", "strcpy", "strncpy",
    "fopen", "fclose", "fread", "fwrite",
    "assert",
}

# Combined C++ set for fast lookup
CPP_STDLIB_ALL = CPP_STL_NAMESPACES | CPP_STL_TYPES | CPP_STL_FUNCTIONS

# ── Python Standard Library ──────────────────────────────────────

PYTHON_STDLIB_MODULES = {
    "os", "sys", "re", "json", "math", "random", "time", "datetime",
    "collections", "itertools", "functools", "operator", "typing",
    "pathlib", "shutil", "glob", "tempfile", "io",
    "subprocess", "threading", "multiprocessing", "concurrent",
    "socket", "http", "urllib", "email",
    "hashlib", "hmac", "secrets",
    "logging", "warnings", "traceback",
    "unittest", "pytest", "doctest",
    "abc", "enum", "dataclasses",
    "copy", "pickle", "shelve", "csv",
    "argparse", "configparser",
    "contextlib", "inspect", "importlib",
    "textwrap", "string",
    "struct", "array", "queue",
    "asyncio", "aiohttp",
}

# ── Framework Profiles ────────────────────────────────────────────

FRAMEWORK_PROFILES = {
    "django": {
        "base_classes": {
            "Model", "Form", "ModelForm", "View", "TemplateView",
            "ListView", "DetailView", "CreateView", "UpdateView",
            "DeleteView", "APIView", "ViewSet", "ModelViewSet",
            "Serializer", "ModelSerializer", "Admin", "ModelAdmin",
            "TestCase", "TransactionTestCase", "SimpleTestCase",
            "Command", "BaseCommand", "Middleware",
        },
        "safe_methods": {
            "objects", "filter", "get", "create", "update",
            "delete", "exclude", "order_by", "values", "annotate",
            "aggregate", "select_related", "prefetch_related",
            "save", "full_clean", "clean", "validate",
            "render", "redirect", "reverse", "resolve",
        },
        "decorators": {
            "login_required", "permission_required", "csrf_exempt",
            "require_http_methods", "api_view",
        },
    },
    "flask": {
        "base_classes": {
            "Flask", "Blueprint", "Resource", "MethodView",
        },
        "safe_methods": {
            "route", "before_request", "after_request",
            "errorhandler", "register_blueprint",
            "render_template", "redirect", "url_for",
            "jsonify", "abort", "make_response",
            "send_file", "send_from_directory",
        },
        "objects": {
            "request", "session", "g", "current_app",
        },
    },
    "fastapi": {
        "base_classes": {
            "FastAPI", "APIRouter", "BaseModel",
        },
        "safe_methods": {
            "get", "post", "put", "delete", "patch",
            "Depends", "HTTPException", "Body", "Query",
            "Path", "Header", "Cookie", "File", "Form",
            "BackgroundTasks", "Response", "JSONResponse",
        },
    },
    "sqlalchemy": {
        "base_classes": {
            "Base", "DeclarativeBase", "Session",
        },
        "safe_methods": {
            "Column", "Integer", "String", "Float", "Boolean",
            "DateTime", "Text", "ForeignKey", "Table",
            "relationship", "backref", "mapped_column",
            "create_engine", "sessionmaker",
            "query", "add", "commit", "rollback", "flush",
        },
    },
    "pydantic": {
        "base_classes": {
            "BaseModel", "BaseSettings",
        },
        "safe_methods": {
            "Field", "validator", "root_validator",
            "model_validator", "field_validator",
            "ConfigDict", "model_dump", "model_validate",
        },
    },
    "pytorch": {
        "base_classes": {
            "Module", "Dataset", "DataLoader", "Optimizer",
        },
        "safe_methods": {
            "forward", "backward", "parameters", "named_parameters",
            "state_dict", "load_state_dict", "train", "eval",
            "zero_grad", "step", "cuda", "cpu", "to",
            "tensor", "zeros", "ones", "randn", "rand",
            "cat", "stack", "reshape", "view", "permute",
            "Linear", "Conv2d", "BatchNorm2d", "ReLU", "Dropout",
            "CrossEntropyLoss", "MSELoss", "Adam", "SGD",
        },
        "modules": {
            "torch", "nn", "optim", "F",
            "torchvision", "transforms",
        },
    },
}


def get_all_framework_symbols() -> set[str]:
    """Return a flat set of all known framework symbols."""
    symbols = set()
    for profile in FRAMEWORK_PROFILES.values():
        for category in profile.values():
            if isinstance(category, set):
                symbols |= category
    return symbols


def is_framework_symbol(name: str) -> bool:
    """Check if a name is a known framework symbol."""
    return name in get_all_framework_symbols()


def is_cpp_stdlib(name: str) -> bool:
    """Check if a name is a known C++ stdlib symbol."""
    return name in CPP_STDLIB_ALL


def is_python_stdlib_module(name: str) -> bool:
    """Check if a name is a known Python stdlib module."""
    return name in PYTHON_STDLIB_MODULES
