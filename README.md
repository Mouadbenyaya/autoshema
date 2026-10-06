# Studio de données

Application locale en français pour consulter, nettoyer et exporter des fichiers CSV et Excel avec Streamlit.

> Le projet n'est pas encore publié sur GitHub. Aucune licence n'a été choisie : ajoutez une licence avant de distribuer le logiciel ou d'accepter des contributions externes.

## Fonctionnalités

- Import de fichiers CSV, XLSX et XLS.
- Aperçu tabulaire et indicateurs de lignes, colonnes, doublons et valeurs manquantes.
- Vérification de la qualité par colonne.
- Nettoyage du texte, des en-têtes, des valeurs manquantes et des doublons.
- Export du résultat en CSV ou génération d'un schéma SQL.
- Traitement des CSV volumineux sur disque, sans charger l'ensemble du fichier en mémoire.
- Registre de transactions financières stocké dans une base SQLite locale.

Les graphiques ont été retirés afin de privilégier les fonctions d'inspection, de nettoyage et d'export.

## Prérequis

- Python 3.10 ou plus récent.
- `pip`.
- De l'espace disque temporaire pour les CSV volumineux.

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

L'application s'ouvre dans le navigateur. Importez un fichier, puis utilisez les espaces **Explorer**, **Nettoyer** et **Exporter**. Le registre **Transactions** est accessible sans importer de fichier.

## Registre des transactions

Ajoutez, consultez et supprimez des opérations avec leur date, description, montant et catégorie. Les montants positifs représentent des entrées et les négatifs des dépenses; le solde net est calculé à partir de centimes entiers.

Par défaut, les transactions sont conservées dans `data/transactions.sqlite3` à côté de l'application. Le dossier `data/` est ignoré par Git afin de ne pas publier les données personnelles. Pour stocker la base ailleurs, définissez la variable d'environnement `TRANSACTIONS_DB_PATH` avant de lancer Streamlit. Sauvegardez ce fichier SQLite si vous souhaitez conserver les données en cas de déplacement ou de réinstallation.

Si l'application est hébergée, la base appartient à la machine qui exécute le serveur et peut être partagée entre ses utilisateurs. Ne l'hébergez pas publiquement avec des données confidentielles sans ajouter une authentification et des contrôles d'accès adaptés.

## Fichiers volumineux et limites

- Les CSV d'au moins 32 Mio sont importés par blocs de 50 000 lignes dans une base SQLite temporaire.
- L'aperçu est limité aux 10 000 premières lignes; les indicateurs généraux sont calculés sur le fichier entier.
- Le rapport de qualité détaillé des gros fichiers est calculé à la demande.
- Le nettoyage et l'export CSV couvrent toutes les lignes, mais nécessitent de l'espace disque temporaire.
- XLSX et XLS sont chargés en mémoire avec pandas; le traitement sur disque ne concerne que les gros CSV.
- Streamlit limite la taille d'envoi à 200 Mio par défaut. Cette limite peut être configurée avec `server.maxUploadSize`.
- Le schéma SQL repose sur des estimations de types. Vérifiez-le avant de l'exécuter; pour un gros CSV, les types sont estimés à partir de l'aperçu.

Les bases et exports temporaires sont créés sur la machine qui exécute l'application puis supprimés lorsque le fichier importé est retiré ou remplacé. En cas d'arrêt brutal, un fichier temporaire peut subsister dans le dossier temporaire du système.

## Tests

```powershell
python -m unittest discover -v
```

## Structure du projet

```text
app.py             Interface Streamlit et flux utilisateur
data_store.py      Import par blocs, stockage SQLite et export des gros CSV
transaction_store.py Stockage SQLite des transactions financières
test_app.py        Tests des fonctions de nettoyage et du schéma SQL
test_data_store.py Tests du stockage et des traitements CSV volumineux
test_transaction_store.py Tests du registre SQLite des transactions
```

## Données et confidentialité

Les fichiers sont traités par l'application; ne téléversez pas de données sensibles dans une instance que vous ne contrôlez pas. Lors d'un hébergement, l'exploitant du serveur peut accéder aux fichiers traités et aux données temporaires sur cette machine.

## Contribuer

Consultez [CONTRIBUTING.md](CONTRIBUTING.md) pour préparer l'environnement et exécuter les tests.

## Sécurité

Consultez [SECURITY.md](SECURITY.md) pour signaler un problème de sécurité de manière responsable.
