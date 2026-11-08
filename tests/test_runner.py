"""执行器测试：不依赖 vendor/，只验证调度语义。"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from dqplat.config import Pipeline, Step
from dqplat.runner import FAILED, OK, SKIPPED, Runner, summarize

PY = sys.executable


def _pipeline(*steps: Step) -> Pipeline:
    return Pipeline(name="t", version="1.0", description="test", steps=steps)


class RunnerTest(unittest.TestCase):
    def _root(self, tmp: str) -> Path:
        return Path(tmp)

    def test_success_writes_manifest_and_hash(self) -> None:
        step = Step(
            id="make",
            command=(PY, "-c", "open('out.txt','w').write('hi')"),
            produces=("out.txt",),
        )
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner(_pipeline(step), tmp, quiet=True)
            manifest = runner.execute()
            self.assertEqual(manifest["status"], OK)
            produced = manifest["steps"][0]["produces"]
            self.assertEqual(len(produced), 1)
            self.assertEqual(produced[0]["bytes"], 2)
            self.assertEqual(len(produced[0]["sha256"]), 64)
            saved = json.loads((runner.run_dir / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["schema"], "dq-run/1.0")

    def test_failure_stops_pipeline(self) -> None:
        bad = Step(id="bad", command=(PY, "-c", "import sys; sys.exit(3)"))
        after = Step(id="after", command=(PY, "-c", "open('after.txt','w')"), produces=("after.txt",))
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner(_pipeline(bad, after), tmp, quiet=True)
            manifest = runner.execute()
            self.assertEqual(manifest["status"], FAILED)
            self.assertEqual(manifest["steps"][0]["exit_code"], 3)
            self.assertFalse((Path(tmp) / "after.txt").exists())

    def test_optional_step_skipped_when_require_missing(self) -> None:
        step = Step(id="needs", command=(PY, "-c", "pass"), requires=("missing.csv",), optional=True)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Runner(_pipeline(step), tmp, quiet=True).execute()
            self.assertEqual(manifest["steps"][0]["status"], SKIPPED)
            self.assertIn("missing.csv", manifest["steps"][0]["reason"])
            self.assertEqual(manifest["status"], OK)

    def test_required_step_fails_when_require_missing(self) -> None:
        step = Step(id="needs", command=(PY, "-c", "pass"), requires=("missing.csv",), optional=False)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Runner(_pipeline(step), tmp, quiet=True).execute()
            self.assertEqual(manifest["status"], FAILED)
            self.assertEqual(manifest["steps"][0]["status"], FAILED)

    def test_dry_run_executes_nothing(self) -> None:
        step = Step(id="w", command=(PY, "-c", "open('x.txt','w')"), produces=("x.txt",))
        with tempfile.TemporaryDirectory() as tmp:
            runner = Runner(_pipeline(step), tmp, dry_run=True, quiet=True)
            manifest = runner.execute()
            self.assertEqual(manifest["status"], "dry-run")
            self.assertFalse((Path(tmp) / "x.txt").exists())
            self.assertFalse((runner.run_dir / "manifest.json").exists())

    def test_only_and_skip_filters(self) -> None:
        a = Step(id="a", command=(PY, "-c", "open('a.txt','w')"), produces=("a.txt",))
        b = Step(id="b", command=(PY, "-c", "open('b.txt','w')"), produces=("b.txt",))
        with tempfile.TemporaryDirectory() as tmp:
            Runner(_pipeline(a, b), tmp, only=("b",), quiet=True).execute()
            self.assertFalse((Path(tmp) / "a.txt").exists())
            self.assertTrue((Path(tmp) / "b.txt").exists())

            with tempfile.TemporaryDirectory() as tmp2:
                Runner(_pipeline(a, b), tmp2, skip=("a",), quiet=True).execute()
                self.assertFalse((Path(tmp2) / "a.txt").exists())
                self.assertTrue((Path(tmp2) / "b.txt").exists())

    def test_resume_reuses_unchanged_step(self) -> None:
        step = Step(id="w", command=(PY, "-c", "open('x.txt','w').write('1')"), produces=("x.txt",))
        with tempfile.TemporaryDirectory() as tmp:
            first = Runner(_pipeline(step), tmp, quiet=True)
            first.execute()
            second = Runner(_pipeline(step), tmp, run_dir=first.run_dir, resume=first.run_dir, quiet=True)
            manifest = second.execute()
            self.assertEqual(manifest["steps"][0]["status"], SKIPPED)
            self.assertIn("resumed", manifest["steps"][0]["reason"])

    def test_timeout_marks_failed(self) -> None:
        slow = Step(id="slow", command=(PY, "-c", "import time; time.sleep(5)"), timeout=1)
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Runner(_pipeline(slow), tmp, quiet=True).execute()
            self.assertEqual(manifest["status"], FAILED)
            self.assertIn("timeout", manifest["steps"][0]["reason"])

    def test_summarize_renders_table(self) -> None:
        step = Step(id="w", command=(PY, "-c", "open('x.txt','w')"), produces=("x.txt",))
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Runner(_pipeline(step), tmp, quiet=True).execute()
            text = summarize(manifest)
            self.assertIn("STEP", text)
            self.assertIn("w", text)


if __name__ == "__main__":
    unittest.main()
