from __future__ import annotations

from pathlib import Path
import subprocess
import unittest


NODE_TEST = Path(__file__).resolve().with_name("edge_cdp_client.test.mjs")


class EdgeCdpClientTests(unittest.TestCase):
    def test_node_protocol_and_projection_contract(self):
        completed = subprocess.run(
            ["node", "--test", str(NODE_TEST)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            completed.stdout + completed.stderr,
        )


if __name__ == "__main__":
    unittest.main()
