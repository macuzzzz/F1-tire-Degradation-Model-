"""Phase 9 review pass of the public API of src/tyredeg (DECISIONS.md D86).

For every public function, method and class it checks:

1. the NumPy docstring sections required by CLAUDE.md rule 5 (Parameters if
   the function takes arguments, Returns if it returns a value, Raises,
   Example/Examples; a class only needs an Example);
2. whether the function validates its inputs, i.e. contains a ``raise`` or
   calls (directly or through other package functions) a function that does.

Check 2 is a heuristic: it matches called functions BY NAME only, so a call to
a validating method with a common name (e.g. ``fit``) counts even if the
object is not validated. Treat "validates = no" as "look at it by hand", not
as proof of a bug.

Usage:  .venv\\Scripts\\python scripts/review_api.py
Writes: reports/phase9_api_review.csv  (one row per public object)
"""

import ast
import re
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "src" / "tyredeg"
OUTPUT = REPO_ROOT / "reports" / "phase9_api_review.csv"

# A NumPy section is a title line followed by a line of dashes.
SECTION_PATTERN = re.compile(r"^\s*(Parameters|Returns|Yields|Raises|Examples?)\s*\n\s*-{3,}", re.M)


def docstring_sections(docstring):
    """Set of section titles found in a docstring ("Examples" counted as "Example")."""
    found = set()
    for match in SECTION_PATTERN.finditer(docstring or ""):
        title = match.group(1)
        found.add("Example" if title.startswith("Example") else title)
    return found


def argument_names(function):
    names = [arg.arg for arg in function.args.args + function.args.kwonlyargs]
    if function.args.vararg:
        names.append(function.args.vararg.arg)
    return [name for name in names if name not in ("self", "cls")]


def returns_a_value(function):
    for node in ast.walk(function):
        if isinstance(node, ast.Return) and node.value is not None:
            return True
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
    return False


def called_names(function):
    names = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                names.add(node.func.attr)
    return names


def contains_raise(function):
    return any(isinstance(node, ast.Raise) for node in ast.walk(function))


def all_functions():
    """Every function definition in the package (public and private), by name."""
    by_name = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                by_name.setdefault(node.name, []).append(node)
    return by_name


def validating_names(by_name):
    """Names of functions that raise, directly or through functions they call."""
    validating = {name for name, nodes in by_name.items() if any(contains_raise(node) for node in nodes)}
    # Repeat until no new name is added (a fixed point of "calls a validating function").
    changed = True
    while changed:
        changed = False
        for name, nodes in by_name.items():
            if name in validating:
                continue
            if any(called_names(node) & validating for node in nodes):
                validating.add(name)
                changed = True
    return validating


def public_objects():
    """Yield (path, line, name, kind, ast node) for each public object."""
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            # Only top-level functions and classes with a public (no underscore) name.
            if not isinstance(node, (ast.FunctionDef, ast.ClassDef)) or node.name.startswith("_"):
                continue
            if isinstance(node, ast.FunctionDef):
                yield relative, node.lineno, node.name, "function", node
            elif isinstance(node, ast.ClassDef):
                yield relative, node.lineno, node.name, "class", node
                for item in node.body:
                    if not isinstance(item, ast.FunctionDef) or item.name.startswith("_"):
                        continue
                    decorators = {getattr(d, "id", getattr(d, "attr", "")) for d in item.decorator_list}
                    if "property" in decorators:
                        continue  # documented like an attribute
                    yield relative, item.lineno, f"{node.name}.{item.name}", "method", item


def review():
    by_name = all_functions()
    validating = validating_names(by_name)
    rows = []
    for path, line, name, kind, node in public_objects():
        docstring = ast.get_docstring(node)
        found = docstring_sections(docstring)
        if docstring is None:
            missing = ["docstring"]
        elif kind == "class":
            missing = [] if "Example" in found else ["Example"]
        else:
            required = ["Raises", "Example"]
            if argument_names(node):
                required.insert(0, "Parameters")
            if returns_a_value(node):
                required.insert(1 if argument_names(node) else 0, "Returns")
            missing = [section for section in required
                       if section not in found and not (section == "Returns" and "Yields" in found)]
        takes_arguments = kind != "class" and bool(argument_names(node))
        validates = "n/a" if not takes_arguments else ("yes" if node.name in validating else "no")
        rows.append({"file": path, "line": line, "name": name, "kind": kind,
                     "missing_sections": ", ".join(missing), "validates_inputs": validates})
    return pd.DataFrame(rows)


def main():
    table = review()
    OUTPUT.parent.mkdir(exist_ok=True)
    table.to_csv(OUTPUT, index=False)
    incomplete = table[table["missing_sections"] != ""]
    no_checks = table[table["validates_inputs"] == "no"]
    print(f"Public objects reviewed: {len(table)}")
    print(f"Incomplete docstrings:   {len(incomplete)}")
    print(f"No input validation found (check by hand): {len(no_checks)}")
    for row in no_checks.itertuples():
        print(f"  {row.file}:{row.line}  {row.name}")
    print(f"Written to {OUTPUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
