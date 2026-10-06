import os
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from datetime import date
from decimal import Decimal

import pandas as pd
import streamlit as st
from data_store import DiskBackedCsv, upload_key
from transaction_store import TransactionStore


st.set_page_config(
    page_title="Studio de données",
    page_icon=":material/query_stats:",
    layout="wide",
    initial_sidebar_state="expanded",
)

LARGE_CSV_THRESHOLD_BYTES = 32 * 1024 * 1024
TRANSACTION_DISPLAY_LIMIT = 500


def render_transactions() -> None:
    """Render the local financial transaction register."""
    st.subheader("Transactions", icon=":material/account_balance_wallet:")
    st.caption(
        "Registre local SQLite. Les montants positifs sont des entrées; "
        "les montants négatifs sont des dépenses."
    )

    try:
        store = TransactionStore()
        transaction_count, total_cents = store.summary()
    except (sqlite3.Error, OSError) as exc:
        st.error(f"Impossible d’ouvrir la base SQLite des transactions : {exc}")
        return

    with st.container(horizontal=True):
        st.metric(
            "Transactions enregistrées",
            f"{transaction_count:,}".replace(",", " "),
            border=True,
        )
        total_amount = Decimal(total_cents) / 100
        st.metric(
            "Solde net",
            f"{total_amount:,.2f}".replace(",", " "),
            border=True,
        )

    st.markdown("### Ajouter une transaction")
    with st.form("add_transaction", border=True):
        transaction_date = st.date_input("Date", value=date.today())
        description = st.text_input("Description")
        amount = st.number_input(
            "Montant",
            value=0.0,
            step=0.01,
            format="%.2f",
            help="Valeur positive pour une entrée et négative pour une dépense.",
        )
        category = st.text_input("Catégorie")
        submitted = st.form_submit_button(
            "Enregistrer la transaction",
            type="primary",
            icon=":material/save:",
        )

    if submitted:
        try:
            store.add(transaction_date, description, amount, category)
        except ValueError as exc:
            st.error(str(exc))
        except sqlite3.Error as exc:
            st.error(f"Impossible d’enregistrer la transaction : {exc}")
        else:
            st.toast("Transaction enregistrée", icon=":material/check_circle:")
            st.rerun()

    st.markdown("### Historique")
    try:
        transactions = store.list_transactions(limit=TRANSACTION_DISPLAY_LIMIT)
    except sqlite3.Error as exc:
        st.error(f"Impossible de lire les transactions : {exc}")
        return

    if not transactions:
        st.info("Aucune transaction enregistrée pour le moment.")
        return

    table_rows = [
        {
            "Date": transaction["date"],
            "Description": transaction["description"],
            "Montant": f"{Decimal(transaction['amount_cents']) / 100:.2f}",
            "Catégorie": transaction["category"],
        }
        for transaction in transactions
    ]
    st.dataframe(pd.DataFrame(table_rows), width="stretch", hide_index=True)
    if transaction_count > TRANSACTION_DISPLAY_LIMIT:
        st.caption(
            f"Affichage des {TRANSACTION_DISPLAY_LIMIT} transactions les plus récentes."
        )

    transaction_options = {
        int(transaction["id"]): (
            f"{transaction['date']} · {transaction['description']} · "
            f"{Decimal(transaction['amount_cents']) / 100:.2f} · "
            f"{transaction['category']}"
        )
        for transaction in transactions
    }
    with st.form("delete_transaction"):
        selected_id = st.selectbox(
            "Transaction à supprimer",
            options=list(transaction_options),
            format_func=transaction_options.get,
        )
        delete_submitted = st.form_submit_button(
            "Supprimer la transaction sélectionnée",
            icon=":material/delete:",
        )
    if delete_submitted:
        try:
            deleted = store.delete(selected_id)
        except sqlite3.Error as exc:
            st.error(f"Impossible de supprimer la transaction : {exc}")
        else:
            if deleted:
                st.toast("Transaction supprimée", icon=":material/delete:")
                st.rerun()
            else:
                st.warning("Cette transaction n’existe plus.")


def normalize_text(value):
    """Return a normalized lowercase string without accents."""
    if value is None:
        return ""
    value = str(value).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return value


def remove_accents(value):
    """Remove accents from a string while preserving case behavior."""
    if value is None:
        return value
    if not isinstance(value, str):
        return value
    value = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def sanitize_column_name(name: object) -> str:
    """Return a safe SQL-friendly column name."""
    text = str(name).strip()
    if not text:
        return "column"
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_]", "_", text)
    if text[0].isdigit():
        text = f"_{text}"
    return text


def make_unique_column_names(columns) -> list[str]:
    """Sanitize headers and add deterministic suffixes for duplicate names."""
    unique_names = []
    used_names = set()
    for column in columns:
        base_name = sanitize_column_name(column)
        candidate = base_name
        suffix = 2
        while candidate in used_names:
            candidate = f"{base_name}_{suffix}"
            suffix += 1
        unique_names.append(candidate)
        used_names.add(candidate)
    return unique_names


def infer_sql_type(series: pd.Series) -> str:
    """Infer a suitable SQL type using lightweight heuristics."""
    non_null = series.dropna()
    if non_null.empty:
        return "VARCHAR"

    def is_integer_like(value) -> bool:
        if pd.isna(value):
            return True
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value).is_integer()
        if isinstance(value, str):
            cleaned = value.strip()
            return bool(re.fullmatch(r"[-+]?\d+", cleaned))
        return False

    def is_date_like(value) -> bool:
        if pd.isna(value):
            return True
        try:
            pd.to_datetime(str(value).strip(), errors="raise")
            return True
        except (TypeError, ValueError):
            return False

    if non_null.map(is_date_like).all():
        try:
            parsed = pd.to_datetime(non_null.astype(str), errors="coerce")
            if parsed.notna().all():
                return "DATE"
        except Exception:
            pass

    if non_null.map(is_integer_like).all():
        return "INT"

    numeric_values = pd.to_numeric(non_null.astype(str).str.strip(), errors="coerce")
    if numeric_values.notna().all():
        return "FLOAT"

    if non_null.map(lambda v: str(v).strip().lower() in {"true", "false", "yes", "no", "y", "n", "1", "0"}).all():
        return "BOOLEAN"

    return "VARCHAR"


def build_create_table_sql(df: pd.DataFrame, table_name: str) -> str:
    """Generate a CREATE TABLE script from the DataFrame."""
    if len(df.columns) == 0:
        raise ValueError("The dataset must have at least one column to generate SQL.")

    table_name = sanitize_column_name(table_name).lower()
    sql_lines = [f'CREATE TABLE "{table_name}" (']
    for column in df.columns:
        sql_type = infer_sql_type(df[column])
        safe_name = sanitize_column_name(column)
        sql_lines.append(f'    "{safe_name}" {sql_type},')
    sql_lines[-1] = sql_lines[-1].rstrip(",")
    sql_lines.append(");")
    return "\n".join(sql_lines)


def load_uploaded_data(uploaded_file) -> pd.DataFrame:
    """Load CSV or Excel data with friendly error handling."""
    if uploaded_file is None:
        raise ValueError("No file uploaded.")

    file_name = uploaded_file.name
    file_ext = file_name.rsplit(".", 1)[1].lower() if "." in file_name else ""

    try:
        if file_ext == "csv":
            df = pd.read_csv(uploaded_file, sep=None, engine="python", on_bad_lines="skip")
        elif file_ext in {"xlsx", "xls"}:
            df = pd.read_excel(uploaded_file)
        else:
            raise ValueError("Unsupported file type. Please upload a CSV or Excel file.")
    except Exception as exc:
        raise ValueError(f"Unable to read the uploaded file: {exc}") from exc

    if df.empty:
        st.warning("The uploaded file appears to be empty.")

    df.columns = make_unique_column_names(df.columns)
    return df


def apply_text_cleaning(
    df: pd.DataFrame,
    strip_spaces: bool,
    lowercase: bool,
    clean_headers: bool,
    remove_accents: bool = False,
    empty_to_na: bool = False,
    remove_duplicates: bool = False,
    lowercase_headers: bool = False,
):
    """Apply text cleaning options safely to object columns and headers."""
    cleaned = df.copy()

    if strip_spaces:
        for col in cleaned.select_dtypes(include=["object"]).columns:
            cleaned[col] = cleaned[col].map(lambda x: x.strip() if isinstance(x, str) else x)

    if lowercase:
        for col in cleaned.select_dtypes(include=["object"]).columns:
            cleaned[col] = cleaned[col].map(lambda x: x.lower() if isinstance(x, str) else x)

    if remove_accents:
        for col in cleaned.select_dtypes(include=["object"]).columns:
            cleaned[col] = cleaned[col].map(lambda x: remove_accents(x) if isinstance(x, str) else x)

    if empty_to_na:
        for col in cleaned.columns:
            cleaned[col] = cleaned[col].replace(r"^\s*$", pd.NA, regex=True)

    if remove_duplicates:
        cleaned = cleaned.drop_duplicates()

    if clean_headers:
        cleaned.columns = make_unique_column_names(
            normalize_text(col).replace(" ", "_") for col in cleaned.columns
        )

    if lowercase_headers:
        cleaned.columns = make_unique_column_names(
            str(col).lower() for col in cleaned.columns
        )

    return cleaned


def apply_missing_value_strategy(df: pd.DataFrame, strategy: str, custom_value: str = ""):
    """Apply a selected missing-value strategy to the dataset."""
    cleaned = df.copy()
    if strategy == "Laisser":
        return cleaned

    if strategy == "Supprimer les lignes concernées":
        return cleaned.dropna()

    for col in cleaned.columns:
        if cleaned[col].isna().sum() == 0:
            continue

        if strategy == "Remplacer par moyenne":
            if pd.api.types.is_numeric_dtype(cleaned[col]):
                cleaned[col] = cleaned[col].fillna(cleaned[col].mean())
        elif strategy == "Remplacer par médiane":
            if pd.api.types.is_numeric_dtype(cleaned[col]):
                cleaned[col] = cleaned[col].fillna(cleaned[col].median())
        elif strategy == "Remplacer par valeur personnalisée":
            cleaned[col] = cleaned[col].fillna(custom_value if custom_value else "Unknown")
        elif strategy == "Remplacer par le mode":
            mode_value = cleaned[col].mode(dropna=True)
            if not mode_value.empty:
                cleaned[col] = cleaned[col].fillna(mode_value.iloc[0])

    return cleaned


def main() -> None:
    with st.sidebar:
        st.markdown("## :material/analytics: Studio de données")
        st.caption("Explorer · nettoyer · exporter · transactions")
        st.markdown("**Formats pris en charge**")
        st.caption("CSV · XLSX · XLS")

    st.title("Studio de données", icon=":material/query_stats:")
    st.caption("Analysez, préparez et exportez votre jeu de données.")

    with st.container(border=True):
        upload_col, status_col = st.columns([1.35, 1], vertical_alignment="center")
        with upload_col:
            uploaded_file = st.file_uploader(
                "Fichier source",
                type=["csv", "xlsx", "xls"],
                help="Importez un fichier CSV, XLSX ou XLS.",
            )
        with status_col:
            if uploaded_file is None:
                st.badge("En attente", icon=":material/upload_file:", color="gray")
                st.caption("Choisissez un fichier pour commencer.")
            else:
                st.badge("Fichier chargé", icon=":material/check_circle:", color="green")
                st.caption(uploaded_file.name)

    current_view = st.segmented_control(
        "Espace de travail",
        ["Explorer", "Nettoyer", "Exporter", "Transactions"],
        default="Explorer",
        key="workspace_view",
        label_visibility="collapsed",
    )

    if uploaded_file is None:
        database_path = st.session_state.pop("large_csv_database_path", None)
        if database_path:
            DiskBackedCsv(database_path, [], 0).delete()
        export_path = st.session_state.pop("large_csv_export_path", None)
        if export_path:
            Path(export_path).unlink(missing_ok=True)
        for key in (
            "upload_source",
            "uploaded_df",
            "cleaned_df",
            "large_csv_columns",
            "large_csv_numeric_columns",
            "large_csv_row_count",
            "large_csv_metrics",
            "large_csv_export_key",
            "large_csv_quality",
        ):
            st.session_state.pop(key, None)

    if current_view == "Transactions":
        render_transactions()
        return

    if uploaded_file is None:
        st.info("Importez un fichier pour explorer, nettoyer ou exporter vos données.")
        return

    source_key = upload_key(uploaded_file)
    file_ext = uploaded_file.name.rsplit(".", 1)[-1].lower()
    is_large_csv = (
        file_ext == "csv"
        and uploaded_file.size >= LARGE_CSV_THRESHOLD_BYTES
    )

    try:
        if st.session_state.get("upload_source") != source_key:
            old_database_path = st.session_state.pop("large_csv_database_path", None)
            if old_database_path:
                DiskBackedCsv(old_database_path, [], 0).delete()
            old_export_path = st.session_state.pop("large_csv_export_path", None)
            if old_export_path:
                Path(old_export_path).unlink(missing_ok=True)
            for key in (
                "large_csv_columns",
                "large_csv_numeric_columns",
                "large_csv_row_count",
                "large_csv_metrics",
                "large_csv_export_key",
                "large_csv_quality",
            ):
                st.session_state.pop(key, None)

            if is_large_csv:
                with st.spinner("Import du CSV volumineux par blocs..."):
                    dataset = DiskBackedCsv.from_upload(
                        uploaded_file,
                        make_unique_column_names,
                    )
                    if not dataset.columns:
                        dataset.delete()
                        st.warning("Le CSV ne contient aucune colonne à analyser.")
                        return
                    try:
                        missing_count, duplicate_count = dataset.metrics()
                    except sqlite3.Error:
                        dataset.delete()
                        raise
                st.session_state.large_csv_database_path = dataset.database_path
                st.session_state.large_csv_columns = dataset.columns
                st.session_state.large_csv_numeric_columns = dataset.numeric_columns
                st.session_state.large_csv_row_count = dataset.row_count
                st.session_state.large_csv_metrics = (missing_count, duplicate_count)
            else:
                df = load_uploaded_data(uploaded_file)
                st.session_state.uploaded_df = df
                st.session_state.cleaned_df = df.copy()
            st.session_state.upload_source = source_key

        if is_large_csv:
            dataset = DiskBackedCsv(
                st.session_state.large_csv_database_path,
                st.session_state.large_csv_columns,
                st.session_state.large_csv_row_count,
                st.session_state.large_csv_numeric_columns,
            )
            df = dataset.preview("source")
            for column in df.columns:
                numeric = pd.to_numeric(df[column], errors="coerce")
                if df[column].notna().any() and numeric[df[column].notna()].notna().all():
                    df[column] = numeric
            cleaned_df = dataset.preview()
            for column in cleaned_df.columns:
                numeric = pd.to_numeric(cleaned_df[column], errors="coerce")
                if (
                    cleaned_df[column].notna().any()
                    and numeric[cleaned_df[column].notna()].notna().all()
                ):
                    cleaned_df[column] = numeric
            missing_count, duplicate_count = st.session_state.large_csv_metrics
        else:
            df = st.session_state.uploaded_df
            cleaned_df = st.session_state.cleaned_df
            duplicate_count = int(df.duplicated().sum())
            missing_count = int(df.isna().sum().sum())
    except (ValueError, pd.errors.ParserError, sqlite3.Error, OSError) as exc:
        st.error(str(exc))
        return

    if is_large_csv:
        st.info(
            "CSV volumineux traité sur disque par blocs. "
            "L’aperçu affiche uniquement un échantillon limité."
        )

    with st.container(horizontal=True):
        row_count = (
            st.session_state.large_csv_row_count if is_large_csv else len(df)
        )
        st.metric("Lignes", f"{row_count:,}".replace(",", " "), border=True)
        st.metric("Colonnes", df.shape[1], border=True)
        st.metric("Doublons", duplicate_count, border=True)
        st.metric("Valeurs manquantes", missing_count, border=True)

    if current_view == "Explorer":
        st.subheader("Aperçu des données", icon=":material/table_chart:")
        st.dataframe(df.head(100), width="stretch", height=320, hide_index=True)

        with st.expander("Qualité par colonne", icon=":material/fact_check:"):
            if is_large_csv:
                if st.button("Calculer la qualité exacte", key="large_csv_quality_button"):
                    try:
                        with st.spinner("Calcul de la qualité par colonne..."):
                            st.session_state.large_csv_quality = dataset.column_quality(
                                infer_sql_type,
                                table="source",
                            )
                    except sqlite3.Error as exc:
                        st.error(f"Le calcul de qualité a échoué : {exc}")
                quality = st.session_state.get("large_csv_quality")
                if quality is not None:
                    st.dataframe(quality, width="stretch", hide_index=True)
            else:
                quality_table = [
                    {
                        "Colonne": column,
                        "Type SQL estimé": infer_sql_type(df[column]),
                        "Valeurs manquantes": int(df[column].isna().sum()),
                        "Valeurs uniques": int(df[column].nunique(dropna=True)),
                    }
                    for column in df.columns
                ]
                if quality_table:
                    st.dataframe(
                        pd.DataFrame(quality_table),
                        width="stretch",
                        hide_index=True,
                    )
                else:
                    st.caption("Aucune colonne à analyser.")

    elif current_view == "Nettoyer":
        st.subheader("Préparer les données", icon=":material/tune:")
        with st.form("cleaning_options", border=True):
            strategy = st.selectbox(
                "Valeurs manquantes",
                [
                    "Laisser",
                    "Remplacer par moyenne",
                    "Remplacer par médiane",
                    "Remplacer par le mode",
                    "Remplacer par valeur personnalisée",
                    "Supprimer les lignes concernées",
                ],
            )
            custom_value = ""
            if strategy == "Remplacer par valeur personnalisée":
                custom_value = st.text_input("Valeur de remplacement", value="Unknown")

            text_col, header_col = st.columns(2)
            with text_col:
                st.markdown("**Texte**")
                strip_spaces = st.checkbox("Supprimer les espaces superflus")
                lowercase = st.checkbox("Convertir en minuscules")
                remove_accents_option = st.checkbox("Supprimer les accents")
                empty_to_na = st.checkbox("Convertir les cellules vides en valeurs manquantes")
            with header_col:
                st.markdown("**Lignes et en-têtes**")
                remove_duplicates = st.checkbox("Supprimer les lignes en doublon")
                clean_headers = st.checkbox("Normaliser les noms de colonnes")
                lowercase_headers = st.checkbox("Mettre les noms de colonnes en minuscules")

            apply_cleaning = st.form_submit_button(
                "Appliquer le nettoyage",
                type="primary",
                icon=":material/check:",
            )

        if apply_cleaning:
            if is_large_csv:
                try:
                    dataset.apply_cleaning(
                        strategy=strategy,
                        custom_value=custom_value,
                        strip_spaces=strip_spaces,
                        lowercase=lowercase,
                        clean_headers=clean_headers,
                        remove_accents=remove_accents_option,
                        empty_to_na=empty_to_na,
                        remove_duplicates=remove_duplicates,
                        lowercase_headers=lowercase_headers,
                        numeric_columns=dataset.numeric_columns,
                        make_unique_column_names=make_unique_column_names,
                        normalize_text=normalize_text,
                    )
                except sqlite3.Error as exc:
                    st.error(f"Le nettoyage du CSV volumineux a échoué : {exc}")
                    return
                st.session_state.pop("large_csv_quality", None)
                export_path = st.session_state.pop("large_csv_export_path", None)
                if export_path:
                    Path(export_path).unlink(missing_ok=True)
                cleaned_df = dataset.preview()
                for column in cleaned_df.columns:
                    numeric = pd.to_numeric(cleaned_df[column], errors="coerce")
                    if (
                        cleaned_df[column].notna().any()
                        and numeric[cleaned_df[column].notna()].notna().all()
                    ):
                        cleaned_df[column] = numeric
            else:
                cleaned = apply_missing_value_strategy(df, strategy, custom_value)
                cleaned = apply_text_cleaning(
                    cleaned,
                    strip_spaces,
                    lowercase,
                    clean_headers,
                    remove_accents=remove_accents_option,
                    empty_to_na=empty_to_na,
                    remove_duplicates=remove_duplicates,
                    lowercase_headers=lowercase_headers,
                )
                st.session_state.cleaned_df = cleaned
                cleaned_df = cleaned
            st.toast("Nettoyage appliqué", icon=":material/check_circle:")

        st.subheader("Aperçu après nettoyage", icon=":material/preview:")
        st.dataframe(cleaned_df.head(100), width="stretch", height=320, hide_index=True)

    elif current_view == "Exporter":
        st.subheader("Exporter les données", icon=":material/download:")
        with st.container(border=True):
            st.markdown("**Fichier CSV**")
            export_row_count = (
                dataset.row_count_for()
                if is_large_csv
                else len(cleaned_df)
            )
            st.caption(
                f"{export_row_count:,} lignes · {cleaned_df.shape[1]} colonnes".replace(",", " ")
            )
            if is_large_csv:
                export_key = (source_key, dataset.active_table())
                export_path = st.session_state.get("large_csv_export_path")
                if (
                    export_path is None
                    or st.session_state.get("large_csv_export_key") != export_key
                ):
                    if export_path:
                        Path(export_path).unlink(missing_ok=True)
                    fd, export_path = tempfile.mkstemp(
                        prefix="studio-export-",
                        suffix=".csv",
                    )
                    os.close(fd)
                    try:
                        with st.spinner("Préparation du CSV à télécharger..."):
                            dataset.export_csv(export_path)
                    except (sqlite3.Error, OSError) as exc:
                        Path(export_path).unlink(missing_ok=True)
                        st.session_state.pop("large_csv_export_path", None)
                        st.error(f"La préparation de l’export a échoué : {exc}")
                        return
                    st.session_state.large_csv_export_path = export_path
                    st.session_state.large_csv_export_key = export_key
                csv_data = lambda path=export_path: open(path, "rb")
            else:
                csv_data = cleaned_df.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="Télécharger le CSV nettoyé",
                data=csv_data,
                file_name="dataset_clean.csv",
                mime="text/csv",
                type="primary",
                icon=":material/download:",
            )

        if cleaned_df.shape[1] == 0:
            st.warning("Le fichier ne contient aucune colonne à exporter en SQL.")
        else:
            st.markdown("**Script SQL**")
            default_table_name = sanitize_column_name(
                uploaded_file.name.rsplit(".", 1)[0]
            ).lower()
            table_name_sql = st.text_input("Nom de la table", value=default_table_name)
            create_table_sql = build_create_table_sql(cleaned_df, table_name_sql)
            st.code(create_table_sql, language="sql", wrap_lines=True)
            st.download_button(
                label="Télécharger le script SQL",
                data=create_table_sql,
                file_name=f"{sanitize_column_name(table_name_sql).lower()}.sql",
                mime="text/sql",
                icon=":material/download:",
            )


if __name__ == "__main__":
    main()
