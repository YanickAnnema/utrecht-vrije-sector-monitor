import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import monitor


def home(home_id):
    return {
        "Id": home_id,
        "Adres": {"Straatnaam": "Teststraat", "Huisnummer": 1, "Woonplaats": "Utrecht"},
        "Eenheid": {"NettoHuur": "1200.00"},
    }


class MonitorTest(unittest.TestCase):
    def test_empty_free_sector_can_be_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "seen_ids.json"
            with (
                patch.object(monitor, "STATE_FILE", state_file),
                patch.object(monitor, "fetch_homes", return_value={}),
                patch.object(monitor, "send_telegram") as send,
                patch("sys.argv", ["monitor.py"]),
                patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "test"}),
            ):
                monitor.main()
                self.assertEqual(json.loads(state_file.read_text())["seen_ids"], [])
                send.assert_not_called()

    def test_first_run_sets_baseline_then_only_new_id_notifies(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "seen_ids.json"
            with (
                patch.object(monitor, "STATE_FILE", state_file),
                patch.object(monitor, "fetch_homes", side_effect=[{"1": home("1")}, {"1": home("1")}, {"1": home("1"), "2": home("2")}]),
                patch.object(monitor, "send_telegram") as send,
                patch("sys.argv", ["monitor.py"]),
                patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "test"}),
            ):
                monitor.main()
                self.assertEqual(json.loads(state_file.read_text())["seen_ids"], ["1"])
                self.assertEqual(send.call_count, 0)
                monitor.main()
                self.assertEqual(send.call_count, 0)
                monitor.main()
                self.assertEqual(send.call_count, 1)
                self.assertIn("PublicatieId=2", send.call_args.args[0])
                self.assertEqual(json.loads(state_file.read_text())["seen_ids"], ["1", "2"])

    def test_failed_telegram_does_not_update_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "seen_ids.json"
            state_file.write_text('{"seen_ids": ["1"]}')
            with (
                patch.object(monitor, "STATE_FILE", state_file),
                patch.object(monitor, "fetch_homes", return_value={"2": home("2")}),
                patch.object(monitor, "send_telegram", side_effect=RuntimeError("failed")),
                patch("sys.argv", ["monitor.py"]),
                patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "test"}),
            ):
                with self.assertRaises(RuntimeError):
                    monitor.main()
                self.assertEqual(json.loads(state_file.read_text())["seen_ids"], ["1"])


if __name__ == "__main__":
    unittest.main()
