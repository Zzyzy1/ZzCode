import os
import unittest

from zzcode.context import (
    build_date_change_context_message,
    build_user_context_message,
    get_local_iso_date,
    get_local_month_year,
)


class RuntimeContextTest(unittest.TestCase):
    def test_local_date_can_be_overridden_for_stable_context(self) -> None:
        previous = os.environ.get("ZZCODE_OVERRIDE_DATE")
        os.environ["ZZCODE_OVERRIDE_DATE"] = "2026-06-24"
        try:
            self.assertEqual(get_local_iso_date(), "2026-06-24")
            self.assertEqual(get_local_month_year(), "June 2026")
        finally:
            if previous is None:
                os.environ.pop("ZZCODE_OVERRIDE_DATE", None)
            else:
                os.environ["ZZCODE_OVERRIDE_DATE"] = previous

    def test_user_context_message_uses_system_reminder_format(self) -> None:
        message = build_user_context_message({"currentDate": "Today's date is 2026-06-24."})

        self.assertEqual(message["role"], "user")
        self.assertIn("<system-reminder>", message["content"])
        self.assertIn("# currentDate", message["content"])
        self.assertIn("Today's date is 2026-06-24.", message["content"])

    def test_date_change_context_message_includes_previous_and_current_date(self) -> None:
        message = build_date_change_context_message("2026-06-30", "2026-07-01")

        self.assertEqual(message["role"], "user")
        self.assertIn("# currentDate", message["content"])
        self.assertIn("# dateChange", message["content"])
        self.assertIn("Today's date is 2026-07-01.", message["content"])
        self.assertIn("from 2026-06-30 to 2026-07-01", message["content"])


if __name__ == "__main__":
    unittest.main()
