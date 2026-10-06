# Studio de données

Application locale en français pour consulter, nettoyer et exporter des fichiers CSV et Excel avec Streamlit.

> Le projet n'est pas encore publié sur GitHub. Aucune licence n'a été choisie : ajoutez une licence avant de distribuer le logiciel ou d'accepter des contributions externes.

## Fonctionnalités

- Import de fichiers CSV, XLSX et XLS.
- Aperçu tabulaire et indicateurs de lignes, colonnes, doublons et valeurs manquantes.
- Vérification de la qualité par colonne.
- Nettoyage du texte, des en-têtes, des valeurs manquantes et des doublons.
- Export du résultat en CSV ou génération d'un schéma SQL.
- Inspection, nettoyage et export des jeux de données.

Les graphiques ont été retirés afin de privilégier les fonctions d'inspection, de nettoyage et d'export.

## Prérequis

- Python 3.10 ou plus récent.
- `pip`.
- Assez de mémoire vive pour charger le fichier complet.

## Installation et lancement

Depuis la racine du projet, dans PowerShell :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

Sous macOS ou Linux :

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

L'application s'ouvre dans le navigateur. Importez un fichier, puis utilisez les espaces **Explorer**, **Nettoyer** et **Exporter**.

## Fichiers volumineux et limites

- Les fichiers CSV, XLSX et XLS sont chargés en mémoire avec pandas.
- Les gros fichiers consomment davantage de mémoire; réduisez leur taille avant de les importer si la mémoire disponible est limitée.
- Streamlit limite la taille d'envoi à 200 Mio par défaut. Cette limite peut être configurée avec `server.maxUploadSize`.
- Le schéma SQL généré repose sur des estimations de types. Vérifiez-le avant de l'exécuter.

## Tests

```powershell
python -m unittest discover -v
```

## Structure du projet

```text
app.py             Interface Streamlit et flux utilisateur
upload_utils.py    Identification des fichiers importés
test_app.py        Tests des fonctions de nettoyage et du schéma SQL
test_data_store.py Tests de l'identification des fichiers importés
```

## Données et confidentialité

Les fichiers sont traités par l'application; ne téléversez pas de données sensibles dans une instance que vous ne contrôlez pas. Lors d'un hébergement, l'exploitant du serveur peut accéder aux fichiers traités et aux données temporaires sur cette machine.

## Contribuer

Consultez [CONTRIBUTING.md](CONTRIBUTING.md) pour préparer l'environnement et exécuter les tests.