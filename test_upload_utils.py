import unittest
from io import BytesIO

from upload_utils import upload_key


class UploadKeyTests(unittest.TestCase):
    def test_uses_streamlit_file_id_without_reading_file_contents(self):
        class IdentifiedUpload(BytesIO):
            name = "large.csv"
            size = 5
            file_id = "streamlit-upload-1"

            def read(self, size: int = -1) -> bytes:
                if size == 0:
                    return b""
                raise AssertionError("file contents should not be read")

        upload = IdentifiedUpload(b"large")

        self.assertEqual(
            upload_key(upload),
            "large.csv:5:streamlit-upload-1",
        )

    def test_hashes_contents_when_file_id_is_not_available(self):
        upload = BytesIO(b"sample")
        upload.name = "sample.csv"
        upload.size = 6

        first_key = upload_key(upload)
        second_key = upload_key(upload)

        self.assertEqual(first_key, second_key)
        self.assertTrue(first_key.startswith("sample.csv:6:"))
        self.assertEqual(upload.tell(), 0)


if __name__ == "__main__":
    unittest.main()
