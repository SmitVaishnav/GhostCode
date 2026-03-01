"""GhostCode CLI — Privacy Proxy for Developers.

Commands:
    ghost hide [files]   Strip business context, produce anonymous code
    ghost reveal [file]  Restore original names from AI's response
    ghost map [mapfile]  Inspect a ghost map
    ghost status         Show GhostCode status and recent activity
    ghost demo           Run interactive demo (hackathon)
"""

import os
import re
import sys
import tempfile
from datetime import datetime

import click

from . import __version__
from .audit.logger import AuditLogger
from .config import load_config
from .mapping.ghost_map import GhostMap
from .parsers.base import ParseResult
from .parsers.cpp_parser import CppParser
from .parsers.python_parser import PythonParser
from .transformers.comment_anonymizer import CommentAnonymizer
from .transformers.comment_stripper import CommentStripper
from .transformers.literal_scrubber import LiteralScrubber
from .transformers.symbol_renamer import SymbolRenamer
from .transformers.isolator import CppIsolator, PythonIsolator
from .transformers.multi_file import process_multiple_files
from .utils.clipboard import copy_to_clipboard, clipboard_available
from .risk_report import RiskAnalyzer, format_risk_report_cli

LANGUAGE_MAP = {
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".c": "cpp", ".h": "cpp", ".hpp": "cpp", ".hxx": "cpp",
    ".py": "python",
}

# ── Styled output helpers ───────────────────────────────────────────

BANNER = r"""
   ________               __  ______          __
  / ____/ /_  ____  _____/ /_/ ____/___  ____/ /__
 / / __/ __ \/ __ \/ ___/ __/ /   / __ \/ __  / _ \
/ /_/ / / / / /_/ (__  ) /_/ /___/ /_/ / /_/ /  __/
\____/_/ /_/\____/____/\__/\____/\____/\__,_/\___/
"""


def _header(text: str):
    """Print a styled section header."""
    click.secho(f"\n{'=' * 54}", fg="cyan")
    click.secho(f"  {text}", fg="cyan", bold=True)
    click.secho(f"{'=' * 54}", fg="cyan")


def _step(label: str, detail: str = "", done: bool = True):
    """Print a step indicator."""
    icon = click.style("  [+]", fg="green") if done else click.style("  [~]", fg="yellow")
    msg = f"{icon} {label}"
    if detail:
        msg += click.style(f"  {detail}", fg="white", dim=True)
    click.echo(msg)


def _warn(msg: str):
    """Print a warning."""
    click.secho(f"  [!] {msg}", fg="yellow")


def _error(msg: str):
    """Print an error and exit."""
    click.secho(f"\n  ERROR: {msg}", fg="red", bold=True, err=True)
    sys.exit(1)


def _info(label: str, value: str):
    """Print an info line."""
    click.echo(f"  {click.style(label + ':', bold=True):30s} {value}")


def _divider():
    click.secho(f"  {'─' * 50}", fg="white", dim=True)


def _get_language(file_path: str) -> str | None:
    _, ext = os.path.splitext(file_path)
    return LANGUAGE_MAP.get(ext.lower())


def _get_parser(language: str):
    if language == "cpp":
        return CppParser()
    if language == "python":
        return PythonParser()
    _error(f"Unsupported language '{language}'. Supported: C/C++, Python")


def _default_map_dir() -> str:
    return os.path.join(".ghostcode", "maps")


def _generate_map_path(source_file: str) -> str:
    base = os.path.splitext(os.path.basename(source_file))[0]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(_default_map_dir(), f"{base}_{timestamp}.json")


# ── Main CLI group ──────────────────────────────────────────────────

@click.group()
@click.version_option(version=__version__, prog_name="ghostcode")
def main():
    """GhostCode — Privacy Proxy for Developers.

    Strip business context from code before sending to AI.
    Restore original names after getting AI's response.

    Your code stays anonymous. Your logic stays intact.
    """
    pass


# ── HIDE command ────────────────────────────────────────────────────

@main.command()
@click.argument("file_paths", nargs=-1, type=click.Path(exists=True), required=True)
@click.option("--level", type=click.IntRange(1, 4), default=None,
              help="Privacy level: 1=names+comments, 2=+literals, 3=+isolation, 4=+dimensions")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output file path (default: ghost_<filename>)")
@click.option("--map-file", type=click.Path(), default=None,
              help="Map file path (default: .ghostcode/maps/<name>_<timestamp>.json)")
@click.option("--function", "-f", type=str, default=None,
              help="Function to isolate (Level 3+).")
@click.option("--encrypt/--no-encrypt", default=None,
              help="Encrypt the map file (default: from config)")
@click.option("--passphrase", type=str, default=None, hide_input=True,
              help="Passphrase for map encryption (prompted if not provided)")
@click.option("--copy/--no-copy", "clipboard", default=True,
              help="Copy ghost output to clipboard (default: yes)")
@click.option("--keep-comments", is_flag=True, default=False,
              help="Anonymize comments instead of stripping them")
@click.option("--risk-report/--no-risk-report", "show_risk_report", default=True,
              help="Show pre-send risk report (default: yes)")
def hide(file_paths: tuple[str, ...], level: int | None, output: str | None,
         map_file: str | None, function: str | None,
         encrypt: bool | None, passphrase: str | None,
         clipboard: bool, keep_comments: bool, show_risk_report: bool):
    """Strip business context from source file(s).

    Privacy levels:
      1 — Rename user symbols + strip comments
      2 — + Scrub string/numeric literals (smart classification)
      3 — + Function isolation with dependency stubs
      4 — + Dimension generalization (loop bounds → constants)

    Examples:
      ghost hide app.py
      ghost hide server.cpp --level 3 --function handle_request
      ghost hide *.py --encrypt --level 4
    """
    # Load config
    config = load_config()
    audit = AuditLogger(enabled=config.enforce_audit)

    # Resolve level
    if level is None:
        level = config.default_scrub_level
    try:
        level = config.validate_level(level)
    except ValueError as e:
        _error(str(e))

    # Resolve encryption
    use_encryption = encrypt if encrypt is not None else config.encrypt_maps

    # Process first file (multi-file uses the first for primary output)
    file_path = file_paths[0]

    # Check banned patterns
    for fp in file_paths:
        if config.check_banned(fp):
            _error(
                f"'{fp}' matches a banned pattern in repo policy.\n"
                f"           Banned patterns: {', '.join(config.banned_patterns)}\n"
                f"           Contact your security team for exceptions."
            )

    language = _get_language(file_path)
    if not language:
        ext = os.path.splitext(file_path)[1]
        _error(
            f"Unsupported file type '{ext}'.\n"
            f"           Supported: .py, .cpp, .cc, .c, .h, .hpp"
        )

    # ── Header ─────────────────────────────────────────────────────
    _header("GHOST HIDE")
    level_labels = {
        1: "Names + Comments",
        2: "Names + Comments + Literals",
        3: "Names + Comments + Literals + Isolation",
        4: "Full (Names + Comments + Literals + Isolation + Dimensions)",
    }
    _info("Source", ", ".join(file_paths))
    _info("Language", language.upper())
    _info("Privacy Level", f"{level} — {level_labels[level]}")
    if function:
        _info("Isolate Function", function)
    if use_encryption:
        _info("Map Encryption", "ON")
    click.echo()

    # Read source
    with open(file_path, encoding="utf-8", errors="replace") as f:
        source_code = f.read()

    # ── Level 3+: Function Isolation ──────────────────────────────
    isolated = False
    if level >= 3 and function:
        if language == "cpp":
            isolator = CppIsolator()
        else:
            isolator = PythonIsolator()

        isolated_source = isolator.isolate(source_code, function)
        if isolated_source:
            source_code = isolated_source
            isolated = True
            _step("Function isolated", f"'{function}' extracted with stubs")
        else:
            _warn(f"Function '{function}' not found — processing full file")

    # ── Parse & Transform ─────────────────────────────────────────
    parser = _get_parser(language)
    ghost_map = GhostMap()
    multi_mode = len(file_paths) > 1 and not isolated

    if multi_mode:
        # ── Multi-file: consistent tokens across all files ────────
        _step("Multi-file mode", f"{len(file_paths)} files")

        # Group files by language and process each group with correct parser
        multi_results = []
        lang_groups: dict[str, list[str]] = {}
        for fp in file_paths:
            lang = _get_language(fp) or language
            lang_groups.setdefault(lang, []).append(fp)

        for lang, group_files in lang_groups.items():
            group_parser = _get_parser(lang)
            group_results = process_multiple_files(
                group_files, group_parser, ghost_map,
                strip_comments=not keep_comments,
            )
            multi_results.extend(group_results)

        _step("AST parsed & renamed",
              f"{ghost_map.symbol_count} symbols across {len(file_paths)} files")

        # Collect stats from all files
        total_comments = sum(cc for _, _, _, cc in multi_results)
        if keep_comments:
            _step("Comments anonymized", f"{total_comments} anonymized")
        else:
            _step("Comments stripped", f"{total_comments} removed")

        # Use first file as primary ghost output
        ghost_source = multi_results[0][1]
        comment_count = total_comments

        # Write all files
        all_outputs = []
        for fpath, gsource, _, _ in multi_results:
            oname = f"ghost_{os.path.basename(fpath)}"
            with open(oname, "w", encoding="utf-8") as f:
                f.write(gsource)
            all_outputs.append(oname)
        _step("Files written", ", ".join(all_outputs))

    else:
        # ── Single-file pipeline ──────────────────────────────────
        ext = os.path.splitext(file_path)[1]

        with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False) as tmp:
            tmp.write(source_code)
            tmp_path = tmp.name

        try:
            # Step 1: Parse and handle comments
            parse_result = parser.parse(tmp_path)
            parse_result.file_path = file_path
            parse_result.source_code = source_code
            _step("AST parsed",
                  f"{len(parse_result.symbols)} symbols, "
                  f"{len(parse_result.comments)} comments")

            if keep_comments:
                # Keep comments — will anonymize after renaming
                clean_source = source_code
                comment_count = len(parse_result.comments)
                saved_comments = parse_result.comments
            else:
                stripper = CommentStripper()
                clean_source, comment_count = stripper.strip(
                    source_code, parse_result.comments
                )
                saved_comments = None
                _step("Comments stripped", f"{comment_count} removed")

            # Step 2: Re-parse clean source for accurate offsets
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(clean_source)

            clean_parse = parser.parse(tmp_path)
            clean_parse.file_path = file_path
            clean_parse.source_code = clean_source

            # Step 3: Rename symbols
            renamer = SymbolRenamer(ghost_map)
            ghost_source = renamer.rename(clean_parse)
            _step("Symbols renamed", f"{ghost_map.symbol_count} mapped")

            # Step 4: Anonymize comments (if keeping them)
            if keep_comments and saved_comments:
                anonymizer = CommentAnonymizer(ghost_map)
                # Re-parse the ghost source to find comment positions
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(ghost_source)
                ghost_parse = parser.parse(tmp_path)
                ghost_source, anon_count = anonymizer.anonymize(
                    ghost_source, ghost_parse.comments
                )
                _step("Comments anonymized", f"{anon_count} anonymized")

        finally:
            os.unlink(tmp_path)

    # ── Level 2+: Literal Scrubbing ──────────────────────────────
    scrub_result = None
    if level >= 2:
        scrubber = LiteralScrubber(ghost_map)
        original_names = {
            entry.original for entry in ghost_map._entries.values()
        }
        scrubber.set_known_symbols(original_names)
        scrub_result = scrubber.scrub(ghost_source, file_path)
        ghost_source = scrub_result.source
        _step("Literals scrubbed",
              f"{len(scrub_result.scrubbed)} scrubbed, "
              f"{len(scrub_result.flagged)} flagged, "
              f"{len(scrub_result.kept)} kept")

    # ── Level 4: Dimension Generalization ─────────────────────────
    dim_count = 0
    if level >= 4:
        ghost_source, dim_count = _generalize_dimensions(
            ghost_source, ghost_map, file_path
        )
        _step("Dimensions generalized", f"{dim_count} loop bounds")

    # ── Output ────────────────────────────────────────────────────
    if output is None:
        base = os.path.basename(file_path)
        output = f"ghost_{base}"

    if map_file is None:
        ext = ".ghost" if use_encryption else ".json"
        map_file = _generate_map_path(file_path).replace(".json", ext)

    if not multi_mode:
        with open(output, "w", encoding="utf-8") as f:
            f.write(ghost_source)

    # Store paths for one-click reveal: overwrite original + auto-detect ghost file
    ghost_map._metadata["original_file"] = os.path.abspath(file_path)
    ghost_map._metadata["ghost_file"] = os.path.abspath(output)
    ghost_map.save(map_file, passphrase=passphrase)

    # Clipboard
    copied = False
    if clipboard:
        copied = copy_to_clipboard(ghost_source)
        if copied:
            _step("Copied to clipboard", "ready to paste into AI")
        else:
            _warn("Clipboard unavailable — copy manually from output file")

    # ── Audit Log ─────────────────────────────────────────────────
    all_warnings = ghost_map.warnings
    audit.log_hide(
        source_files=list(file_paths),
        scrub_level=level,
        function_isolated=function if isolated else None,
        symbols_scrubbed=ghost_map.symbol_count,
        literals_scrubbed=len(scrub_result.scrubbed) if scrub_result else 0,
        literals_flagged=len(scrub_result.flagged) if scrub_result else 0,
        literals_kept=len(scrub_result.kept) if scrub_result else 0,
        comments_stripped=comment_count,
        warnings=all_warnings,
        ghost_output_path=output,
        map_path=map_file,
        ghost_output_content=ghost_source,
    )

    # ── Risk Report ───────────────────────────────────────────────
    if show_risk_report:
        analyzer = RiskAnalyzer()
        risk_report = analyzer.analyze(
            ghost_map=ghost_map,
            ghost_source=ghost_source,
            level=level,
            comment_count=comment_count,
            keep_comments=keep_comments,
            scrub_result=scrub_result,
            function_isolated=function if isolated else None,
            dim_count=dim_count,
            file_count=len(file_paths),
        )
        click.echo(format_risk_report_cli(risk_report))

        # Emit JSON for VS Code extension parsing
        import json as _json
        click.echo(f"RISK_REPORT_JSON: {_json.dumps(risk_report.to_dict())}")

    # ── Summary ───────────────────────────────────────────────────
    click.echo()
    _divider()
    click.secho("  HIDE COMPLETE", fg="green", bold=True)
    _divider()
    _info("Symbols renamed", str(ghost_map.symbol_count))
    if keep_comments:
        _info("Comments anonymized", str(comment_count))
    else:
        _info("Comments stripped", str(comment_count))
    if isolated:
        _info("Function isolated", function)
    if scrub_result:
        _info("Literals scrubbed", str(len(scrub_result.scrubbed)))
        if scrub_result.flagged:
            _info("Literals flagged", str(len(scrub_result.flagged)))
    if level >= 4:
        _info("Dimensions generalized", str(dim_count))
    if all_warnings:
        _info("Warnings", str(len(all_warnings)))
    if use_encryption:
        _info("Encryption", "enabled")
    click.echo()
    _info("Ghost output", output)
    _info("Map file", map_file)
    if copied:
        click.secho("\n  >> Ghost output is on your clipboard. Paste it into your AI. <<",
                     fg="green", bold=True)
    click.echo()

    # Show literal scrub details if any flagged
    if scrub_result and scrub_result.flagged:
        scrubber = LiteralScrubber(ghost_map)
        click.echo(scrubber.summary(scrub_result))


def _generalize_dimensions(source: str, ghost_map: GhostMap,
                           file_path: str) -> tuple[str, int]:
    """Level 4: Replace loop bound literals with ghost constants."""
    count = 0
    pattern = re.compile(
        r"(\bfor\s*\([^;]*;\s*\w+\s*[<>!=]+\s*)(\d+)(\s*;)"
    )

    def replacer(match):
        nonlocal count
        number = match.group(2)
        num_val = int(number)
        if num_val <= 1:
            return match.group(0)
        token = ghost_map.add_symbol(
            original=number, kind="constant",
            scope="loop_bound", source_file=file_path,
        )
        count += 1
        return match.group(1) + token + match.group(3)

    source = pattern.sub(replacer, source)

    py_pattern = re.compile(r"(range\s*\()(\d+)(\s*\))")

    def py_replacer(match):
        nonlocal count
        number = match.group(2)
        num_val = int(number)
        if num_val <= 1:
            return match.group(0)
        token = ghost_map.add_symbol(
            original=number, kind="constant",
            scope="loop_bound", source_file=file_path,
        )
        count += 1
        return match.group(1) + token + match.group(3)

    source = py_pattern.sub(py_replacer, source)
    return source, count


# ── REVEAL command ──────────────────────────────────────────────────

@main.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--map-file", "-m", type=click.Path(exists=True), required=True,
              help="Path to the ghost map file")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output file path for code (default: revealed_<filename>)")
@click.option("--sent", "-s", type=click.Path(exists=True), default=None,
              help="Original ghost file sent to AI (for diff analysis)")
@click.option("--mode", type=click.Choice(["code", "ai-response"]), default="code",
              help="Mode: 'code' for pure code files, 'ai-response' for full AI responses")
def reveal(file_path: str, map_file: str, output: str | None,
           sent: str | None, mode: str):
    """Restore original names from AI's response.

    Two modes:
      code         — pure code file, simple token replacement
      ai-response  — full AI response with prose + code blocks

    Examples:
      ghost reveal fixed.cpp -m .ghostcode/maps/sample_20240101.json
      ghost reveal ai_output.md -m map.json --mode ai-response --sent ghost_sample.cpp
    """
    from .reveal.code_revealer import CodeRevealer
    from .reveal.diff_analyzer import DiffAnalyzer
    from .reveal.explanation_translator import ExplanationTranslator

    _header("GHOST REVEAL")
    _info("Mode", mode)

    # Load map
    ghost_map = GhostMap.load(map_file)
    _step("Map loaded", f"{ghost_map.symbol_count} symbols from {map_file}")

    # Read input
    with open(file_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    revealer = CodeRevealer(ghost_map)

    if mode == "code":
        # ── Simple code reveal ────────────────────────────────────
        # Auto-detect the original ghost file from map metadata for annotation
        sent_code = None
        ghost_file_path = ghost_map._metadata.get("ghost_file", "")
        if sent:
            with open(sent, encoding="utf-8", errors="replace") as f:
                sent_code = f.read()
        elif ghost_file_path and os.path.exists(ghost_file_path):
            with open(ghost_file_path, encoding="utf-8", errors="replace") as f:
                sent_code = f.read()
            _step("Auto-detected ghost file", os.path.basename(ghost_file_path))

        # Diff analysis (run before reveal so we can pass result through)
        diff_result = None
        if sent_code:
            analyzer = DiffAnalyzer()
            diff_result = analyzer.analyze(sent_code, content)

        restored, count, new_symbols = revealer.reveal_code(
            content, original_ghost=sent_code, diff_result=diff_result
        )
        _step("Symbols restored", f"{count} tokens → original names")

        if new_symbols:
            _warn(f"{len(new_symbols)} new symbols detected (AI-introduced):")
            for sym in new_symbols:
                click.echo(f"       {sym} → NEW_{sym}")
            conf_color = {"HIGH": "green", "MEDIUM": "yellow", "LOW": "red"}.get(
                diff_result.confidence.value, "white"
            )
            _step("Diff analyzed",
                  f"{len(diff_result.changes)} changes, confidence: "
                  + click.style(diff_result.confidence.value, fg=conf_color))

        # Output — overwrite original file by default
        if output is None:
            original_file = ghost_map._metadata.get("original_file", "")
            if original_file and os.path.exists(os.path.dirname(original_file) or "."):
                output = original_file
            else:
                base = os.path.basename(file_path)
                output = f"revealed_{base}"

        with open(output, "w", encoding="utf-8") as f:
            f.write(restored)

        # Summary
        click.echo()
        _divider()
        click.secho("  REVEAL COMPLETE", fg="green", bold=True)
        _divider()
        _info("Symbols restored", str(count))
        _info("New symbols", f"{len(new_symbols)} (prefixed with NEW_)")
        if diff_result:
            _info("Confidence",
                  f"{diff_result.confidence.value} ({diff_result.confidence_score}/100)")
            if diff_result.changes:
                click.echo()
                click.secho("  Changes detected:", bold=True)
                for change in diff_result.changes:
                    icon = {
                        "modified": click.style("~", fg="yellow"),
                        "new_function": click.style("+", fg="green"),
                        "deleted_function": click.style("-", fg="red"),
                        "signature_change": click.style("!", fg="red"),
                        "new_variable": click.style("+", fg="green"),
                        "new_dependency": click.style("+", fg="cyan"),
                    }.get(change.type.value, "?")
                    click.echo(f"    [{icon}] {change.detail}")
        _info("Output", output)
        click.echo()

    else:
        # ── AI response reveal (zone-aware) ───────────────────────
        result = revealer.reveal_ai_response(content)
        _step("Zones parsed", f"{result.symbols_restored} symbols restored")

        # Explanation translator
        stubs = [
            token for token, entry in ghost_map._entries.items()
            if "(stub)" in (entry.scope or "")
        ]
        translator = ExplanationTranslator(ghost_map, stubs=stubs)
        annotated_explanation, annotations = translator.annotate(
            result.restored_explanation
        )
        _step("Explanation translated", f"{len(annotations)} annotations")

        # Diff analysis
        diff_result = None
        if sent:
            with open(sent, encoding="utf-8", errors="replace") as f:
                sent_code = f.read()
            analyzer = DiffAnalyzer()
            diff_result = analyzer.analyze(sent_code, result.restored_code)
            _step("Diff analyzed", f"confidence: {diff_result.confidence.value}")

        # Output files
        if output is None:
            base = os.path.splitext(os.path.basename(file_path))[0]
            output = f"revealed_{base}"

        code_output = output + os.path.splitext(file_path)[1]
        explanation_output = output + "_explanation.md"

        if result.restored_code:
            with open(code_output, "w", encoding="utf-8") as f:
                f.write(result.restored_code)

        with open(explanation_output, "w", encoding="utf-8") as f:
            f.write(annotated_explanation)

        # Summary
        click.echo()
        _divider()
        click.secho("  REVEAL COMPLETE", fg="green", bold=True)
        _divider()
        _info("Symbols restored", str(result.symbols_restored))
        _info("New symbols", str(len(result.new_symbols)))
        _info("Annotations", str(len(annotations)))
        if diff_result:
            _info("Confidence",
                  f"{diff_result.confidence.value} ({diff_result.confidence_score}/100)")
        if annotations:
            click.echo()
            click.secho("  Annotations:", bold=True)
            for ann in annotations:
                if ann.type == "naming_advice":
                    icon = click.style("~~", fg="yellow")
                else:
                    icon = click.style("!!", fg="red")
                click.echo(f"    [{icon}] {ann.note[:80]}")
        click.echo()
        if result.restored_code:
            _info("Code output", code_output)
        _info("Explanation", explanation_output)
        click.echo()


# ── MAP command ─────────────────────────────────────────────────────

@main.command("map")
@click.argument("map_file", type=click.Path(exists=True))
def show_map(map_file: str):
    """Inspect a ghost map file."""
    ghost_map = GhostMap.load(map_file)

    _header(f"GHOST MAP — {os.path.basename(map_file)}")
    _info("Total symbols", str(ghost_map.symbol_count))
    _info("Files", ", ".join(ghost_map._metadata.get("files", [])))
    click.echo()

    forward = ghost_map.forward_map()
    groups: dict[str, list[tuple[str, str]]] = {}
    prefix_names = {
        "gv": "Variables", "gf": "Functions", "gt": "Types",
        "gc": "Constants", "gs": "Strings", "gm": "Macros",
        "gn": "Namespaces",
    }
    prefix_colors = {
        "gv": "white", "gf": "cyan", "gt": "magenta",
        "gc": "yellow", "gs": "green", "gm": "red",
        "gn": "blue",
    }

    for token, original in sorted(forward.items()):
        prefix = token.split("_")[0]
        groups.setdefault(prefix, []).append((token, original))

    for prefix, items in groups.items():
        label = prefix_names.get(prefix, prefix)
        color = prefix_colors.get(prefix, "white")
        click.secho(f"  {label}:", fg=color, bold=True)
        for token, original in items:
            entry = ghost_map.get_entry(token)
            scope = click.style(f"  ({entry.scope})", dim=True) if entry and entry.scope else ""
            click.echo(f"    {click.style(token, fg=color)}  →  {original}{scope}")
        click.echo()

    if ghost_map.warnings:
        click.secho(f"  Warnings ({len(ghost_map.warnings)}):", fg="yellow", bold=True)
        for w in ghost_map.warnings:
            click.echo(f"    {w['type']}: {w['symbol']} (line {w['line']})")


# ── STATUS command ──────────────────────────────────────────────────

@main.command()
def status():
    """Show GhostCode status and recent activity."""
    config = load_config()
    audit = AuditLogger()

    _header("GHOSTCODE STATUS")
    _info("Version", __version__)

    # Config info
    click.echo()
    click.secho("  Configuration:", bold=True)
    from .config import _find_repo_config
    repo_config_path = _find_repo_config()
    if repo_config_path:
        _info("  Repo policy", repo_config_path)
    else:
        _info("  Repo policy", click.style("none", dim=True))
    user_config = os.path.join(os.path.expanduser("~"), ".ghostcode", "config.yaml")
    if os.path.exists(user_config):
        _info("  User config", user_config)
    else:
        _info("  User config", click.style("none", dim=True))
    _info("  Min level", str(config.min_scrub_level))
    _info("  Default level", str(config.default_scrub_level))
    _info("  Encrypt maps", str(config.encrypt_maps))
    _info("  Audit enforced", str(config.enforce_audit))
    if config.banned_patterns:
        _info("  Banned patterns", ", ".join(config.banned_patterns))

    # Active maps
    map_dir = os.path.join(".ghostcode", "maps")
    click.echo()
    if os.path.exists(map_dir):
        maps = [f for f in os.listdir(map_dir)
                if f.endswith(".json") or f.endswith(".ghost")]
        if maps:
            click.secho(f"  Active Maps ({len(maps)}):", bold=True)
            for m in sorted(maps, reverse=True)[:5]:
                mpath = os.path.join(map_dir, m)
                size = os.path.getsize(mpath)
                if m.endswith(".ghost"):
                    tag = click.style("encrypted", fg="green")
                else:
                    tag = click.style("plaintext", fg="yellow")
                click.echo(f"    {m} ({size} bytes, {tag})")
        else:
            click.secho("  Active Maps: none", dim=True)
    else:
        click.secho("  Active Maps: none", dim=True)

    # Recent audit
    entries = audit.get_recent_entries(5)
    click.echo()
    if entries:
        click.secho(f"  Recent Activity ({len(entries)}):", bold=True)
        for entry in reversed(entries):
            ts = entry.get("timestamp", "?")[:19]
            action = entry.get("action", "?")
            if action == "hide":
                files = entry.get("source_files", [])
                lvl = entry.get("scrub_level", "?")
                syms = entry.get("symbols_scrubbed", 0)
                click.echo(
                    f"    {click.style(ts, dim=True)}  "
                    f"{click.style('HIDE', fg='cyan')}  "
                    f"L{lvl}  {syms} symbols  {', '.join(files)}"
                )
            elif action == "reveal":
                restored = entry.get("symbols_restored", 0)
                conf = entry.get("confidence", "?")
                click.echo(
                    f"    {click.style(ts, dim=True)}  "
                    f"{click.style('REVEAL', fg='green')}  "
                    f"{restored} restored  confidence={conf}"
                )
    else:
        click.secho("  Recent Activity: none", dim=True)
    click.echo()


# ── DEMO command ────────────────────────────────────────────────────

@main.command()
@click.option("--lang", type=click.Choice(["cpp", "python"]), default="python",
              help="Demo language (default: python)")
def demo(lang: str):
    """Run an interactive GhostCode demo.

    Shows the full hide → AI → reveal workflow with a real code sample.
    Perfect for hackathon presentations and onboarding.
    """
    import time

    # Find fixture
    fixture_dir = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")
    if not os.path.exists(fixture_dir):
        fixture_dir = os.path.join(os.path.dirname(__file__), "fixtures")
    fixture = os.path.join(fixture_dir, f"sample.{'py' if lang == 'python' else 'cpp'}")

    if not os.path.exists(fixture):
        _error(f"Demo fixture not found at {fixture}. Run from project root.")

    click.echo(click.style(BANNER, fg="cyan", bold=True))
    click.secho("  Privacy Proxy for Developers", fg="white", bold=True)
    click.secho("  Your code stays anonymous. Your logic stays intact.\n", fg="white", dim=True)

    # Read original
    with open(fixture, encoding="utf-8", errors="replace") as f:
        original = f.read()

    # ── Step 1: Show original ─────────────────────────────────────
    click.secho("  STEP 1: Your original code (CONFIDENTIAL)", fg="red", bold=True)
    _divider()
    _show_code_preview(original, lang, max_lines=20)
    click.echo()
    _pause("Press Enter to see what GhostCode does...")

    # ── Step 2: Run hide ──────────────────────────────────────────
    click.secho("\n  STEP 2: ghost hide (stripping business context)", fg="cyan", bold=True)
    _divider()

    parser = _get_parser(lang if lang == "python" else "cpp")
    ext = ".py" if lang == "python" else ".cpp"

    with tempfile.NamedTemporaryFile(mode="w", suffix=ext, delete=False) as tmp:
        tmp.write(original)
        tmp_path = tmp.name

    try:
        parse_result = parser.parse(tmp_path)
        parse_result.source_code = original
        parse_result.file_path = f"sample{ext}"

        # Strip comments
        stripper = CommentStripper()
        clean_source, comment_count = stripper.strip(original, parse_result.comments)
        _step("Comments stripped", f"{comment_count} removed")
        time.sleep(0.3)

        # Re-parse
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(clean_source)
        clean_parse = parser.parse(tmp_path)
        clean_parse.source_code = clean_source
        clean_parse.file_path = f"sample{ext}"

        # Rename
        ghost_map = GhostMap()
        renamer = SymbolRenamer(ghost_map)
        ghost_source = renamer.rename(clean_parse)
        _step("Symbols renamed", f"{ghost_map.symbol_count} → ghost tokens")
        time.sleep(0.3)

        # Literal scrub
        scrubber = LiteralScrubber(ghost_map)
        original_names = {e.original for e in ghost_map._entries.values()}
        scrubber.set_known_symbols(original_names)
        scrub_result = scrubber.scrub(ghost_source, f"sample{ext}")
        ghost_source = scrub_result.source
        _step("Literals scrubbed",
              f"{len(scrub_result.scrubbed)} domain fingerprints removed")
        time.sleep(0.3)

    finally:
        os.unlink(tmp_path)

    click.echo()
    click.secho("  Ghost output (safe to send to ANY AI):", fg="green", bold=True)
    _divider()
    _show_code_preview(ghost_source, lang, max_lines=20)
    click.echo()
    _pause("Press Enter to see the mapping...")

    # ── Step 3: Show map ──────────────────────────────────────────
    click.secho("\n  STEP 3: Ghost Map (your private key)", fg="magenta", bold=True)
    _divider()
    forward = ghost_map.forward_map()
    shown = 0
    for token, orig in sorted(forward.items()):
        if shown >= 10:
            remaining = len(forward) - shown
            click.secho(f"    ... and {remaining} more", dim=True)
            break
        entry = ghost_map.get_entry(token)
        kind = entry.kind if entry else "?"
        click.echo(
            f"    {click.style(token, fg='cyan')}  →  "
            f"{click.style(orig, fg='white', bold=True)}  "
            f"{click.style(f'({kind})', dim=True)}"
        )
        shown += 1

    click.echo()
    _pause("Press Enter to see the reveal...")

    # ── Step 4: Simulate AI response and reveal ───────────────────
    click.secho("\n  STEP 4: AI responds → ghost reveal restores your names", fg="green", bold=True)
    _divider()

    # Simulate: reveal the ghost source back (as if AI returned it unchanged)
    from .reveal.code_revealer import CodeRevealer
    revealer = CodeRevealer(ghost_map)
    restored, count, new_syms = revealer.reveal_code(ghost_source)
    _step("Symbols restored", f"{count} ghost tokens → original names")

    click.echo()
    click.secho("  Restored code (back to YOUR names):", fg="green", bold=True)
    _divider()
    _show_code_preview(restored, lang, max_lines=15)

    # ── Final pitch ───────────────────────────────────────────────
    click.echo()
    _divider()
    click.secho("  GhostCode doesn't make your code invisible.", fg="white", bold=True)
    click.secho("  It makes your code anonymous.", fg="cyan", bold=True)
    click.echo()
    click.secho("  Features:", bold=True)
    click.echo("    • AST-based parsing (not regex) — understands your code structure")
    click.echo("    • 4 privacy levels — from name+comment stripping to full isolation")
    click.echo("    • Smart literal classification — scrubs domains, keeps math constants")
    click.echo("    • Zone-aware reveal — handles AI prose, code blocks, inline code")
    click.echo("    • Map encryption — AES-encrypted mapping files")
    click.echo("    • Audit logging — compliance-ready with SHA-256 hashes")
    click.echo("    • Clipboard integration — paste directly into ChatGPT/Claude")
    click.echo()
    click.secho("  ghost hide app.py && paste into AI && ghost reveal response.md", fg="cyan")
    click.echo()


def _show_code_preview(code: str, lang: str, max_lines: int = 20):
    """Show a syntax-highlighted code preview."""
    lines = code.split("\n")
    for i, line in enumerate(lines[:max_lines]):
        lineno = click.style(f"  {i + 1:3d} │ ", dim=True)
        click.echo(f"  {lineno}{line}")
    if len(lines) > max_lines:
        click.secho(f"        ... ({len(lines) - max_lines} more lines)", dim=True)


def _pause(msg: str):
    """Pause for demo mode."""
    click.secho(f"  {msg}", fg="yellow", dim=True)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        click.echo()


if __name__ == "__main__":
    main()
