"""Tests for pure helpers in :mod:`app` that need no running GUI.

Importing :mod:`app` only defines its classes and functions; no Tk window is
created until ``MyDbApp().mainloop()`` runs, so these import cleanly headless.
"""

import unittest

import app


class BalticInputTests(unittest.TestCase):
    def test_corrects_mis_decoded_latvian_letters(self) -> None:
        # The cp1252-rendered byte is re-decoded as cp1257 back to the letter.
        self.assertEqual(app.fix_baltic_char("ï"), "ļ")
        self.assertEqual(app.fix_baltic_char("â"), "ā")
        self.assertEqual(app.fix_baltic_char("î"), "ī")
        self.assertEqual(app.fix_baltic_char("ç"), "ē")

    def test_leaves_ascii_and_empty_alone(self) -> None:
        for ch in ("a", "Z", "1", ".", "", " "):
            self.assertIsNone(app.fix_baltic_char(ch))

    def test_leaves_already_correct_latvian_alone(self) -> None:
        # A correct ā (U+0101) is not a Latin-1 character, so it is untouched.
        self.assertIsNone(app.fix_baltic_char("ā"))
        self.assertIsNone(app.fix_baltic_char("ļ"))


if __name__ == "__main__":
    unittest.main()
