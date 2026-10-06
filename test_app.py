import unittest

import pandas as pd

from app import (
    apply_text_cleaning,
    build_create_table_sql,
    make_unique_column_names,
)


class ColumnNameTests(unittest.TestCase):
    def test_sanitized_names_are_unique_and_stable(self):
        columns = make_unique_column_names(["A B", "A-B", "A_B", "A_B_2"])

        self.assertEqual(columns, ["A_B", "A_B_2", "A_B_3", "A_B_2_2"])

    def test_cleaning_headers_keeps_names_unique(self):
        frame = pd.DataFrame([[1, 2]], columns=["Côté A", "Cote A"])

        cleaned = apply_text_cleaning(
            frame,
            strip_spaces=False,
            lowercase=False,
            clean_headers=True,
        )

        self.assertEqual(cleaned.columns.tolist(), ["cote_a", "cote_a_2"])


class SqlGenerationTests(unittest.TestCase):
    def test_table_and_column_names_are_valid_quoted_identifiers(self):
        frame = pd.DataFrame({"Order": [1]})

        sql = build_create_table_sql(frame, "2025-report")

        self.assertEqual(
            sql,
            'CREATE TABLE "_2025_report" (\n    "Order" INT\n);',
        )

    def test_empty_column_set_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least one column"):
            build_create_table_sql(pd.DataFrame(), "dataset")


if __name__ == "__main__":
    unittest.main()
