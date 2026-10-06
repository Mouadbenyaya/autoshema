# Contribuer

Merci de vouloir contribuer à Studio de données. Le projet est en préparation pour une publication; vérifiez les indications de licence et de contribution avec les mainteneurs avant de redistribuer du code.

## Préparer l'environnement

Utilisez Python 3.10 ou plus récent, puis installez les dépendances :

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Sous macOS ou Linux, remplacez l'activation par `source .venv/bin/activate`.

Lancez les tests depuis la racine :

```powershell
python -m unittest discover -v
```

Lancez l'application localement avec :

```powershell
streamlit run app.py
```

## Proposer un changement

1. Décrivez le problème ou le besoin et son résultat attendu.
2. Gardez le changement ciblé et suivez les conventions existantes.
3. Ajoutez ou mettez à jour les tests pour le comportement modifié.
4. Exécutez les tests et vérifiez l'application Streamlit si l'interface change.
5. Documentez les changements visibles pour les utilisateurs.
6. Dans une demande de contribution, indiquez le problème traité, la solution, les tests lancés et toute limite connue.

N'incluez pas de fichiers de données réels, de secrets, de résultats contenant des données personnelles, ni de fichiers temporaires dans une contribution.
