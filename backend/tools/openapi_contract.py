"""The backend's contract with the frontend: what each endpoint answers, committed.

``frontend/openapi.json`` is what the frontend's contract gate
(``frontend/scripts/check-contract.ts``, run by ``make front-contract``)
compares the frontend's hand-written types with. It lives under ``frontend/``
so a backend change that rewrites it also runs the frontend's gates.

It is the part of the app's OpenAPI document that gate reads, and nothing
else: each path's operations, the schema of each one's 2xx JSON answer, and
the component schemas those reach, each schema cut to its shape (``SHAPE``:
its fields, items, members and references). A description, a title, an
example, a request body or a parameter is not in it, so changing one leaves
the file alone.

``make back-build`` runs ``--check``: an answer whose shape changed without
the contract being regenerated fails the build, naming the command that
fixes it. Keys are sorted and two-space indented, so the same app always
writes the same bytes and a diff reads field by field.

Usage (from ``backend/``)::

    python -m tools.openapi_contract --write   # regenerate (make openapi)
    python -m tools.openapi_contract --check   # fail when stale (make back-build)
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

CONTRACT = Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
REGENERATE = "make openapi"
METHODS = ("get", "post", "put", "patch", "delete")
# What a schema keeps: what `frontend/scripts/contract/` walks, and the other
# places a schema nests one (a tuple's `prefixItems`, a record's
# `propertyNames`), so a component reached only there is in the contract too.
SHAPE = (
    "$ref",
    "type",
    "properties",
    "items",
    "prefixItems",
    "additionalProperties",
    "propertyNames",
    "anyOf",
    "oneOf",
    "allOf",
)
REF_PREFIX = "#/components/schemas/"


def shape(schema: Any) -> Any:
    """A schema cut to ``SHAPE``, all the way down (``additionalProperties``
    may be a bare boolean, which stays as it is)."""
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for key in SHAPE:
        if key not in schema:
            continue
        value = schema[key]
        if key == "properties":
            out[key] = {name: shape(field) for name, field in value.items()}
        elif key in ("anyOf", "oneOf", "allOf", "prefixItems"):
            out[key] = [shape(member) for member in value]
        elif key in ("items", "additionalProperties", "propertyNames"):
            out[key] = shape(value)
        else:
            out[key] = value
    return out


def _answers(operation: dict[str, Any]) -> dict[str, Any]:
    """An operation's 2xx answers that carry JSON, as their shape."""
    answers = {}
    for code, response in operation.get("responses", {}).items():
        schema = response.get("content", {}).get("application/json", {}).get("schema")
        if code.startswith("2") and schema is not None:
            answers[code] = {"content": {"application/json": {"schema": shape(schema)}}}
    return answers


def _refs(schema: Any) -> list[str]:
    """The component names a shaped schema points at, directly or nested."""
    if isinstance(schema, list):
        return [name for member in schema for name in _refs(member)]
    if not isinstance(schema, dict):
        return []
    found = [schema["$ref"].removeprefix(REF_PREFIX)] if "$ref" in schema else []
    for key, value in schema.items():
        if key == "properties":
            found += [name for field in value.values() for name in _refs(field)]
        elif key != "$ref":
            found += _refs(value)
    return found


def contract(spec: dict[str, Any]) -> dict[str, Any]:
    """The part of the app's OpenAPI document the frontend's gate reads."""
    paths: dict[str, Any] = {}
    for path, item in spec.get("paths", {}).items():
        operations = {m: {"responses": _answers(item[m])} for m in METHODS if m in item}
        if operations:
            paths[path] = operations
    components = spec.get("components", {}).get("schemas", {})
    reached: dict[str, Any] = {}
    queue = _refs(list(paths.values()))
    while queue:
        name = queue.pop()
        if name in reached or name not in components:
            continue
        reached[name] = shape(components[name])
        queue += _refs(reached[name])
    return {"paths": paths, "components": {"schemas": reached}}


def render(spec: dict[str, Any]) -> str:
    """The contract's file: sorted keys, two-space indent, a final newline."""
    return json.dumps(contract(spec), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def is_current(spec: dict[str, Any], path: Path) -> bool:
    """Whether the committed file says what the app says (compared as JSON,
    so a formatter touching the file changes nothing)."""
    try:
        committed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError, json.JSONDecodeError:
        return False
    return committed == json.loads(render(spec))


def _spec() -> dict[str, Any]:
    """The app's OpenAPI document. Importing ``main`` is also the build check."""
    from main import app

    return app.openapi()


def main(argv: list[str], spec: dict[str, Any] | None = None, path: Path = CONTRACT) -> int:
    """Write or check the contract; ``spec`` and ``path`` are for the tests."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate frontend/openapi.json")
    mode.add_argument("--check", action="store_true", help="fail when it is stale")
    args = parser.parse_args(argv)

    spec = _spec() if spec is None else spec
    if args.write:
        path.write_text(render(spec), encoding="utf-8")
        print(f"openapi contract: wrote {path.name}")
        return 0
    if not is_current(spec, path):
        print(
            f"openapi contract: {path.name} is missing or does not match what the endpoints"
            " answer: an answer's shape (a field, a type, an endpoint) changed without it."
            f" Run `{REGENERATE}` and commit the file; the frontend's contract gate then"
            " judges the change.",
            file=sys.stderr,
        )
        return 1
    print(f"openapi contract: {path.name} is current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
