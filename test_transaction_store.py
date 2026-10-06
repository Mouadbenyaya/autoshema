import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from transaction_store import TransactionStore


class TransactionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "transactions.sqlite3"
        self.store = TransactionStore(self.database_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_transactions_persist_and_summary_uses_exact_cents(self):
        self.store.add(date(2026, 10, 6), "Salaire", Decimal("1234.56"), "Revenu")
        self.store.add("2026-10-05", "Courses", "-32.10", "Alimentation")

        reopened_store = TransactionStore(self.database_path)

        self.assertEqual(reopened_store.summary(), (2, 120246))
        transactions = reopened_store.list_transactions()
        self.assertEqual(transactions[0]["description"], "Salaire")
        self.assertEqual(transactions[0]["amount_cents"], 123456)
        self.assertEqual(transactions[1]["amount_cents"], -3210)

    def test_amount_rounds_to_cents_without_binary_float_artifacts(self):
        self.store.add("2026-10-06", "Ajustement", 0.1 + 0.2, "Divers")

        self.assertEqual(self.store.list_transactions()[0]["amount_cents"], 30)

    def test_add_rejects_missing_description_category_and_invalid_amount(self):
        with self.assertRaisesRegex(ValueError, "description est obligatoire"):
            self.store.add("2026-10-06", " ", 10, "Divers")
        with self.assertRaisesRegex(ValueError, "catégorie est obligatoire"):
            self.store.add("2026-10-06", "Achat", 10, " ")
        with self.assertRaisesRegex(ValueError, "nombre valide"):
            self.store.add("2026-10-06", "Achat", "not-a-number", "Divers")
        with self.assertRaisesRegex(ValueError, "capacité de stockage SQLite"):
            self.store.add("2026-10-06", "Achat", "100000000000000000", "Divers")
        with self.assertRaisesRegex(ValueError, "date valide"):
            self.store.add("06/10/2026", "Achat", 10, "Divers")

        self.assertEqual(self.store.summary(), (0, 0))

    def test_list_limit_and_delete_are_applied(self):
        first_id = self.store.add("2026-10-05", "Premier", 10, "Divers")
        second_id = self.store.add("2026-10-06", "Second", 20, "Divers")

        transactions = self.store.list_transactions(limit=1)

        self.assertEqual([item["id"] for item in transactions], [second_id])
        self.assertTrue(self.store.delete(first_id))
        self.assertFalse(self.store.delete(first_id))
        self.assertEqual(self.store.summary(), (1, 2000))


if __name__ == "__main__":
    unittest.main()
