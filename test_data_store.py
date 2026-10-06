import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from app import (
    infer_sql_type,
    make_unique_column_names,
    normalize_text,
)
from data_store import DiskBackedCsv
from data_store import upload_key


class DiskBackedCsvTests(unittest.TestCase):
    def load_csv(self, contents):
        uploaded_file = BytesIO(contents.encode("utf-8"))
        uploaded_file.name = "sample.csv"
        with patch("data_store.CSV_CHUNK_SIZE", 2):
            return DiskBackedCsv.from_upload(
                uploaded_file,
                make_unique_column_names,
            )

    def test_imports_in_chunks_and_calculates_exact_metrics(self):
        dataset = self.load_csv(
            "Full Name,Age,City\n"
            " Alice ,10,Paris\n"
            "bob,,Lyon\n"
            " Alice ,10.0,Paris\n"
            "Chloé,30,\n"
        )
        try:
            self.assertEqual(dataset.row_count, 4)
            self.assertEqual(dataset.metrics(), (2, 1))
            self.assertEqual(dataset.preview(limit=2).shape, (2, 3))

            quality = dataset.column_quality(infer_sql_type, table="source")
            self.assertEqual(quality.loc[quality["Colonne"] == "Age", "Valeurs uniques"].item(), 2)
        finally:
            dataset.delete()

    def test_single_column_csv_is_not_split_by_delimiter_sniffing(self):
        dataset = self.load_csv("value\n1\n2\n3\n")
        try:
            self.assertEqual(dataset.columns, ["value"])
            self.assertEqual(dataset.preview()["value"].tolist(), ["1", "2", "3"])
        finally:
            dataset.delete()

    def test_upload_key_uses_streamlit_file_id_without_reading_file(self):
        class IdentifiedUpload(BytesIO):
            name = "large.csv"
            size = 5
            file_id = "streamlit-upload-1"

            def read(self, size: int = -1) -> bytes:
                if size == 0:
                    return b""
                raise AssertionError("file contents should not be read to identify uploads")

        self.assertEqual(
            upload_key(IdentifiedUpload(b"large")),
            "large.csv:5:streamlit-upload-1",
        )

    def test_cleaning_and_export_keep_all_rows_on_disk(self):
        dataset = self.load_csv(
            "Full Name,Age,City\n"
            " Alice ,10,Paris\n"
            " Alice ,10.0,Paris\n"
            "Chloé,30,Lyon\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = str(Path(temp_dir) / "clean.csv")
            try:
                dataset.apply_cleaning(
                    strategy="Laisser",
                    custom_value="",
                    strip_spaces=True,
                    lowercase=True,
                    clean_headers=True,
                    remove_accents=True,
                    empty_to_na=False,
                    remove_duplicates=True,
                    lowercase_headers=False,
                    numeric_columns={"Age"},
                    make_unique_column_names=make_unique_column_names,
                    normalize_text=normalize_text,
                )
                self.assertEqual(dataset.row_count_for(), 2)
                self.assertEqual(
                    dataset.preview().columns.tolist(),
                    ["full_name", "age", "city"],
                )
                dataset.export_csv(output_path)
                exported = Path(output_path).read_text(encoding="utf-8-sig")
                self.assertIn("alice,10,paris", exported)
                self.assertIn("chloe,30,lyon", exported)
                self.assertEqual(len(exported.strip().splitlines()), 3)
            finally:
                dataset.delete()

    def test_median_imputation_uses_values_from_the_full_file(self):
        dataset = self.load_csv(
            "value,category\n1,a\n2,b\n,c\n3,d\n4,e\n"
        )
        try:
            dataset.apply_cleaning(
                strategy="Remplacer par médiane",
                custom_value="",
                strip_spaces=False,
                lowercase=False,
                clean_headers=False,
                remove_accents=False,
                empty_to_na=False,
                remove_duplicates=False,
                lowercase_headers=False,
                numeric_columns={"value"},
                make_unique_column_names=make_unique_column_names,
                normalize_text=normalize_text,
            )
            values = dataset.preview()["value"].astype(float).tolist()
            self.assertEqual(values, [1.0, 2.0, 2.5, 3.0, 4.0])
        finally:
            dataset.delete()


if __name__ == "__main__":
    unittest.main()
