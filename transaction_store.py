from contextlib import closing
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import os
from pathlib import Path
import sqlite3


class TransactionStore:
    """Persist financial transactions in a local SQLite database."""

    def __init__(self, database_path: str | Path | None = None):
        configured_path = database_path or os.environ.get("TRANSACTIONS_DB_PATH")
        self.database_path = Path(configured_path) if configured_path else (
            Path(__file__).resolve().parent / "data" / "transactions.sqlite3"
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=30)

    def initialize(self) -> None:
        with closing(self.connect()) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        transaction_date TEXT NOT NULL,
                        description TEXT NOT NULL,
                        amount_cents INTEGER NOT NULL,
                        category TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS "
                    "idx_transactions_date ON transactions(transaction_date DESC, id DESC)"
                )

    @staticmethod
    def _to_cents(amount: Decimal | int | float | str) -> int:
        try:
            decimal_amount = Decimal(str(amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("Le montant doit être un nombre valide.") from exc
        if not decimal_amount.is_finite():
            raise ValueError("Le montant doit être un nombre fini.")
        try:
            rounded_amount = decimal_amount.quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        except InvalidOperation as exc:
            raise ValueError("Le montant dépasse la précision autorisée.") from exc
        amount_cents = int(rounded_amount * 100)
        if abs(amount_cents) > 2**63 - 1:
            raise ValueError("Le montant dépasse la capacité de stockage SQLite.")
        return amount_cents

    def add(
        self,
        transaction_date: date | str,
        description: str,
        amount: Decimal | int | float | str,
        category: str,
    ) -> int:
        if isinstance(transaction_date, date):
            date_value = transaction_date.isoformat()
        else:
            try:
                date_value = date.fromisoformat(transaction_date).isoformat()
            except ValueError as exc:
                raise ValueError("La date doit être une date valide au format ISO.") from exc

        description = description.strip()
        category = category.strip()
        if not description:
            raise ValueError("La description est obligatoire.")
        if not category:
            raise ValueError("La catégorie est obligatoire.")

        amount_cents = self._to_cents(amount)
        with closing(self.connect()) as connection:
            with connection:
                cursor = connection.execute(
                    """
                    INSERT INTO transactions (
                        transaction_date,
                        description,
                        amount_cents,
                        category
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (date_value, description, amount_cents, category),
                )
                return int(cursor.lastrowid)

    def list_transactions(self, limit: int = 500) -> list[dict[str, object]]:
        if limit < 1:
            raise ValueError("La limite d'affichage doit être supérieure à zéro.")
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """
                SELECT id, transaction_date, description, amount_cents, category
                FROM transactions
                ORDER BY transaction_date DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "id": row[0],
                "date": row[1],
                "description": row[2],
                "amount_cents": row[3],
                "category": row[4],
            }
            for row in rows
        ]

    def summary(self) -> tuple[int, int]:
        with closing(self.connect()) as connection:
            count, total_cents = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount_cents), 0) FROM transactions"
            ).fetchone()
        return int(count), int(total_cents)

    def delete(self, transaction_id: int) -> bool:
        with closing(self.connect()) as connection:
            with connection:
                cursor = connection.execute(
                    "DELETE FROM transactions WHERE id = ?",
                    (transaction_id,),
                )
                return cursor.rowcount == 1
