import os
import tempfile
import unittest
from pathlib import Path

from hll.runtime_env import load_dotenv_for_cli


class RuntimeEnvTests(unittest.TestCase):
    def test_loads_dotenv_without_overwriting_existing_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "OPENAI_API_KEY=from_file",
                        "OPENAI_MODEL=gpt-4.1",
                        "OPENAI_BASE_URL=https://example.test/v1",
                        "QUOTED=\"hello world\"",
                        "COMMENTED=value # trailing comment",
                    ]
                ),
                encoding="utf-8",
            )
            previous_key = os.environ.get("OPENAI_API_KEY")
            previous_model = os.environ.get("OPENAI_MODEL")
            previous_base_url = os.environ.get("OPENAI_BASE_URL")
            previous_quoted = os.environ.get("QUOTED")
            previous_commented = os.environ.get("COMMENTED")
            try:
                os.environ["OPENAI_API_KEY"] = "from_shell"
                os.environ.pop("OPENAI_MODEL", None)
                os.environ["OPENAI_BASE_URL"] = ""
                os.environ.pop("QUOTED", None)
                os.environ.pop("COMMENTED", None)

                loaded = load_dotenv_for_cli(root)

                self.assertIn((root / ".env").resolve(), loaded)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "from_shell")
                self.assertEqual(os.environ["OPENAI_MODEL"], "gpt-4.1")
                self.assertEqual(os.environ["OPENAI_BASE_URL"], "https://example.test/v1")
                self.assertEqual(os.environ["QUOTED"], "hello world")
                self.assertEqual(os.environ["COMMENTED"], "value")
            finally:
                _restore_env("OPENAI_API_KEY", previous_key)
                _restore_env("OPENAI_MODEL", previous_model)
                _restore_env("OPENAI_BASE_URL", previous_base_url)
                _restore_env("QUOTED", previous_quoted)
                _restore_env("COMMENTED", previous_commented)


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
