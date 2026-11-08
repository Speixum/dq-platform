"""契约校验测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from dqplat import contracts


def _write(tmp: str, name: str, payload: object) -> Path:
    path = Path(tmp) / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class ValidatePayloadTest(unittest.TestCase):
    def test_pii_ok(self) -> None:
        payload = {
            "schema": "pii-hits/1.0",
            "source": "sample.txt",
            "findings": [{"type": "mobile_cn", "confidence": "high"}],
            "summary": {"total": 1},
        }
        self.assertEqual(contracts.validate_payload(payload), [])

    def test_pii_missing_key(self) -> None:
        payload = {"schema": "pii-hits/1.0", "findings": []}
        problems = contracts.validate_payload(payload)
        self.assertTrue(any("source" in item for item in problems))

    def test_pii_bad_finding(self) -> None:
        payload = {"schema": "pii-hits/1.0", "source": "x", "summary": {}, "findings": [{"type": "t"}]}
        problems = contracts.validate_payload(payload)
        self.assertTrue(any("confidence" in item for item in problems))

    def test_lineage_ok(self) -> None:
        payload = {
            "schema": "dataset-lineage/1.0",
            "run_id": "r1",
            "status": "ok",
            "nodes": [{"status": "ok"}],
            "edges": [],
        }
        self.assertEqual(contracts.validate_payload(payload), [])

    def test_report_ok(self) -> None:
        payload = {"schema": "data-quality-report/1.0", "subject": {}, "summary": {}, "dimensions": []}
        self.assertEqual(contracts.validate_payload(payload), [])

    def test_unknown_schema(self) -> None:
        problems = contracts.validate_payload({"schema": "nope/9.9"})
        self.assertTrue(problems and "unknown schema" in problems[0])

    def test_not_an_object(self) -> None:
        self.assertTrue(contracts.validate_payload([1, 2]))

    def test_validate_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            good = _write(tmp, "a.json", {"schema": "data-quality-report/1.0", "subject": {}, "summary": {}, "dimensions": []})
            self.assertEqual(contracts.validate_file(good), [])
            bad = Path(tmp) / "b.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertTrue(contracts.validate_file(bad))


if __name__ == "__main__":
    unittest.main()
