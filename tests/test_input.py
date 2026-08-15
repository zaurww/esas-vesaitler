"""What the program accepts on the way in, and what it refuses (§11.1).

The storage format is one thing (ISO dates, a dot for decimals). Input is
another: it arrives pasted out of somebody else's workbook, looking the way a
person sees it. Two shapes are refused on purpose, because guessing at them is
wrong by a factor of a thousand or by several months.
"""

from tests.support import EngineTest

from engine.mutate import dec, iso_date
from engine.mutate.parse import _normalise_number
from engine.storage import DataError


class Numbers(EngineTest):

    def norm(self, raw):
        return _normalise_number(raw, "İlkin dəyər")

    def test_plain(self):
        self.assertEqual(self.norm("1234.56"), "1234.56")

    def test_space_grouped_with_a_comma_decimal(self):
        self.assertEqual(self.norm("1 234,56"), "1234.56")

    def test_non_breaking_space_grouped(self):
        self.assertEqual(self.norm("1 234,56"), "1234.56")

    def test_english_grouping(self):
        self.assertEqual(self.norm("1,234.56"), "1234.56")

    def test_continental_grouping(self):
        self.assertEqual(self.norm("1.234,56"), "1234.56")

    def test_grouped_integer(self):
        self.assertEqual(self.norm("1 234 567"), "1234567")

    def test_currency_marks_are_dropped(self):
        self.assertEqual(self.norm("1234.56 ₼"), "1234.56")
        self.assertEqual(self.norm("1234.56 AZN"), "1234.56")

    def test_last_separator_wins_when_both_are_present(self):
        self.assertEqual(self.norm("1.234,56"), "1234.56")
        self.assertEqual(self.norm("1,234.56"), "1234.56")

    def test_ambiguous_thousands_comma_is_refused(self):
        """`1,234` is either 1.234 or 1234. Choosing silently is wrong by a
        factor of a thousand, so it is an input error (§2.1)."""
        with self.assertRaises(DataError):
            self.norm("1,234")

    def test_negative_cost_is_refused(self):
        with self.assertRaises(DataError):
            dec("-5", "İlkin dəyər")


class Dates(EngineTest):

    def test_iso_passes_through(self):
        self.assertEqual(iso_date("2023-02-15", "Alış tarixi"), "2023-02-15")

    def test_day_first_with_dots(self):
        self.assertEqual(iso_date("15.02.2023", "Alış tarixi"), "2023-02-15")

    def test_day_first_with_slashes(self):
        self.assertEqual(iso_date("15/02/2023", "Alış tarixi"), "2023-02-15")

    def test_time_is_dropped(self):
        self.assertEqual(iso_date("15.02.2023 0:00", "Alış tarixi"),
                         "2023-02-15")

    def test_month_first_is_refused(self):
        """03/05/2023 is two different dates depending on which pattern wins.
        Only day-first is accepted, which is how it is written here."""
        self.assertEqual(iso_date("03/05/2023", "Alış tarixi"), "2023-05-03")
        with self.assertRaises(DataError):
            iso_date("12/25/2023", "Alış tarixi")     # only valid as US order

    def test_garbage_is_refused(self):
        with self.assertRaises(DataError):
            iso_date("bilmirem", "Alış tarixi")

    def test_optional_date_may_be_empty(self):
        self.assertEqual(iso_date("", "Alış tarixi", required=False), "")


class ColumnGuessing(EngineTest):
    """§11.2: the import guesses which column is which; the guesses are
    matched case- and alphabet-insensitively, İ included."""

    def test_dotted_capital_i_is_folded(self):
        from engine.mutate import guess_columns
        got = guess_columns(["İnv.№", "Adı", "Kateqoriya"])
        self.assertEqual(got.get("inv_no"), 0)
        self.assertEqual(got.get("name"), 1)

    def test_russian_headers_are_recognised(self):
        from engine.mutate import guess_columns
        got = guess_columns(["Инвентарный номер", "Наименование",
                             "Первоначальная стоимость"])
        self.assertEqual(got.get("inv_no"), 0)
        self.assertEqual(got.get("cost"), 2)

    def test_the_new_optional_columns_are_recognised(self):
        from engine.mutate import guess_columns
        got = guess_columns(["E-qaimə", "Seriya nömrəsi"])
        self.assertEqual(got.get("e_qaime"), 0)
        self.assertEqual(got.get("serial_no"), 1)

    def test_a_longer_header_is_not_swallowed_by_a_shorter_alias(self):
        """Regression: `inv_no` lists "nömrə", "Seriya nömrəsi" contains it,
        and inv_no is declared first -- so the serial column was mapped to the
        inventory number. Exact matches are now claimed first."""
        from engine.mutate import guess_columns
        got = guess_columns(["İnv.№", "Adı", "Seriya nömrəsi"])
        self.assertEqual(got.get("inv_no"), 0)
        self.assertEqual(got.get("serial_no"), 2)

    def test_a_full_realistic_header_maps_end_to_end(self):
        from engine.mutate import guess_columns
        got = guess_columns(["İnv.№", "Adı", "Kateqoriya", "Alış tarixi",
                             "İlkin dəyər", "Qalıq dəyər", "Kontragent",
                             "E-qaimə №", "Seriya №", "Qeyd"])
        self.assertEqual(got, {"inv_no": 0, "name": 1, "category": 2,
                               "in_date": 3, "cost": 4, "opening_residual": 5,
                               "counterparty": 6, "e_qaime": 7,
                               "serial_no": 8, "note": 9})


if __name__ == "__main__":
    import unittest
    unittest.main()
