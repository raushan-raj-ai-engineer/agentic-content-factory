from content_factory.llm.base import _decode_json_payload


def test_decode_json_payload_accepts_fenced_json() -> None:
    assert _decode_json_payload('```json\n{"value": 3}\n```') == {"value": 3}


def test_decode_json_payload_accepts_small_prefix_suffix() -> None:
    assert _decode_json_payload('Here is the JSON: {"value": 4}') == {"value": 4}
