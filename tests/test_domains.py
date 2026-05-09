"""
tests/test_domains.py
文件说明：验证 Keepa domain 输入归一化。
主要职责：覆盖代码、数字 ID、locale alias 和未知 domain 错误。
依赖边界：只依赖本地静态 domain 表。
"""

import unittest

from keepa_cli.domains import DOMAIN_ALIASES, resolve_domain


class DomainResolutionTests(unittest.TestCase):
    def test_resolves_common_domain_inputs_to_same_locale(self):
        self.assertEqual(resolve_domain("US").domain_id, 1)
        self.assertEqual(resolve_domain("1").locale, "com")
        self.assertEqual(resolve_domain("com").code, "US")

    def test_rejects_unknown_domain_with_clear_message(self):
        with self.assertRaisesRegex(ValueError, "unknown Keepa domain"):
            resolve_domain("mars")

    def test_exposes_alias_table_for_agent_discovery(self):
        self.assertIn("US", DOMAIN_ALIASES)
        self.assertIn("com", DOMAIN_ALIASES)


if __name__ == "__main__":
    unittest.main()
