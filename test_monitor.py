import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

import monitor


def home(home_id):
    return {
        "Id": home_id,
        "Adres": {"Straatnaam": "Teststraat", "Huisnummer": 1, "Woonplaats": "Utrecht"},
        "Eenheid": {"NettoHuur": "1200.00"},
    }


class MonitorTest(unittest.TestCase):
    def test_fetch_retries_timeout_after_empty_response(self):
        @contextmanager
        def response_context(response=None, timeout=False):
            yield SimpleNamespace(value=response)
            if timeout:
                raise PlaywrightTimeoutError("timed out")

        empty = MagicMock(status=200)
        empty.json.return_value = {"data": {"PublicatieLijst": {"List": []}}}
        valid = MagicMock(status=200)
        valid.json.return_value = {"data": {
            "Result": {"IsSuccess": True},
            "PublicatieLijst": {"List": [{"PublicatieModel": "Aanbodmodel", "EenheidSoort": "Woonruimte"}]},
        }}
        page = MagicMock()
        page.expect_response.side_effect = [
            response_context(empty), response_context(timeout=True), response_context(valid),
        ]
        playwright = MagicMock()
        playwright.chromium.launch.return_value.new_page.return_value = page
        context = MagicMock()
        context.__enter__.return_value = playwright

        with patch.object(monitor, "sync_playwright", return_value=context), patch.object(monitor.time, "sleep"):
            homes, counts = monitor.fetch_offers()

        self.assertEqual(homes, {})
        self.assertEqual(counts["Aanbod"], 1)
        self.assertEqual(page.reload.call_count, 2)

    def test_empty_free_sector_can_be_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "seen_ids.json"
            with (
                patch.object(monitor, "STATE_FILE", state_file),
                patch.object(monitor, "fetch_offers", return_value=({}, {"Vrije sector": 0})),
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
                patch.object(monitor, "fetch_offers", side_effect=[
                    ({"1": home("1")}, {"Vrije sector": 1}),
                    ({"1": home("1")}, {"Vrije sector": 1}),
                    ({"1": home("1"), "2": home("2")}, {"Vrije sector": 2}),
                ]),
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
                patch.object(monitor, "fetch_offers", return_value=({"2": home("2")}, {"Vrije sector": 1})),
                patch.object(monitor, "send_telegram", side_effect=RuntimeError("failed")),
                patch("sys.argv", ["monitor.py"]),
                patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "test"}),
            ):
                with self.assertRaises(RuntimeError):
                    monitor.main()
                self.assertEqual(json.loads(state_file.read_text())["seen_ids"], ["1"])

    def test_report_sends_current_count_and_home_without_marking_it_new(self):
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "seen_ids.json"
            state_file.write_text('{"seen_ids": ["1"]}')
            with (
                patch.object(monitor, "STATE_FILE", state_file),
                patch.object(monitor, "fetch_offers", return_value=({"1": home("1")}, {
                    "Aanbod": 64, "Loting": 9, "Vrije sector": 1, "Parkeren & Overig": 2,
                })),
                patch.object(monitor, "send_telegram") as send,
                patch("sys.argv", ["monitor.py", "--report"]),
                patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "test", "TELEGRAM_CHAT_ID": "123"}),
            ):
                monitor.main()
                self.assertEqual(send.call_count, 1)
                message = send.call_args.args[0]
                self.assertIn("Totaal: 76 advertenties", message)
                self.assertIn("Vrije sector: 1", message)
                self.assertIn("Teststraat 1, Utrecht", message)
                self.assertIn("PublicatieId=1", message)
                self.assertEqual(json.loads(state_file.read_text())["seen_ids"], ["1"])


if __name__ == "__main__":
    unittest.main()
