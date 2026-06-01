"""Unit tests for retry utility."""

import unittest
from unittest.mock import MagicMock, patch

from scholar_agent.engine.retry import retry_with_backoff


class TestRetryWithBackoff(unittest.TestCase):
    def test_success_first_try(self) -> None:
        fn = MagicMock(return_value=42)
        result = retry_with_backoff(fn, max_retries=3, jitter=False)
        self.assertEqual(result, 42)
        self.assertEqual(fn.call_count, 1)

    @patch("scholar_agent.engine.retry.time.sleep")
    def test_retries_on_failure_then_succeeds(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(side_effect=[ValueError("fail"), "ok"])
        result = retry_with_backoff(fn, max_retries=2, jitter=False, retry_on=(ValueError,))
        self.assertEqual(result, "ok")
        self.assertEqual(fn.call_count, 2)
        mock_sleep.assert_called_once()

    @patch("scholar_agent.engine.retry.time.sleep")
    def test_raises_after_max_retries(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(side_effect=ValueError("always fail"))
        with self.assertRaises(ValueError):
            retry_with_backoff(fn, max_retries=2, jitter=False, retry_on=(ValueError,))
        self.assertEqual(fn.call_count, 3)

    @patch("scholar_agent.engine.retry.time.sleep")
    def test_only_retries_on_specified_exceptions(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(side_effect=TypeError("wrong type"))
        with self.assertRaises(TypeError):
            retry_with_backoff(fn, max_retries=2, retry_on=(ValueError,))
        self.assertEqual(fn.call_count, 1)

    @patch("scholar_agent.engine.retry.time.sleep")
    def test_on_retry_callback_called(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(side_effect=[ValueError("fail"), "ok"])
        callback = MagicMock()
        retry_with_backoff(fn, max_retries=1, jitter=False, retry_on=(ValueError,), on_retry=callback)
        callback.assert_called_once()
        call_args = callback.call_args[0]
        self.assertEqual(call_args[0], 1)
        self.assertIsInstance(call_args[1], ValueError)

    @patch("scholar_agent.engine.retry.time.sleep")
    def test_delay_capped_at_max_delay(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(side_effect=[ValueError("fail"), ValueError("fail"), "ok"])
        retry_with_backoff(fn, max_retries=2, base_delay=100.0, max_delay=5.0, jitter=False, retry_on=(ValueError,))
        for call in mock_sleep.call_args_list:
            self.assertLessEqual(call[0][0], 5.0)

    @patch("scholar_agent.engine.retry.time.sleep")
    def test_passes_args_and_kwargs(self, mock_sleep: MagicMock) -> None:
        fn = MagicMock(return_value="result")
        retry_with_backoff(fn, "a", "b", key="val", max_retries=0)
        fn.assert_called_once_with("a", "b", key="val")


if __name__ == "__main__":
    unittest.main()
