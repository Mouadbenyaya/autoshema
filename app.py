import re
import unicodedata

import pandas as pd
import streamlit as st
from upload_utils import upload_key


st.set_page_config(
    page_title="Studio de données",
    page_icon=":material/query_stats:",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
        st.caption("Explorer · nettoyer · exporter")
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
        ["Explorer", "Nettoyer", "Exporter"],
        default="Explorer",
        key="workspace_view",
        label_visibility="collapsed",
    )

    if uploaded_file is None:
        st.session_state.pop("upload_source", None)
        st.session_state.pop("uploaded_df", None)
        st.session_state.pop("cleaned_df", None)
        st.info("Importez un fichier pour explorer, nettoyer ou exporter vos données.")
        return

    source_key = upload_key(uploaded_file)
    try:
        if st.session_state.get("upload_source") != source_key:
            with st.spinner("Chargement du fichier..."):
                df = load_uploaded_data(uploaded_file)
            st.session_state.uploaded_df = df
            st.session_state.cleaned_df = df.copy()
            st.session_state.upload_source = source_key

        df = st.session_state.uploaded_df
        cleaned_df = st.session_state.cleaned_df
        duplicate_count = int(df.duplicated().sum())
        missing_count = int(df.isna().sum().sum())
    except (ValueError, pd.errors.ParserError, OSError) as exc:
        st.error(str(exc))
        return

    with st.container(horizontal=True):
        st.metric("Lignes", f"{len(df):,}".replace(",", " "), border=True)
        st.metric("Colonnes", df.shape[1], border=True)
        st.metric("Doublons", duplicate_count, border=True)
        st.metric("Valeurs manquantes", missing_count, border=True)

    if current_view == "Explorer":
        st.subheader("Aperçu des données", icon=":material/table_chart:")
        st.dataframe(df.head(100), width="stretch", height=320, hide_index=True)

        with st.expander("Qualité par colonne", icon=":material/fact_check:"):
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
            st.caption(
                f"{len(cleaned_df):,} lignes · {cleaned_df.shape[1]} colonnes".replace(",", " ")
            )
            st.download_button(
                label="Télécharger le CSV nettoyé",
                data=cleaned_df.to_csv(index=False).encode("utf-8-sig"),
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
