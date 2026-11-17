"""R1 附件回填测试：只测文件名白名单和路径安全，不访问网络。"""

import unittest

from tools.fetch_attachments import target_name


class TargetNameTest(unittest.TestCase):
    def test_accepts_project_attachments(self):
        self.assertEqual(
            target_name("articles-2026-11-17.json"),
            ("2026-11-17", "articles-2026-11-17.json"),
        )
        self.assertEqual(
            target_name("run-2026-11-17.json"), ("2026-11-17", "run-2026-11-17.json")
        )
        self.assertEqual(
            target_name("labels-2026-11-17.csv"),
            ("2026-11-17", "labels-2026-11-17.csv"),
        )

    def test_strips_directories(self):
        self.assertEqual(
            target_name("../../articles-2026-11-17.json"),
            ("2026-11-17", "articles-2026-11-17.json"),
        )
        self.assertEqual(
            target_name("C:\\temp\\articles-2026-11-17.json"),
            ("2026-11-17", "articles-2026-11-17.json"),
        )

    def test_rejects_other_names(self):
        for name in (
            "report.pdf",
            "articles.json",
            "articles-2026-11-17.txt",
            "other-2026-11-17.json",
            "",
        ):
            self.assertIsNone(target_name(name), name)


if __name__ == "__main__":
    unittest.main()
