"""CLI 冒烟测试：只跑不产生副作用的分支。"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from dqplat.cli import main


def run(*argv: str) -> tuple[int, str]:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = main(list(argv))
    return code, buffer.getvalue()


class CliTest(unittest.TestCase):
    def test_version_exits_zero(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_list_shows_steps(self) -> None:
        code, out = run("list", "demo")
        self.assertEqual(code, 0)
        for step in ("fixtures", "pii", "lineage", "report"):
            self.assertIn(step, out)

    def test_run_dry_run_executes_nothing(self) -> None:
        code, out = run("run", "demo", "--dry-run", "--quiet")
        self.assertEqual(code, 0)
        self.assertNotIn("[run ]", out)

    def test_unknown_pipeline_exits_two(self) -> None:
        code, out = run("run", "no-such-pipeline", "--dry-run")
        self.assertEqual(code, 2)
        self.assertIn("error", out)

    def test_validate_ok_and_bad(self) -> None:
        good = {
            "schema": "pii-hits/1.0",
            "source": "x.txt",
            "summary": {"total": 1},
            "findings": [{"type": "mobile_cn", "confidence": "high", "value": "1**********"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pii.json"
            path.write_text(json.dumps(good), encoding="utf-8")
            code, out = run("validate", str(path))
            self.assertEqual(code, 0)
            self.assertIn("[ok", out)

            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"schema": "pii-hits/1.0"}), encoding="utf-8")
            code, out = run("validate", str(bad))
            self.assertEqual(code, 1)
            self.assertIn("[bad", out)


if __name__ == "__main__":
    unittest.main()
