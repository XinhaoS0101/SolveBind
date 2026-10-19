import unittest

from hll.experiment import build_reproducibility_manifest


class ExperimentManifestTests(unittest.TestCase):
    def test_prompt_and_tool_schema_fingerprints_are_stable(self):
        first = build_reproducibility_manifest()
        second = build_reproducibility_manifest()

        self.assertEqual(first, second)
        self.assertEqual(len(first["workflow"]["prompt_sha256"]), 64)
        self.assertEqual(len(first["tool_schema"]["sha256"]), 64)
        self.assertGreater(first["tool_schema"]["action_count"], 20)


if __name__ == "__main__":
    unittest.main()
