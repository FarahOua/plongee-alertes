# Alertes plongée : comparaison quotidienne des modèles de mer

Une appli web où un plongeur clique sur un point de la carte, choisit une période, et reçoit chaque
matin un mail qui compare vagues, vent, courant et température de l'eau selon plusieurs modèles
(Météo-France, ECMWF, NOAA, DWD), avec un indice d'accord entre modèles et un score de 0 à 100.

- **Backend** : Flask + Postgres hébergé sur Supabase (dossier `backend/`)
- **Frontend** : Streamlit + carte Folium (dossier `frontend/`)
- **Données** : Open-Meteo (gratuit pour un usage non commercial)
- **Texte du mail** : LLM gratuit (Google Gemini), sinon texte gabarit

## Démarrage rapide

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env             # puis renseigne au moins DATABASE_URL (voir « Base de données »)

# Terminal 1 : l'API
flask --app backend.app init-db   # une fois : crée les tables dans Supabase
flask --app backend.app run

# Terminal 2 : le site
streamlit run frontend/streamlit_app.py

# Terminal 3 : le planificateur (traite les alertes toutes les 15 min)
python -m backend.scheduler
```

Ouvre http://localhost:8501, connecte-toi avec ton mail, clique en mer, crée une alerte.

**Mode dev** (seule la base est obligatoire) : les mails (code de connexion compris) sont écrits dans `outbox/`
(fichiers `.html` lisibles dans un navigateur) et le texte vient du gabarit.

## Base de données (Supabase)

Toutes les données (comptes, alertes, rapports, journal d'envoi, cache des prévisions) sont dans Postgres.

1. Crée un projet sur supabase.com (région proche, par exemple Europe de l'Ouest).
2. Bouton **Connect** du projet → **Session pooler** → copie l'URI et mets-la dans `.env` :
   `DATABASE_URL=postgresql://postgres.xxxx:MOT_DE_PASSE@aws-0-eu-west-3.pooler.supabase.com:5432/postgres`
   (la connexion « directe » est en IPv6 uniquement : elle échoue sur beaucoup de réseaux domestiques ;
   si le mot de passe contient des caractères spéciaux comme `@`, `#` ou `!`, encode-les : `@` → `%40`,
   `#` → `%23`, `!` → `%21`.)
3. `flask --app backend.app init-db` crée les tables. Tu les vois ensuite dans Supabase → Table Editor.

La sécurité de ligne (RLS) est activée sur toutes les tables sans aucune règle : l'API REST de Supabase
et sa clé « anon » ne peuvent donc rien lire. Seul ton serveur Flask, qui se connecte avec le mot de passe
de la base, y accède. N'utilise jamais ce mot de passe côté navigateur.

## Mettre en vrai

| Quoi | Où | Variable du `.env` |
|---|---|---|
| Texte rédigé par IA | Clé gratuite sur aistudio.google.com | `GEMINI_API_KEY` |
| Envoi réel des mails | Clé API sur brevo.com (`xkeysib-…`) | `BREVO_API_KEY`, `MAIL_FROM` |
| Liens dans les mails | URL publiques de l'API et du site | `PUBLIC_BACKEND_URL`, `FRONTEND_URL` |

Pour la délivrabilité, envoie depuis un domaine à toi avec SPF, DKIM et DMARC configurés dans Brevo.

Les alertes se traitent avec `flask --app backend.app run-due`, à lancer toutes les 15 minutes : par
GitHub Actions en production (voir « Déploiement gratuit »), ou en local avec `python -m backend.scheduler`.
Pour tester l'envoi : `flask --app backend.app test-mail ton@mail.fr`.

## Comment c'est calculé

1. Chaque modèle est interrogé séparément sur Open-Meteo (`backend/openmeteo.py`). Un modèle qui ne
   renvoie que des valeurs vides à cet endroit est ignoré (c'est le cas d'un point à terre, ou d'un
   modèle qui ne couvre pas la zone). Les réponses sont mises en cache 3 h par maille de ~5 km.
2. Pour chaque heure entre 7h et 19h (heure locale du spot), on calcule la médiane, le minimum et le
   maximum des modèles (`backend/compare.py`).
3. **Accord** : élevé si l'écart de hauteur de vagues est < 0,3 m et l'écart de vent < 5 nœuds ;
   faible au-delà de 0,6 m ou 10 nœuds ; moyen entre les deux.
4. **Score** sur 100 : vagues (45 pts), vent (35 pts), courant (20 pts), plafonné à 80 si l'accord
   est moyen et à 60 s'il est faible. Le meilleur créneau de 3 h donne le score du jour.
5. **Texte** (`backend/writer.py`) : le LLM reçoit uniquement les chiffres calculés. Si son texte
   contient un nombre absent des données, il est rejeté et on utilise le gabarit.

Les seuils sont dans `backend/compare.py` et les modèles dans `backend/config.py` : ajuste-les avec
ton expérience du spot.

## Modèles utilisés

| Type | Modèles (identifiants Open-Meteo) |
|---|---|
| Vagues | `meteofrance_wave` (MFWAM), `ecmwf_wam`, `ncep_gfswave016` (GFS Wave), `ewam` (DWD) |
| Vent | `ecmwf_ifs025`, `meteofrance_seamless` (ARPEGE hors France), `icon_seamless`, `gfs_seamless` |
| Courant | `meteofrance_currents` (un seul modèle : indicatif) |
| Eau | température de surface, modèle par défaut |

Le courant est converti de km/h en nœuds.

## Visibilité sous l'eau (estimation)

Aucun modèle ne prévoit directement la visibilité d'un plongeur. L'appli l'**estime** (bonne / moyenne /
faible) à partir de Copernicus Marine (`backend/visibility.py`) :

- **Kd490 prévu** (atténuation de la lumière) par le modèle biogéochimique Méditerranée, ~4 km ;
  à défaut, le Kd490 observé par satellite ;
- seuils de départ : Kd490 < 0,07 → bonne (15 m et plus), < 0,15 → moyenne (8 à 15 m), sinon faible ;
- un niveau de moins si la houle médiane dépasse 1 m, et encore un si plus de 10 mm de pluie sont
  tombés sur les 48 h précédentes (apports des oueds) ;
- la profondeur de Secchi observée par satellite est affichée à titre indicatif.

Activation : crée un compte gratuit sur marine.copernicus.eu, puis renseigne `COPERNICUS_USERNAME` / `COPERNICUS_PASSWORD` dans `.env`. Sans cela, la ligne visibilité est
simplement absente. Ajuste les seuils en haut de `backend/visibility.py` avec tes propres observations.

## API

| Méthode | Route | Rôle |
|---|---|---|
| POST | `/auth/request-code` | Envoie un code à 6 chiffres par mail |
| POST | `/auth/verify` | Échange le code contre un jeton (`Authorization: Bearer …`) |
| GET | `/subscriptions` | Mes alertes (avec dernier score) |
| POST | `/subscriptions` | Crée une alerte : `name, lat, lon, start_date, end_date, send_time` |
| PATCH | `/subscriptions/<id>` | Modifie, met en pause (`status: paused`) ou reprend (`active`) |
| DELETE | `/subscriptions/<id>` | Supprime |
| POST | `/subscriptions/<id>/send-now` | Mail de test immédiat |
| GET | `/preview?lat=&lon=` | Comparaison des modèles sans alerte |
| GET | `/reports/<id>/<date>?t=` | Version web d'un mail |
| GET | `/unsubscribe/<token>` | Arrêt en un clic depuis le mail |

## Déploiement gratuit

Trois services gratuits, sans serveur à gérer, et plus aucun souci d'adresse IP de ton Mac :

| Rôle | Service | Coût |
|---|---|---|
| Base de données | Supabase | gratuit |
| API Flask | Render (offre gratuite) | gratuit, s'endort après 15 min sans visite |
| Site Streamlit | Streamlit Community Cloud | gratuit |
| Envoi des alertes (toutes les 15 min) | GitHub Actions | gratuit sur un dépôt public |

1. **GitHub** : pousse le projet sur un dépôt **public** (le `.env` n'est pas dans git, les clés restent secrètes).
2. **Secrets GitHub** : dépôt → Settings → Secrets and variables → Actions → New repository secret. Crée :
   `DATABASE_URL`, `BREVO_API_KEY`, `MAIL_FROM`, `GEMINI_API_KEY`, `COPERNICUS_USERNAME`,
   `COPERNICUS_PASSWORD`, `PUBLIC_BACKEND_URL`, `FRONTEND_URL` (les deux derniers : voir étapes 3 et 4).
   Le planificateur `.github/workflows/scheduler.yml` (copie-le depuis `deploy/scheduler-workflow.yml`) se lance alors tout seul toutes les 15 minutes.
3. **API sur Render** : render.com → New → Blueprint → choisis le dépôt (il lit `render.yaml`). Renseigne les
   variables demandées (mêmes valeurs que les secrets). Une fois en ligne, note l'adresse
   (`https://plongee-api.onrender.com`) : c'est `PUBLIC_BACKEND_URL`.
4. **Site sur Streamlit Community Cloud** : share.streamlit.io → New app → ton dépôt, fichier principal
   `frontend/streamlit_app.py`. Dans Advanced settings → Secrets : `BACKEND_URL = "https://plongee-api.onrender.com"`.
   L'adresse du site est `FRONTEND_URL` : mets-la dans Render et dans les secrets GitHub.
5. Une seule fois, depuis ton Mac : `flask --app backend.app init-db` (crée les tables dans Supabase).

À savoir :
- **Premier chargement lent** : l'API gratuite se rendort quand personne ne l'utilise ; le premier clic peut
  prendre 30 à 60 secondes. Le planificateur la réveille toutes les 15 minutes pour limiter ça.
- **Envois un peu décalés** : GitHub lance les tâches planifiées avec parfois 5 à 20 minutes de retard aux
  heures chargées. Un mail programmé à 06:30 peut arriver à 06:45.
- **Pause après 60 jours sans activité** du dépôt : GitHub désactive les tâches planifiées ; un clic sur
  « Enable workflow » (onglet Actions) les relance.
- **Mémoire de Render (512 Mo)** : si l'API plante à cause de `copernicusmarine`, dis-le-moi, on le retirera de
  l'API (la visibilité resterait dans les mails, envoyés par GitHub Actions).
- Les IP des services gratuits ne sont pas fixes : n'active pas de restriction par IP chez Brevo ni Supabase.

## Tests

```bash
TEST_DATABASE_URL=postgresql://... pytest -q      # ou la mettre dans .env
```

Les tests vident leur base à chaque lancement : utilise un **second projet Supabase** (ou une base locale),
jamais celle de production. Sans `TEST_DATABASE_URL`, ils sont ignorés.

Les tests simulent Open-Meteo (aucun appel réseau) et couvrent : la comparaison et le score, le rejet
d'un texte d'IA qui invente un chiffre, le parcours complet (connexion, création, pause, envoi unique
par jour, page du rapport, désabonnement, suppression) et les limites (nombre d'alertes, propriété).

## Dépannage

**Voir ce que chaque modèle renvoie pour un point** (sans cache) :

```bash
python -m backend.diagnose 35.69 -5.30
```

Pour chaque modèle : nombre d'heures avec des données, première et dernière heure, pas de temps,
maille réellement utilisée par Open-Meteo. Le cache se vide dans Supabase : `DELETE FROM forecast_cache;` (SQL Editor).

**`SSL: CERTIFICATE_VERIFY_FAILED … self-signed certificate in certificate chain`** : un antivirus
(Kaspersky, Avast, ESET…), un proxy d'entreprise ou un VPN inspecte le trafic HTTPS. Le backend
utilise les certificats du système grâce au paquet `truststore` (`pip install -r requirements-dev.txt`).
Si l'erreur persiste, exporte le certificat racine de ce logiciel en `.pem` et ajoute dans `.env` :
`REQUESTS_CA_BUNDLE=C:\chemin\vers\certificat.pem`. Ne désactive pas la vérification HTTPS.

## Limites connues

- Près des côtes et dans le détroit de Gibraltar, les modèles résolvent mal le relief : un accord
  faible y est souvent un signe d'effet local.
- Open-Meteo gratuit = usage non commercial. Si l'appli devient payante, il faut une clé commerciale
  (`OPEN_METEO_API_KEY`).
- Piste suivante : ajouter le modèle méditerranéen Copernicus Med-WAV (~4 km) via `copernicusmarine`.
