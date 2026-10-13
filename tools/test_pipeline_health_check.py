#!/usr/bin/env python3
"""Offline tests for pipeline catalog integrity and fail-closed safety checks."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from pipeline_health_check import DEFAULT_CATALOG, ROOT, validate_catalog


class PipelineCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(DEFAULT_CATALOG.read_text(encoding="utf-8"))

    def test_repository_catalog_is_consistent(self):
        self.assertEqual(validate_catalog(self.catalog, ROOT), [])

    def test_duplicate_stage_ids_fail(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["stages"].append(copy.deepcopy(catalog["stages"][0]))
        self.assertTrue(any("stage ids must be unique" in e for e in validate_catalog(catalog, ROOT)))

    def test_missing_tool_reference_fails(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["tools"][0]["path"] = "tools/definitely_missing_pipeline_tool.py"
        self.assertTrue(any("references missing file" in e for e in validate_catalog(catalog, ROOT)))

    def test_missing_safety_protection_fails(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["protected_operations"] = ["credentials", "QA"]
        errors = validate_catalog(catalog, ROOT)
        self.assertTrue(any("billing" in e for e in errors))
        self.assertTrue(any("YouTube upload" in e for e in errors))

    def test_static_status_cannot_masquerade_as_runtime_proof(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["stages"][0]["step_status_is_not_runtime_proof"] = False
        self.assertTrue(any("separate static configuration" in e for e in validate_catalog(catalog, ROOT)))

    def test_cron_caveat_cannot_claim_guaranteed_uptime(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["runtime_monitoring"]["availability_caveat"] = "Guaranteed 24/7 uptime."
        self.assertTrue(any("24/7 uptime guarantee" in e for e in validate_catalog(catalog, ROOT)))

    def test_path_traversal_is_rejected(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["tools"][0]["path"] = "../secrets.txt"
        self.assertTrue(any("unsafe repository-relative path" in e for e in validate_catalog(catalog, ROOT)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
