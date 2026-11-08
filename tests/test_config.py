"""配置解析测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from dqplat.config import ConfigError, load_pipeline

ROOT = Path(__file__).resolve().parent.parent


class LoadPipelineTest(unittest.TestCase):
    def test_demo_pipeline(self) -> None:
        pipeline = load_pipeline(ROOT / "pipelines" / "demo.toml")
        self.assertEqual(pipeline.name, "demo")
        self.assertEqual(pipeline.step_ids(), ("fixtures", "pii", "lineage", "report"))

    def test_full_pipeline_has_six_modules(self) -> None:
        pipeline = load_pipeline(ROOT / "pipelines" / "full.toml")
        ids = set(pipeline.step_ids())
        self.assertTrue({"prep", "qc", "cost", "pii", "lineage", "report"} <= ids)

    def test_duplicate_id_rejected(self) -> None:
        text = """
name = "dup"
[[step]]
id = "a"
command = ["x"]
[[step]]
id = "a"
command = ["y"]
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.toml"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_pipeline(path)
            self.assertIn("duplicate", str(ctx.exception))

    def test_missing_command_rejected(self) -> None:
        text = 'name = "x"\n[[step]]\nid = "a"\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.toml"
            path.write_text(text, encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_pipeline(path)

    def test_missing_file(self) -> None:
        with self.assertRaises(ConfigError):
            load_pipeline(ROOT / "pipelines" / "does-not-exist.toml")


if __name__ == "__main__":
    unittest.main()
