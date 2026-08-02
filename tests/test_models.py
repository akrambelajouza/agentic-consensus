import os
import unittest
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from agentic_consensus.models import build_llm


class OpenRouterPayloadTests(unittest.TestCase):
    def test_preserves_max_tokens_wire_parameter(self) -> None:
        env = {
            "OPENROUTER_API_KEY": "test-key",
            "MODERATOR_MODEL": "openrouter:google/gemini-3.6-flash",
        }

        with patch.dict(os.environ, env, clear=False):
            model = build_llm("moderator", max_tokens=1234)
            payload = model._get_request_payload(
                [HumanMessage(content="test")],
            )

        self.assertEqual(payload["extra_body"]["max_tokens"], 1234)
        self.assertNotIn("max_completion_tokens", payload)


if __name__ == "__main__":
    unittest.main()
