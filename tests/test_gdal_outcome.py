from __future__ import annotations

import unittest

from tools.gdal_outcome import GdalOutcomeReason, GdalOutcomeTracker


SUCCESS_MARKER = "프로세스가 성공적으로 완료되었습니다"


class GdalOutcomeTrackerTests(unittest.TestCase):
    def test_clean_run_succeeds_after_exact_marker(self):
        tracker = GdalOutcomeTracker(SUCCESS_MARKER)

        self.assertTrue(tracker.record_info(SUCCESS_MARKER))

        decision = tracker.decide()
        self.assertTrue(decision.succeeded)
        self.assertEqual(decision.reason, GdalOutcomeReason.SUCCESS)
        self.assertEqual(decision.diagnostics, ())

    def test_nonfatal_diagnostic_is_allowed_when_marker_follows(self):
        tracker = GdalOutcomeTracker(SUCCESS_MARKER)
        tracker.record_diagnostic("입력 데이터에 대한 참고 진단")
        tracker.record_info(SUCCESS_MARKER)

        decision = tracker.decide()

        self.assertTrue(decision.succeeded)
        self.assertEqual(len(decision.diagnostics), 1)
        self.assertFalse(decision.diagnostics[0].fatal)

    def test_missing_marker_fails_closed(self):
        decision = GdalOutcomeTracker(SUCCESS_MARKER).decide()

        self.assertFalse(decision.succeeded)
        self.assertEqual(
            decision.reason,
            GdalOutcomeReason.SUCCESS_MARKER_MISSING,
        )

    def test_nonzero_diagnostic_without_marker_fails_closed(self):
        tracker = GdalOutcomeTracker(SUCCESS_MARKER)
        tracker.record_diagnostic("프로세스가 오류 코드 1을 반환했습니다")

        decision = tracker.decide()

        self.assertFalse(decision.succeeded)
        self.assertEqual(
            decision.reason,
            GdalOutcomeReason.SUCCESS_MARKER_MISSING,
        )
        self.assertIn("오류 코드 1", decision.detail)

    def test_fatal_diagnostic_blocks_later_success_marker(self):
        tracker = GdalOutcomeTracker(SUCCESS_MARKER)
        tracker.record_diagnostic("처리를 계속할 수 없습니다", fatal=True)
        tracker.record_info(SUCCESS_MARKER)

        decision = tracker.decide()

        self.assertFalse(decision.succeeded)
        self.assertEqual(decision.reason, GdalOutcomeReason.FATAL_DIAGNOSTIC)

    def test_diagnostic_after_success_marker_fails_closed(self):
        tracker = GdalOutcomeTracker(SUCCESS_MARKER)
        tracker.record_info(SUCCESS_MARKER)
        tracker.record_diagnostic("완료 뒤에 전달된 진단")

        decision = tracker.decide()

        self.assertFalse(decision.succeeded)
        self.assertEqual(
            decision.reason,
            GdalOutcomeReason.DIAGNOSTIC_AFTER_SUCCESS,
        )

    def test_wrong_marker_is_not_accepted(self):
        tracker = GdalOutcomeTracker(SUCCESS_MARKER)

        self.assertFalse(tracker.record_info("Process completed successfully"))

        decision = tracker.decide()
        self.assertFalse(decision.succeeded)
        self.assertEqual(
            decision.reason,
            GdalOutcomeReason.SUCCESS_MARKER_MISSING,
        )

    def test_empty_configured_marker_is_invalid(self):
        tracker = GdalOutcomeTracker("")

        self.assertFalse(tracker.record_info(""))

        decision = tracker.decide()
        self.assertFalse(decision.succeeded)
        self.assertEqual(
            decision.reason,
            GdalOutcomeReason.INVALID_SUCCESS_MARKER,
        )


if __name__ == "__main__":
    unittest.main()
