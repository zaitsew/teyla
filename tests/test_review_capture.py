"""The review capture format (docs/REVIEW.md): the JSON Schema, the fixture capture and the
signing vector. The repo has no runtime dependencies, so a small validator for the schema subset
the schema uses stands in for `jsonschema`: type, const, enum, pattern, minimum, minLength,
maxLength, maxItems, items, required, properties, additionalProperties and local $ref."""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "templates" / "review" / "capture.schema.json"
FIX = ROOT / "tests" / "fixtures" / "review-capture"
VECTOR = ROOT / "tests" / "fixtures" / "review-vector.json"
DOC = ROOT / "docs" / "REVIEW.md"

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool}


def _is_type(value, name: str) -> bool:
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def validate(value, schema: dict, root: dict, path: str = "$") -> list[str]:
    """Return the list of violations; an empty list means valid."""
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        return validate(value, node, root, path)
    errors: list[str] = []
    if "const" in schema and value != schema["const"]:
        return [f"{path}: expected {schema['const']!r}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: {value!r} is not one of {schema['enum']}"]
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(_is_type(value, n) for n in names):
            return [f"{path}: expected {schema['type']}, got {type(value).__name__}"]
    if isinstance(value, str):
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: {value!r} does not match {schema['pattern']}")
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: shorter than {schema['minLength']}")
        if len(value) > schema.get("maxLength", 10**9):
            errors.append(f"{path}: longer than {schema['maxLength']}")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")):
            errors.append(f"{path}: {value} is below {schema['minimum']}")
    if isinstance(value, list):
        if len(value) > schema.get("maxItems", 10**9):
            errors.append(f"{path}: more than {schema['maxItems']} items")
        for i, item in enumerate(value):
            if "items" in schema:
                errors += validate(item, schema["items"], root, f"{path}[{i}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing {key!r}")
        props = schema.get("properties", {})
        for key, item in value.items():
            if key in props:
                errors += validate(item, props[key], root, f"{path}.{key}")
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}: unexpected key {key!r}")
    return errors


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


@pytest.fixture()
def capture() -> dict:
    return json.loads((FIX / "capture.json").read_text(encoding="utf-8"))


def check(doc: dict, schema: dict) -> list[str]:
    return validate(doc, schema, schema)


def test_the_schema_is_valid_json_with_the_required_top_level_keys(schema):
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) <= set(schema["properties"])
    assert schema["properties"]["v"] == {"const": 1}


def test_the_fixture_capture_is_valid(capture, schema):
    assert check(capture, schema) == []


def test_the_example_in_the_docs_is_valid(schema):
    text = DOC.read_text(encoding="utf-8")
    blocks = re.findall(r"```json\n(.*?)\n```", text, re.S)
    docs = [json.loads(b) for b in blocks if '"comment"' in b and '"anchors"' in b]
    assert docs, "docs/REVIEW.md has no capture example"
    for doc in docs:
        assert check(doc, schema) == []


def test_the_screenshot_hash_matches_the_png(capture):
    png = (FIX / "capture.png").read_bytes()
    assert capture["screenshot"]["sha256"] == hashlib.sha256(png).hexdigest()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width = int.from_bytes(png[16:20], "big")
    height = int.from_bytes(png[20:24], "big")
    assert (capture["screenshot"]["width"], capture["screenshot"]["height"]) == (width, height)


def test_the_tap_is_inside_the_element(capture):
    tap, box = capture["tap"], capture["element"]["bounds"]
    assert box["x"] <= tap["x"] < box["x"] + box["width"]
    assert box["y"] <= tap["y"] < box["y"] + box["height"]
    assert capture["element"]["id"] in {a["id"] for a in capture["anchors"]}


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda c: c.pop("comment"), "missing 'comment'"),
        (lambda c: c.update(v=2), "expected 1"),
        (lambda c: c.update(id="not-a-uuid"), "does not match"),
        (lambda c: c.update(created="2026-10-30 21:14:05"), "does not match"),
        (lambda c: c.update(extra=1), "unexpected key 'extra'"),
        (lambda c: c["comment"].update(input="voice"), "is not one of"),
        (lambda c: c["comment"].update(text=""), "shorter than 1"),
        (lambda c: c["tap"].update(x="12"), "expected number"),
        (lambda c: c["element"].update(role="slider"), "is not one of"),
        (lambda c: c["element"]["bounds"].pop("width"), "missing 'width'"),
        (lambda c: c["element"]["source"].update(line=0), "below 1"),
        (lambda c: c["environment"].update(appearance="sepia"), "is not one of"),
        (lambda c: c["app"].update(configuration="app_store"), "is not one of"),
        (lambda c: c["screenshot"].update(sha256="abc"), "does not match"),
        (lambda c: c["screenshot"].update(file="shot.png"), "expected 'capture.png'"),
        (lambda c: c["microphone"].update(host_audio_in_use="no"), "expected boolean"),
        (lambda c: c.update(anchors=[{"id": "a"}] * 201), "more than 200 items"),
        (lambda c: c.update(device="My iPhone\nname"), "does not match"),
    ],
)
def test_the_schema_rejects_a_broken_capture(capture, schema, mutate, fragment):
    bad = copy.deepcopy(capture)
    mutate(bad)
    assert any(fragment in e for e in check(bad, schema)), check(bad, schema)


def test_null_is_never_valid(capture, schema):
    capture["tap"] = None
    assert check(capture, schema)


def test_a_capture_without_element_or_tap_is_valid(capture, schema):
    for key in ("tap", "element", "screen"):
        capture.pop(key)
    assert check(capture, schema) == []


def _hmac(key: bytes, message: str) -> str:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()


def test_the_capture_signature_vector_reproduces():
    vec = json.loads(VECTOR.read_text(encoding="utf-8"))
    key = bytes.fromhex(vec["key_hex"])
    cap = json.loads((FIX / "capture.json").read_text(encoding="utf-8"))
    jsha = hashlib.sha256((FIX / "capture.json").read_bytes()).hexdigest()
    psha = hashlib.sha256((FIX / "capture.png").read_bytes()).hexdigest()
    assert (vec["capture_json_sha256"], vec["capture_png_sha256"]) == (jsha, psha)
    message = "\n".join(["teyla-review-v1", cap["id"], cap["created"], jsha, psha])
    assert vec["capture_message"] == message
    assert vec["capture_sig"] == _hmac(key, message)
    assert (FIX / "capture.sig").read_text().strip() == vec["capture_sig"]


def test_the_status_signature_vector_reproduces():
    vec = json.loads(VECTOR.read_text(encoding="utf-8"))
    key = bytes.fromhex(vec["key_hex"])
    status = json.loads((FIX / "status.json").read_text(encoding="utf-8"))
    message = "\n".join(
        ["teyla-review-status-v1", status["id"], status["status"], status["updated"], status.get("pr", "")]
    )
    assert vec["status_message"] == message
    assert vec["status_sig"] == status["sig"] == _hmac(key, message)


def test_the_pairing_string_in_the_vector_decodes_to_the_key():
    import base64

    vec = json.loads(VECTOR.read_text(encoding="utf-8"))
    body = vec["pairing"].removeprefix("teyla-pair:v1:")
    assert base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).hex() == vec["key_hex"]


def test_a_changed_byte_breaks_the_signature():
    vec = json.loads(VECTOR.read_text(encoding="utf-8"))
    key = bytes.fromhex(vec["key_hex"])
    forged = (FIX / "capture.json").read_bytes().replace(b"too small", b"too large")
    cap = json.loads((FIX / "capture.json").read_text(encoding="utf-8"))
    message = "\n".join(
        ["teyla-review-v1", cap["id"], cap["created"], hashlib.sha256(forged).hexdigest(), vec["capture_png_sha256"]]
    )
    assert _hmac(key, message) != vec["capture_sig"]
