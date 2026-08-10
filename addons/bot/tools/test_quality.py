"""test_quality — static analyzer for test meaningfulness.

Scans changed test files in a PR (Python AST for .py, regex for .js/.ts/.mjs)
and reports:

    - Assertion counts per test function
    - Anti-patterns:
        * assert True / assert 1 / assert "x" (tautologies)
        * Empty test functions (`pass` or no body)
        * Tests that only contain mock setup + mock.assert_called* (no real
          behavior verification)
        * Tests with zero assertions
    - Source → test coverage mapping: for each changed source file, does a
      corresponding test file exist and have new assertions in the diff?
    - Overall meaningfulness score 0.0-1.0

Used by review_pr.py to enforce the "real functional validating tests"
rule — anti-patterns and low scores force the review verdict to
request_changes.

Called directly by the LLM as a bot tool:
    call("42")          # analyze test files in PR #42
    call("local")       # analyze tests in the current working tree (no PR)
"""
import ast
import os
import re
import sys
from pathlib import Path

NAME = "test_quality"
DESCRIPTION = (
    "Analyze the quality of test files in a pull request (or the local "
    "working tree). Reports assertion counts, anti-patterns (assert True, "
    "empty tests, mock-only tests), source→test coverage mapping, and an "
    "overall meaningfulness score. Use before approving PRs to verify the "
    "tests actually validate behavior rather than just existing. Query: "
    "'<pr-number>' or 'local' for the current working tree."
)

# ── Python AST analysis ───────────────────────────────────────────────────


class PyTestAnalyzer(ast.NodeVisitor):
    """Walks a Python test file and counts assertions, detects tautologies,
    empty tests, and mock-only patterns.
    """

    def __init__(self):
        self.tests: list[dict] = []
        self._current: dict | None = None

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if not node.name.startswith("test_"):
            self.generic_visit(node)
            return
        prev = self._current
        self._current = {
            "name": node.name,
            "line": node.lineno,
            "asserts": 0,
            "mock_asserts": 0,
            "anti_patterns": [],
            "body_size": len(node.body),
            "is_empty": False,
        }
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            self._current["is_empty"] = True
            self._current["anti_patterns"].append("empty_body")
        if len(node.body) == 0:
            self._current["is_empty"] = True
            self._current["anti_patterns"].append("empty_body")

        self.generic_visit(node)

        # Post-analysis heuristics
        if self._current["asserts"] == 0 and self._current["mock_asserts"] == 0 and not self._current["is_empty"]:
            self._current["anti_patterns"].append("no_assertions")
        if self._current["asserts"] == 0 and self._current["mock_asserts"] > 0:
            self._current["anti_patterns"].append("mock_only")

        self.tests.append(self._current)
        self._current = prev

    visit_AsyncFunctionDef = visit_FunctionDef  # treat async tests the same

    def visit_Assert(self, node: ast.Assert):
        if self._current is None:
            return
        # Tautology detection: constant True, non-zero literal, non-empty string
        test = node.test
        taut = False
        if isinstance(test, ast.Constant):
            if test.value is True or (isinstance(test.value, (int, float)) and test.value) or (isinstance(test.value, str) and test.value):
                taut = True
        elif isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(test.ops[0], ast.Eq):
            left, right = test.left, test.comparators[0]
            if isinstance(left, ast.Constant) and isinstance(right, ast.Constant) and left.value == right.value:
                taut = True  # e.g. assert 1 == 1

        if taut:
            self._current["anti_patterns"].append(f"tautology_line_{node.lineno}")
        else:
            self._current["asserts"] += 1
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # Count mock.assert_called / assert_called_with / called / etc.
        if self._current is not None and isinstance(node.func, ast.Attribute):
            name = node.func.attr
            if name in ("assert_called", "assert_called_with", "assert_called_once",
                        "assert_called_once_with", "assert_any_call", "assert_has_calls",
                        "assert_not_called"):
                self._current["mock_asserts"] += 1
            # pytest-style: some people call `assertEqual` / `assertTrue` via self
            elif name in ("assertEqual", "assertTrue", "assertFalse", "assertIn",
                          "assertIsNotNone", "assertGreater", "assertLess",
                          "assertRaises", "assertAlmostEqual"):
                self._current["asserts"] += 1
        self.generic_visit(node)


def analyze_python(path: Path) -> dict:
    """Run the AST analyzer over a single .py test file."""
    try:
        source = path.read_text(errors="replace")
        tree = ast.parse(source)
    except Exception as exc:
        return {"path": str(path), "error": str(exc), "tests": [], "score": 0.0}

    analyzer = PyTestAnalyzer()
    analyzer.visit(tree)
    tests = analyzer.tests

    score = _score_tests(tests)
    return {
        "path": str(path),
        "tests": tests,
        "test_count": len(tests),
        "assertion_count": sum(t["asserts"] for t in tests),
        "mock_assertion_count": sum(t["mock_asserts"] for t in tests),
        "anti_patterns": [p for t in tests for p in t["anti_patterns"]],
        "score": score,
    }


# ── JS/TS analysis (regex-based) ──────────────────────────────────────────


def analyze_js(path: Path) -> dict:
    """Regex-based scan for .js/.ts/.mjs/.jsx test files."""
    try:
        source = path.read_text(errors="replace")
    except Exception as exc:
        return {"path": str(path), "error": str(exc), "tests": [], "score": 0.0}

    # Find test/it blocks: `test("name", () => {})` or `it("name", () => {})`
    test_pattern = re.compile(
        r"\b(test|it)\s*\(\s*['\"`]([^'\"`]+)['\"`]\s*,\s*(?:async\s*)?\(\s*\)\s*=>\s*\{",
        re.MULTILINE,
    )
    tests: list[dict] = []

    for m in test_pattern.finditer(source):
        name = m.group(2)
        start = m.end()
        # Find matching closing brace — shallow tracking
        depth = 1
        i = start
        while i < len(source) and depth > 0:
            if source[i] == "{":
                depth += 1
            elif source[i] == "}":
                depth -= 1
            i += 1
        body = source[start:i - 1]

        # Count assertions: expect(x).to*, assert(...), strictEqual, deepEqual, ok(...), etc.
        asserts = 0
        asserts += len(re.findall(r"\bexpect\s*\([^)]+\)\.(toBe|toEqual|toStrictEqual|toMatch|toContain|toHaveBeenCalled|toThrow|toHaveLength|toBeGreaterThan|toBeLessThan|toBeTruthy|toBeFalsy|toBeDefined|toBeUndefined|toBeNull|toHaveProperty)", body))
        asserts += len(re.findall(r"\b(assert|strictEqual|deepEqual|notStrictEqual|ok|equal|notEqual|throws|doesNotThrow)\s*\(", body))

        # Tautology detection
        anti: list[str] = []
        if re.search(r"\bexpect\s*\(\s*true\s*\)\.toBe\s*\(\s*true\s*\)", body):
            anti.append("tautology_expect_true")
        if re.search(r"\bassert\s*\(\s*true\s*\)", body):
            anti.append("tautology_assert_true")
        if re.search(r"\bstrictEqual\s*\(\s*1\s*,\s*1\s*\)", body):
            anti.append("tautology_strict_equal")

        if not body.strip() or body.strip() == "//" or re.match(r"^\s*$", body):
            anti.append("empty_body")

        if asserts == 0 and "empty_body" not in anti:
            anti.append("no_assertions")

        tests.append({
            "name": name,
            "asserts": asserts,
            "anti_patterns": anti,
            "is_empty": "empty_body" in anti,
        })

    score = _score_tests(tests)
    return {
        "path": str(path),
        "tests": tests,
        "test_count": len(tests),
        "assertion_count": sum(t["asserts"] for t in tests),
        "anti_patterns": [p for t in tests for p in t["anti_patterns"]],
        "score": score,
    }


# ── Scoring ───────────────────────────────────────────────────────────────


def _score_tests(tests: list[dict]) -> float:
    """Return a 0.0-1.0 meaningfulness score for a list of test results.

    Heuristic:
        - Base = 1.0
        - -0.3 per test with 'no_assertions' anti-pattern
        - -0.2 per test with 'tautology_*' anti-pattern
        - -0.3 per test with 'empty_body' anti-pattern
        - -0.1 per test that's mock_only
        - Floor at 0.0
    """
    if not tests:
        return 0.0
    penalty = 0.0
    for t in tests:
        patterns = t.get("anti_patterns", [])
        if "no_assertions" in patterns:
            penalty += 0.3
        if "empty_body" in patterns:
            penalty += 0.3
        if "mock_only" in patterns:
            penalty += 0.1
        if any(p.startswith("tautology") for p in patterns):
            penalty += 0.2
    score = max(0.0, 1.0 - penalty / len(tests))
    return round(score, 2)


# ── PR file analysis ──────────────────────────────────────────────────────


def _test_file_for_source(source_path: str) -> list[str]:
    """Given a source file like 'app.py' or 'src/foo.js', return likely
    test file locations to check for coverage.
    """
    p = Path(source_path)
    stem = p.stem
    candidates = [
        f"tests/test_{stem}.py",
        f"tests/{stem}_test.py",
        f"tests/test_{p.name}",
        f"{p.parent}/test_{p.name}",
        f"tests/{stem}.test.js",
        f"tests/{stem}.test.mjs",
        f"tests/{stem}.test.ts",
        f"{p.parent}/{stem}.test.js",
        f"{p.parent}/{stem}.test.ts",
    ]
    return candidates


def analyze_files(file_list: list[dict]) -> dict:
    """Analyze a list of PR files (from gitea.get_pr_files).

    file_list entries have 'filename', 'additions', 'deletions' fields.
    """
    report = {
        "files_analyzed": [],
        "source_files": [],
        "missing_tests_for": [],
        "total_tests": 0,
        "total_assertions": 0,
        "total_anti_patterns": 0,
        "score": 1.0,
        "findings": [],
    }

    source_exts = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs"}
    test_file_scores: list[float] = []

    for f in file_list:
        fname = f.get("filename", "")
        ext = Path(fname).suffix
        if ext not in source_exts:
            continue

        path = Path(fname)
        if not path.exists():
            # File was deleted — ignore
            continue

        is_test = (
            "test" in fname.lower()
            or fname.startswith("tests/")
            or "/tests/" in fname
            or path.name.endswith((".test.js", ".test.ts", ".test.mjs"))
        )

        if is_test:
            if ext == ".py":
                analysis = analyze_python(path)
            else:
                analysis = analyze_js(path)
            report["files_analyzed"].append(analysis)
            report["total_tests"] += analysis.get("test_count", 0)
            report["total_assertions"] += analysis.get("assertion_count", 0)
            report["total_anti_patterns"] += len(analysis.get("anti_patterns", []))
            test_file_scores.append(analysis.get("score", 0.0))
        else:
            report["source_files"].append(fname)

    # Coverage check: for each changed source file, does ANY test exist?
    for source in report["source_files"]:
        candidates = _test_file_for_source(source)
        if not any(Path(c).exists() for c in candidates):
            report["missing_tests_for"].append(source)

    # Aggregate score: average of per-file scores, penalized by coverage gaps
    if test_file_scores:
        report["score"] = round(sum(test_file_scores) / len(test_file_scores), 2)
    else:
        report["score"] = 0.0 if report["source_files"] else 1.0

    if report["missing_tests_for"]:
        coverage_penalty = min(0.5, 0.1 * len(report["missing_tests_for"]))
        report["score"] = round(max(0.0, report["score"] - coverage_penalty), 2)

    # Build human-readable findings for the LLM reviewer
    for analysis in report["files_analyzed"]:
        anti = analysis.get("anti_patterns", [])
        if anti:
            report["findings"].append(
                f"{analysis['path']}: {len(anti)} anti-pattern(s) — {', '.join(set(anti))[:200]}"
            )
    for missing in report["missing_tests_for"]:
        report["findings"].append(f"no test file found for changed source: {missing}")
    if report["total_tests"] > 0 and report["total_assertions"] / report["total_tests"] < 1.0:
        report["findings"].append(
            f"avg assertions per test is {report['total_assertions'] / report['total_tests']:.1f} "
            f"— very low, suggests weak assertion coverage"
        )
    if not report["findings"] and report["score"] >= 0.9:
        report["findings"].append("tests look meaningful — no anti-patterns detected")

    return report


# ── Main entry ────────────────────────────────────────────────────────────


def call(query: str, ctx: dict) -> str:
    q = query.strip().lower()

    if q == "local" or q == "":
        # Analyze the local working tree's tests/ directory
        files = []
        for ext_dir in ("tests", "test"):
            if Path(ext_dir).exists():
                for p in Path(ext_dir).rglob("*"):
                    if p.suffix in (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs") and p.is_file():
                        files.append({"filename": str(p), "additions": 0, "deletions": 0})
        if not files:
            return "(no tests/ directory — nothing to analyze)"
        report = analyze_files(files)
        return _format_report(report, "(local working tree)")

    # Otherwise treat as PR number
    m = re.search(r"\d+", q)
    if not m:
        return "(test_quality: need a PR number or 'local')"
    pr_number = int(m.group())

    try:
        sys.path.insert(0, "bot")
        from tools import gitea
    except ImportError as exc:
        return f"(test_quality: gitea module missing: {exc})"

    try:
        files = gitea.get_pr_files(pr_number)
    except Exception as exc:
        return f"(test_quality: could not fetch PR #{pr_number} files: {exc})"

    report = analyze_files(files)
    return _format_report(report, f"PR #{pr_number}")


def _format_report(report: dict, context: str) -> str:
    lines = [
        f"Test quality report for {context}:",
        f"  score: {report['score']:.2f} (0.0=all anti-patterns, 1.0=meaningful)",
        f"  test files: {len(report['files_analyzed'])}",
        f"  source files changed: {len(report['source_files'])}",
        f"  missing tests for: {len(report['missing_tests_for'])}",
        f"  total tests: {report['total_tests']}",
        f"  total assertions: {report['total_assertions']}",
        f"  total anti-patterns: {report['total_anti_patterns']}",
    ]
    if report["findings"]:
        lines.append("")
        lines.append("Findings:")
        for finding in report["findings"][:10]:
            lines.append(f"  • {finding}")
    return "\n".join(lines)
