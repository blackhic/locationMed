# AUTOBAHN — Contrat de location

Web app Flask (mobile-first) qui permet à un employé de se connecter, remplir un
formulaire, et télécharger un **contrat de location PDF** : le texte est superposé sur
le modèle `templates/modele_vierge.pdf` aux coordonnées validées de `positions.json`.

## Fonctionnement

- **`/`** — page de connexion (login / mot de passe via variables d'env).
- **`/contrat`** — formulaire en 3 sections (Identité / Documents / Véhicule + Location),
  champs obligatoires marqués `*`, validation JS bloquante, auto-calcul du nombre de
  jours (date retour − date départ) et du montant (prix/jour × jours).
- **`POST /api/generate`** — génère le PDF (overlay `reportlab` + fusion `pypdf`) et le
  renvoie en téléchargement, nommé `contrat_autobahn_<NOM>.pdf`. La page 2 (conditions
  générales) du modèle est conservée.

## Structure

```
├── app.py                     # application Flask
├── positions.json             # coordonnées des champs (px @ 150 DPI)
├── templates/
│   └── modele_vierge.pdf      # fond du contrat (ne pas modifier)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml         # service + labels Traefik
├── .env.example               # modèle de variables (sans secrets)
└── demo_TOUS_CHAMPS.pdf       # rendu de référence
```

## Variables d'environnement

| Variable       | Rôle                                   | Défaut (dev)      |
|----------------|----------------------------------------|-------------------|
| `USERNAME`     | identifiant de connexion               | `autobahn`        |
| `PASSWORD`     | mot de passe de connexion              | `autobahn2024`    |
| `FLASK_SECRET` | clé secrète des sessions (obligatoire) | valeur de dev     |

⚠️ Ne **jamais** committer de vraies valeurs. En production, elles vivent dans un
fichier `.env` **non versionné** (voir `.env.example`).

## Lancement local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
# http://localhost:5000  (identifiants par défaut : autobahn / autobahn2024)
```

## Déploiement (VPS + Docker + Traefik)

L'app tourne en conteneur, exposée en HTTPS sur `autobahn.myzone-deals.com` via un
Traefik déjà présent sur le serveur (réseau Docker externe `root_default`).

```bash
# Sur le VPS
git clone https://github.com/blackhic/locationMed.git /opt/autobahn
cd /opt/autobahn

# Créer le .env avec les vraies valeurs (non versionné)
cat > .env <<EOF
USERNAME=...
PASSWORD=...
FLASK_SECRET=$(openssl rand -hex 32)
EOF

# Build + run
docker compose up -d --build
```

Le certificat HTTPS est obtenu automatiquement par Traefik (Let's Encrypt,
challenge TLS-ALPN-01). L'enregistrement DNS `autobahn.myzone-deals.com` doit pointer
vers l'IP du VPS en **DNS only** (le proxy Cloudflare doit rester désactivé, sinon la
validation du certificat et le HTTPS de Traefik échouent).
