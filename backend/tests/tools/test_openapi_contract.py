"""The committed OpenAPI contract: what it keeps, and when it is stale."""

import json
from pathlib import Path

from tools import openapi_contract as oc

ROW = {
    "title": "Row",
    "description": "A row.",
    "type": "object",
    "required": ["id"],
    "properties": {
        "id": {"type": "string", "format": "uuid", "title": "Id"},
        "tags": {"type": "array", "items": {"$ref": "#/components/schemas/Tag"}},
        "note": {"anyOf": [{"type": "string"}, {"type": "null"}], "examples": ["x"]},
    },
}


def _spec(**schemas: dict) -> dict:
    """An app with one list endpoint answering ``Row``s, and a DELETE with no body."""
    answer = {"type": "array", "items": {"$ref": "#/components/schemas/Row"}}
    return {
        "openapi": "3.1.0",
        "info": {"title": "app", "version": "1"},
        "paths": {
            "/rows": {
                "get": {
                    "summary": "List rows",
                    "parameters": [{"name": "page", "in": "query"}],
                    "responses": {
                        "200": {"content": {"application/json": {"schema": answer}}},
                        "422": {"content": {"application/json": {"schema": {"type": "object"}}}},
                    },
                },
                "delete": {"responses": {"204": {"description": "gone"}}},
            },
        },
        "components": {"schemas": {"Row": ROW, **schemas}},
    }


def test_shape_keeps_fields_items_members_and_refs_only():
    assert oc.shape(ROW) == {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "tags": {"type": "array", "items": {"$ref": "#/components/schemas/Tag"}},
            "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    }
    assert oc.shape({"type": "object", "additionalProperties": True}) == {
        "type": "object",
        "additionalProperties": True,
    }


def test_contract_keeps_2xx_json_answers_and_the_components_they_reach():
    tag = {"type": "object", "properties": {"label": {"type": "string"}}}
    unused = {"type": "object", "properties": {"secret": {"type": "string"}}}
    result = oc.contract(_spec(Tag=tag, Unused=unused))
    assert result["paths"]["/rows"] == {
        "get": {
            "responses": {
                "200": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Row"},
                            }
                        }
                    }
                }
            }
        },
        "delete": {"responses": {}},
    }
    # `Tag` is reached through `Row`; `Unused` is no answer's, so it is left out.
    assert sorted(result["components"]["schemas"]) == ["Row", "Tag"]


def test_render_is_stable_and_sorted():
    spec = _spec(Tag={"type": "object"})
    text = oc.render(spec)
    assert text == oc.render(json.loads(json.dumps(spec)))
    assert text.endswith("}\n")
    assert text.index('"components"') < text.index('"paths"')


def test_check_passes_when_current_and_fails_naming_the_fix(tmp_path: Path, capsys):
    path = tmp_path / "openapi.json"
    spec = _spec(Tag={"type": "object"})
    assert oc.main(["--check"], spec, path) == 1
    assert oc.main(["--write"], spec, path) == 0
    assert oc.main(["--check"], spec, path) == 0
    # A description changing leaves the contract current; a field does not.
    documented = {**ROW, "description": "Another description."}
    assert oc.main(["--check"], _spec(Row=documented, Tag={"type": "object"}), path) == 0
    grown = {**ROW, "properties": {**ROW["properties"], "extra": {"type": "integer"}}}
    capsys.readouterr()
    assert oc.main(["--check"], _spec(Row=grown, Tag={"type": "object"}), path) == 1
    assert "make openapi" in capsys.readouterr().err


def test_check_reads_the_file_as_json(tmp_path: Path):
    path = tmp_path / "openapi.json"
    spec = _spec(Tag={"type": "object"})
    path.write_text(json.dumps(oc.contract(spec)), encoding="utf-8")
    assert oc.is_current(spec, path)
    path.write_text("{ not json", encoding="utf-8")
    assert not oc.is_current(spec, path)


FORM = Path(__file__).resolve().parents[3] / "frontend" / "scripts" / "openapi-form.json"


def test_render_writes_the_form_the_merge_driver_writes():
    # The merge driver re-renders a merged contract in TypeScript
    # (frontend/scripts/merge-openapi.ts); its test holds it to this same file,
    # whose keys reach every place the two writers could part.
    text = FORM.read_text(encoding="utf-8")
    assert oc.render(json.loads(text)) == text
