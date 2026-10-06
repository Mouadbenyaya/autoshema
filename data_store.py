from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
import tempfile
import unicodedata
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Callable, Generator, Iterable, Protocol

import pandas as pd


CSV_CHUNK_SIZE = 50_000
PREVIEW_SIZE = 10_000


class UploadedFileLike(Protocol):
    name: str
    size: int

    def read(self, size: int = -1) -> bytes: ...

    def seek(self, offset: int, whence: int = 0) -> int: ...


def _detect_csv_separator(uploaded_file: UploadedFileLike) -> str:
    uploaded_file.seek(0)
    sample = uploaded_file.read(64 * 1024).decode("utf-8-sig", errors="replace")
    uploaded_file.seek(0)
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def upload_key(uploaded_file: UploadedFileLike) -> str:
    """Return a stable identity for a Streamlit upload without copying its contents."""
    file_id = getattr(uploaded_file, "file_id", None)
    if file_id:
        return f"{uploaded_file.name}:{uploaded_file.size}:{file_id}"

    digest = hashlib.sha256()
    uploaded_file.seek(0)
    for chunk in iter(lambda: uploaded_file.read(1024 * 1024), b""):
        digest.update(chunk)
    uploaded_file.seek(0)
    return f"{uploaded_file.name}:{uploaded_file.size}:{digest.hexdigest()}"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


class DiskBackedCsv:
    """Store large CSVs in SQLite and only materialize bounded previews in memory."""

    def __init__(
        self,
        database_path: str,
        columns: list[str],
        row_count: int,
        numeric_columns: set[str] | None = None,
    ):
        self.database_path = database_path
        self.columns = columns
        self.row_count = row_count
        self.numeric_columns = numeric_columns or set()

    @classmethod
    def from_upload(
        cls,
        uploaded_file: UploadedFileLike,
        make_unique_column_names: Callable[[Iterable[object]], list[str]],
    ) -> DiskBackedCsv:
        fd, database_path = tempfile.mkstemp(prefix="studio-data-", suffix=".sqlite3")
        os.close(fd)
        row_count = 0
        numeric_columns: set[str] = set()

        try:
            uploaded_file.seek(0)
            separator = _detect_csv_separator(uploaded_file)
            header = pd.read_csv(
                uploaded_file,
                sep=separator,
                engine="c",
                on_bad_lines="skip",
                nrows=0,
            )
            columns = make_unique_column_names(header.columns)
            uploaded_file.seek(0)

            with closing(sqlite3.connect(database_path)) as connection, connection:
                if columns:
                    numeric_candidates = set(columns)
                    definitions = ", ".join(
                        f"{_quote_identifier(column)} TEXT" for column in columns
                    )
                    connection.execute(f"CREATE TABLE source ({definitions})")
                    placeholders = ", ".join("?" for _ in columns)
                    insert_sql = f"INSERT INTO source VALUES ({placeholders})"

                    chunks = pd.read_csv(
                        uploaded_file,
                        sep=separator,
                        engine="c",
                        on_bad_lines="skip",
                        chunksize=CSV_CHUNK_SIZE,
                        dtype=str,
                    )
                    for chunk in chunks:
                        chunk.columns = columns
                        for column in tuple(numeric_candidates):
                            values = chunk[column].dropna()
                            if not values.empty and not pd.to_numeric(
                                values,
                                errors="coerce",
                            ).notna().all():
                                numeric_candidates.remove(column)
                        rows = (
                            tuple(None if pd.isna(value) else str(value) for value in row)
                            for row in chunk.itertuples(index=False, name=None)
                        )
                        connection.executemany(insert_sql, rows)
                        row_count += len(chunk)
                    numeric_columns = numeric_candidates

            uploaded_file.seek(0)
            return cls(database_path, columns, row_count, numeric_columns)
        except Exception:
            uploaded_file.seek(0)
            Path(database_path).unlink(missing_ok=True)
            raise

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path, timeout=120)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def table_exists(self, table: str = "cleaned") -> bool:
        with self.connect() as connection:
            result = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
        return result is not None

    def active_table(self) -> str:
        return "cleaned" if self.table_exists() else "source"

    def row_count_for(self, table: str | None = None) -> int:
        table = table or self.active_table()
        with self.connect() as connection:
            query = f"SELECT COUNT(*) FROM {_quote_identifier(table)}"
            return int(connection.execute(query).fetchone()[0])

    def metrics(self) -> tuple[int, int]:
        if not self.columns:
            return 0, self.row_count

        null_terms = " + ".join(
            f"SUM(CASE WHEN {_quote_identifier(column)} IS NULL THEN 1 ELSE 0 END)"
            for column in self.columns
        )
        group_columns = ", ".join(
            (
                f"CAST({_quote_identifier(column)} AS NUMERIC)"
                if column in self.numeric_columns
                else _quote_identifier(column)
            )
            for column in self.columns
        )
        query = (
            f"SELECT COALESCE(({null_terms}), 0) FROM source"
        )
        duplicate_query = (
            f"SELECT COALESCE(SUM(duplicates - 1), 0) FROM ("
            f"SELECT COUNT(*) AS duplicates FROM source GROUP BY {group_columns} "
            "HAVING COUNT(*) > 1)"
        )
        with self.connect() as connection:
            connection.execute("PRAGMA temp_store = FILE")
            connection.execute("PRAGMA cache_size = -65536")
            missing = int(connection.execute(query).fetchone()[0])
            duplicates = int(connection.execute(duplicate_query).fetchone()[0])
        return missing, duplicates

    def preview(
        self,
        table: str | None = None,
        limit: int = PREVIEW_SIZE,
    ) -> pd.DataFrame:
        table = table or self.active_table()
        with self.connect() as connection:
            return pd.read_sql_query(
                f"SELECT * FROM {_quote_identifier(table)} LIMIT ?",
                connection,
                params=(limit,),
            )

    def column_quality(
        self,
        infer_sql_type: Callable[[pd.Series], str],
        table: str | None = None,
    ) -> pd.DataFrame:
        table = table or self.active_table()
        rows = []
        sample = self.preview(table, limit=5_000)
        with self.connect() as connection:
            columns = [
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({_quote_identifier(table)})"
                ).fetchall()
            ]
        with self.connect() as connection:
            connection.execute("PRAGMA temp_store = FILE")
            connection.execute("PRAGMA cache_size = -65536")
            statistics = {}
            for start in range(0, len(columns), 64):
                batch = columns[start : start + 64]
                terms = []
                for column in batch:
                    quoted = _quote_identifier(column)
                    distinct_value = (
                        f"CAST({quoted} AS NUMERIC)"
                        if column in self.numeric_columns
                        else quoted
                    )
                    terms.extend(
                        (
                            f"SUM(CASE WHEN {quoted} IS NULL THEN 1 ELSE 0 END)",
                            f"COUNT(DISTINCT {distinct_value})",
                        )
                    )
                query = (
                    f"SELECT {', '.join(terms)} "
                    f"FROM {_quote_identifier(table)}"
                )
                values = connection.execute(query).fetchone()
                for index, column in enumerate(batch):
                    statistics[column] = (
                        int(values[index * 2] or 0),
                        int(values[index * 2 + 1] or 0),
                    )

            for column in columns:
                missing, unique = statistics[column]
                rows.append(
                    {
                        "Colonne": column,
                        "Type SQL estimé": infer_sql_type(sample[column]),
                        "Valeurs manquantes": int(missing or 0),
                        "Valeurs uniques": int(unique or 0),
                    }
                )
        return pd.DataFrame(rows)

    def apply_cleaning(
        self,
        *,
        strategy: str,
        custom_value: str,
        strip_spaces: bool,
        lowercase: bool,
        clean_headers: bool,
        remove_accents: bool,
        empty_to_na: bool,
        remove_duplicates: bool,
        lowercase_headers: bool,
        numeric_columns: set[str],
        make_unique_column_names: Callable[[Iterable[object]], list[str]],
        normalize_text: Callable[[object], str],
    ) -> list[str]:
        output_columns = self.columns
        if clean_headers:
            output_columns = make_unique_column_names(
                normalize_text(column).replace(" ", "_") for column in output_columns
            )
        if lowercase_headers:
            output_columns = make_unique_column_names(
                column.lower() for column in output_columns
            )

        expressions = []
        parameters = []
        for column in self.columns:
            quoted = _quote_identifier(column)
            expression = quoted

            if strategy == "Remplacer par moyenne" and column in numeric_columns:
                fill = f"(SELECT CAST(AVG(CAST({quoted} AS REAL)) AS TEXT) FROM source)"
                expression = f"COALESCE({expression}, {fill})"
            elif strategy == "Remplacer par médiane" and column in numeric_columns:
                fill = (
                    f"(SELECT CAST(AVG(value) AS TEXT) FROM ("
                    f"SELECT CAST({quoted} AS REAL) AS value FROM source "
                    f"WHERE {quoted} IS NOT NULL ORDER BY value "
                    "LIMIT 2 - (SELECT COUNT(*) FROM source "
                    f"WHERE {quoted} IS NOT NULL) % 2 OFFSET "
                    f"(SELECT (COUNT(*) - 1) / 2 FROM source WHERE {quoted} IS NOT NULL)))"
                )
                expression = f"COALESCE({expression}, {fill})"
            elif strategy == "Remplacer par le mode":
                if column in numeric_columns:
                    fill = (
                        f"(SELECT CAST(CAST({quoted} AS NUMERIC) AS TEXT) FROM source "
                        f"WHERE {quoted} IS NOT NULL GROUP BY CAST({quoted} AS NUMERIC) "
                        f"ORDER BY COUNT(*) DESC, CAST({quoted} AS NUMERIC) LIMIT 1)"
                    )
                else:
                    fill = (
                        f"(SELECT {quoted} FROM source WHERE {quoted} IS NOT NULL "
                        f"GROUP BY {quoted} ORDER BY COUNT(*) DESC, {quoted} LIMIT 1)"
                    )
                expression = f"COALESCE({expression}, {fill})"
            elif strategy == "Remplacer par valeur personnalisée":
                expression = f"COALESCE({expression}, ?)"
                parameters.append(custom_value or "Unknown")

            if strip_spaces:
                expression = f"strip_unicode({expression})"
            if lowercase:
                expression = f"lower_unicode({expression})"
            if remove_accents:
                expression = f"remove_accents({expression})"
            if empty_to_na:
                expression = (
                    f"CASE WHEN TRIM({expression}) = '' "
                    f"THEN NULL ELSE {expression} END"
                )

            expressions.append(
                f"{expression} AS {_quote_identifier(output_columns[len(expressions)])}"
            )

        where = ""
        if strategy == "Supprimer les lignes concernées" and self.columns:
            where = " WHERE " + " AND ".join(
                f"{_quote_identifier(column)} IS NOT NULL" for column in self.columns
            )

        select_columns = ", ".join(expressions) if expressions else "*"
        select = f"SELECT {select_columns} FROM source{where}"
        if remove_duplicates and output_columns:
            rank_column = "_studio_dedup_rank"
            while rank_column in output_columns:
                rank_column += "_"
            selected_columns = ", ".join(
                _quote_identifier(column) for column in output_columns
            )
            partition_columns = ", ".join(
                (
                    f"CAST({_quote_identifier(output_columns[index])} AS NUMERIC)"
                    if column in numeric_columns
                    else _quote_identifier(output_columns[index])
                )
                for index, column in enumerate(self.columns)
            )
            select = (
                f"WITH transformed AS ({select}) "
                f"SELECT {selected_columns} FROM ("
                f"SELECT *, ROW_NUMBER() OVER (PARTITION BY {partition_columns}) "
                f"AS {_quote_identifier(rank_column)} FROM transformed) "
                f"WHERE {_quote_identifier(rank_column)} = 1"
            )

        with self.connect() as connection:
            connection.create_function(
                "strip_unicode",
                1,
                lambda value: value.strip() if value is not None else None,
            )
            connection.create_function(
                "lower_unicode",
                1,
                lambda value: value.lower() if value is not None else None,
            )
            connection.create_function(
                "remove_accents",
                1,
                lambda value: (
                    "".join(
                        char
                        for char in unicodedata.normalize("NFKD", value)
                        if not unicodedata.combining(char)
                    )
                    if value is not None
                    else None
                ),
            )
            connection.execute("DROP TABLE IF EXISTS cleaned")
            connection.execute(
                f"CREATE TABLE cleaned AS {select}",
                parameters,
            )
        return output_columns

    def export_csv(self, output_path: str, table: str | None = None) -> None:
        table = table or self.active_table()
        with (
            self.connect() as connection,
            open(output_path, "w", encoding="utf-8-sig", newline="") as output,
        ):
            cursor = connection.execute(f"SELECT * FROM {_quote_identifier(table)}")
            writer = csv.writer(output)
            writer.writerow([description[0] for description in cursor.description])
            while rows := cursor.fetchmany(CSV_CHUNK_SIZE):
                writer.writerows(rows)

    def delete(self) -> None:
        Path(self.database_path).unlink(missing_ok=True)
