# Déploiement sur un VM Hetzner (sous-domaine + certificat SSL automatique)

Ce document décrit la procédure pour déployer l'état actuel du dépôt
(`claude/erp-v1-bm0gzx`) sur un serveur VM Hetzner Cloud, accessible via un
sous-domaine du type `app.widehalo.cloud`, avec un certificat SSL/TLS obtenu
et renouvelé automatiquement (Let's Encrypt, via Caddy).

Pile utilisée pour ce déploiement : Docker Compose (`docker-compose.prod.yml`,
nouveau fichier à côté du `docker-compose.yml` de développement), PostgreSQL
et Redis en conteneurs, l'application servie par `daphne` (serveur ASGI —
nécessaire pour la messagerie temps réel WebSocket de `apps/chat`, pas
seulement du HTTP classique), et **Caddy** comme reverse proxy/terminaison
TLS : Caddy demande lui-même le certificat Let's Encrypt pour le sous-domaine
configuré et le renouvelle automatiquement, sans étape manuelle (pas de
`certbot` séparé à opérer).

## 1. Prérequis

- Un compte Hetzner Cloud.
- Un nom de domaine dont vous contrôlez la zone DNS (ex. `widehalo.cloud`) —
  peu importe le registrar, seule la capacité à ajouter un enregistrement DNS
  compte.
- Une clé SSH locale (`ssh-keygen -t ed25519` si vous n'en avez pas déjà une).

## 2. Notion de sous-domaine, d'IP du VM et de certificat SSL

Trois éléments distincts, à ne pas confondre :

- **L'IP du VM** : adresse IPv4 (et/ou IPv6) publique attribuée par Hetzner à
  la création du serveur (ex. `203.0.113.42`). Elle est fixe pour la durée de
  vie du VM (sauf recréation), visible dans la console Hetzner Cloud.
- **Le sous-domaine** (ex. `app.widehalo.cloud`) : un nom choisi sous un
  domaine que vous possédez déjà, qui **pointe vers** l'IP du VM via un
  enregistrement DNS de type **A** (et **AAAA** si vous utilisez IPv6). C'est
  ce nom, jamais l'IP nue, que les utilisateurs tapent dans leur navigateur et
  que le certificat SSL protège.
- **Le certificat SSL/TLS** : délivré par Let's Encrypt pour le **nom de
  domaine**, pas pour l'IP (Let's Encrypt ne signe pas de certificat pour une
  adresse IP nue). Caddy (service `caddy` de `docker-compose.prod.yml`) le
  demande automatiquement au premier démarrage via le défi HTTP-01 (port 80),
  ce qui suppose que le DNS soit déjà propagé et que le port 80 soit
  accessible depuis Internet — voir étape 5.

Le sous-domaine est entièrement configurable via `.env` (variable
`WIDEHALO_DOMAIN`, cf. étape 4) — changer de sous-domaine plus tard ne
nécessite qu'une modification de `.env` + un redémarrage des conteneurs,
Caddy redemande alors un certificat pour le nouveau nom.

## 3. Provisionner le VM

Dans la console Hetzner Cloud (ou `hcloud` CLI si vous préférez) :

1. Créer un serveur — type recommandé pour démarrer : **CX22** (2 vCPU, 4 Go
   RAM, cohérent avec le budget infra ≤ 60 €/mois du projet). Ajuster à la
   hausse si la charge réelle le justifie une fois en production.
2. Image : **Ubuntu 24.04 LTS**.
3. Ajouter votre clé SSH publique à la création (évite le mot de passe root
   par e-mail).
4. Noter l'IP publique attribuée (IPv4, et IPv6 si activée).
5. Firewall Hetzner (recommandé, en plus d'un pare-feu système côté VM,
   cf. étape suivante) : n'autoriser en entrée que les ports 22 (SSH), 80
   (HTTP, requis pour le défi Let's Encrypt) et 443 (HTTPS).

## 4. Préparer le VM

Connexion initiale et durcissement minimal :

```bash
ssh root@<IP_DU_VM>

# Pare-feu système (ufw) : redondant avec le firewall Hetzner ci-dessus,
# mais defense-in-depth peu coûteuse.
apt-get update && apt-get install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Retrait defensif de tout paquet Docker/Compose preexistant sur l'image de
# base (docker.io/docker-compose du depot Ubuntu, versions partielles sans
# le plugin Compose V2) - evite un conflit d'installation avec le script
# officiel ci-dessous. Idempotent : sans effet si aucun n'est present.
apt-get remove -y docker.io docker-doc docker-compose podman-docker \
  containerd runc 2>/dev/null || true

# Docker Engine + plugin Compose (dépôt officiel Docker, pas le paquet
# Ubuntu obsolète)
curl -fsSL https://get.docker.com | sh

# Verification explicite - ne jamais supposer que l'installation a reussi
# silencieusement.
docker --version
docker compose version   # doit afficher une version (plugin V2), pas une
                          # erreur "'compose' is not a docker command"
systemctl enable --now docker   # le script get.docker.com le fait deja au
                                 # premier install, explicite ici pour ne
                                 # pas en dependre implicitement
```

## 5. Pointer le sous-domaine sur l'IP du VM

Chez votre registrar/gestionnaire DNS, ajouter (exemple pour
`app.widehalo.cloud`, zone `widehalo.cloud`) :

| Type | Nom | Valeur              | TTL          |
|------|-----|----------------------|--------------|
| A    | app | `<IP_DU_VM>`         | 300 (5 min)  |
| AAAA | app | `<IPv6_DU_VM>` (si activée) | 300   |

Vérifier la propagation avant de continuer (peut prendre de quelques minutes
à quelques heures selon le registrar) :

```bash
dig +short app.widehalo.cloud
# doit renvoyer l'IP du VM
```

**Ne pas démarrer Caddy avant que ce test renvoie la bonne IP** — sinon la
demande de certificat Let's Encrypt échoue (Caddy réessaiera automatiquement
par la suite, mais autant éviter l'attente et le risque de rate-limit
Let's Encrypt en cas d'essais répétés).

## 6. Cloner le dépôt et configurer `.env`

```bash
cd /opt
git clone <URL_DU_DEPOT> widehalo
cd widehalo
git checkout claude/erp-v1-bm0gzx   # ou la branche/tag à déployer

cp .env.example .env
```

Éditer `.env` (`nano .env` ou équivalent) — variables **à changer
impérativement** par rapport à `.env.example` pour un déploiement réel :

```bash
DJANGO_SETTINGS_MODULE=config.settings.prod
DJANGO_DEBUG=false

# Genere une cle secrete forte (jamais la valeur de .env.example) :
#   python3 -c "import secrets; print(secrets.token_urlsafe(50))"
DJANGO_SECRET_KEY=<valeur generee>

# Le nom seul, sans schema — c'est le Host: HTTP envoye par le navigateur.
DJANGO_ALLOWED_HOSTS=app.widehalo.cloud

# Avec schema explicite (cf. section 2) — doit correspondre exactement au
# sous-domaine servi en HTTPS.
DJANGO_CSRF_TRUSTED_ORIGINS=https://app.widehalo.cloud

# Sous-domaine reel — pilote a la fois Caddy (certificat) et sert de
# reference dans ce document. Doit correspondre a DJANGO_ALLOWED_HOSTS/
# DJANGO_CSRF_TRUSTED_ORIGINS ci-dessus (memes 3 valeurs, coherentes).
WIDEHALO_DOMAIN=app.widehalo.cloud

# E-mail reel — Let's Encrypt l'utilise uniquement pour notifier une
# expiration de certificat imminente en cas d'echec de renouvellement.
ACME_EMAIL=vous@exemple.com

# Mot de passe du role applicatif Postgres (widehalo_app) — fort, distinct
# de la valeur de dev par defaut.
POSTGRES_PASSWORD=<mot de passe fort genere>

# Mot de passe du role BOOTSTRAP du cluster Postgres (distinct du role
# applicatif ci-dessus — cf. docker/init-db/001-init-app-role.sh pour le
# detail : Postgres ne permet structurellement jamais de retirer le
# privilege superuser a ce role, donc l'application ne doit jamais s'y
# connecter). Fort, different de POSTGRES_PASSWORD.
POSTGRES_SUPERUSER_PASSWORD=<mot de passe fort genere, different du precedent>
```

Les autres variables (`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_SUPERUSER`,
`REDIS_URL`, `CLAMAV_ENABLED`, `WHATSAPP_*`) peuvent rester à leurs valeurs
par défaut de `.env.example`, à ajuster selon vos besoins réels (WhatsApp
notamment, nécessite des identifiants Meta Cloud API — cf. `README.md`/le
plan du projet).

## 7. Démarrer le déploiement

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Ce que ce lancement fait, dans l'ordre :

1. `db`/`redis` démarrent et passent en santé (healthcheck).
2. `docker/init-db/001-init-app-role.sh` (monté automatiquement dans
   `/docker-entrypoint-initdb.d`) crée le rôle applicatif Postgres
   (`widehalo_app`, `NOSUPERUSER NOBYPASSRLS`) — **étape de sécurité
   critique** pour que l'isolation multi-tenant par Row-Level Security soit
   réellement effective. Ce rôle est délibérément **distinct** du rôle
   bootstrap du cluster (`POSTGRES_SUPERUSER`, cf. section 6) : PostgreSQL
   refuse structurellement de jamais retirer le privilège superuser au rôle
   bootstrap lui-même (aucune commande ne peut l'y contraindre), c'est
   pourquoi Django ne doit jamais se connecter avec ce rôle bootstrap — voir
   les commentaires du script pour le détail complet.
3. `web`/`worker` démarrent : `docker/entrypoint.sh` compile les traductions
   et applique les migrations Django automatiquement à chaque démarrage,
   avant que `web` ne lance `collectstatic` puis `daphne`.
4. `caddy` démarre, lit `WIDEHALO_DOMAIN`/`ACME_EMAIL` depuis `.env`, et
   demande automatiquement un certificat Let's Encrypt pour ce nom via le
   défi HTTP-01 (port 80) — la première demande prend généralement quelques
   secondes à quelques dizaines de secondes.

Suivre les logs de Caddy pour confirmer l'émission du certificat :

```bash
docker compose -f docker-compose.prod.yml logs -f caddy
# chercher une ligne du type "certificate obtained successfully"
```

Vérifier ensuite dans un navigateur que `https://app.widehalo.cloud`
répond avec un certificat valide (cadenas vert), et que
`https://app.widehalo.cloud/api/v1/docs` affiche la documentation OpenAPI.

## 8. Premier accès — compte admin par défaut et paramétrage de la société

Au tout premier démarrage (instance sans aucun utilisateur), le service
`web` crée automatiquement un compte administrateur par défaut avant de
lancer le serveur (`python manage.py bootstrap_admin`, idempotent — ne fait
plus rien dès qu'un utilisateur existe déjà) :

- **Identifiant** : `admin@admin.local`
- **Mot de passe** : `admin`

Se connecter sur `https://app.widehalo.cloud/login/` avec ces identifiants.
Deux écrans s'affichent alors automatiquement, dans cet ordre, avant tout
accès au reste de l'application :

1. **Changement de mot de passe obligatoire** — le mot de passe `admin`
   étant un mot de passe courant, il est de toute façon refusé comme
   nouveau mot de passe (`CommonPasswordValidator`) : en choisir un fort
   (12 caractères minimum).
2. **Paramétrage de la première société de l'instance** — code, raison
   sociale, NIF (optionnel), pays. Ce formulaire ne s'affiche que tant
   qu'aucune société n'existe encore sur l'instance ; une fois validé, la
   société est créée avec les paramètres par défaut du pays choisi
   (devise, TVA, fuseau horaire — `apps.core.services.smart_defaults`) et
   le compte admin y est immédiatement rattaché.

Ensuite, selon le rôle du compte (`admin` fait partie des rôles à MFA
obligatoire), un enrôlement TOTP est demandé avant l'accès au tableau de
bord — comportement standard du socle (étape 4), pas spécifique à ce compte
par défaut.

**Jeux de données de démonstration** (optionnel, pour tester plus vite que
manuellement) — une fois la société créée ci-dessus, les commandes
`seed_<module>` existantes restent utilisables pour peupler des données
d'exemple **dans un tenant `DEMO` séparé** (elles créent leur propre tenant
plutôt que de réutiliser celui paramétré ci-dessus) :

```bash
docker compose -f docker-compose.prod.yml exec web \
  python manage.py seed_core --tenant-code DEMO
docker compose -f docker-compose.prod.yml exec web \
  python manage.py seed_accounting --tenant-code DEMO
# ... de même pour seed_partners / seed_catalog / seed_chat / seed_crm /
# seed_mrp / seed_patronage selon les modules que vous voulez tester.
```

`sales`/`purchase`/`stocks` n'ont pas (encore) de commande `seed_*` dédiée à
la date de rédaction de ce document — les tester en l'état nécessite de
créer les données via l'API/les écrans HTMX ou l'admin Django une fois
connecté avec un utilisateur créé par `seed_core`.

Consulter la sortie de chaque commande `seed_*` pour les identifiants de
connexion créés (utilisateur/mot de passe de démonstration).

## 9. Mettre à jour le déploiement

```bash
cd /opt/widehalo
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Les migrations et la compilation des traductions sont réappliquées
automatiquement au redémarrage de `web`/`worker` (`docker/entrypoint.sh`) ;
aucune étape manuelle supplémentaire n'est nécessaire pour une mise à jour de
code standard.

## 10. Sauvegarde

La base Postgres est persistée dans le volume nommé `db_data` (survit à un
`docker compose down` sans `-v`). Un mécanisme d'export/import applicatif par
tenant existe déjà dans ce dépôt (`apps.core.services.tenant_export`,
`export_tenant_archive()`/`import_tenant_archive()`) mais n'est exposé
aujourd'hui que comme fonction de service, pas encore comme commande
`manage.py` dédiée — invocable en attendant via `manage.py shell` :

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py shell -c "
from apps.core.models.tenant import Tenant
from apps.core.services.tenant_export import export_tenant_archive
tenant = Tenant.objects.get(code='DEMO')
open('/app/backup.zip', 'wb').write(export_tenant_archive(tenant))
"
docker compose -f docker-compose.prod.yml cp web:/app/backup.zip ./backup.zip
```

**Note** : l'audit/durcissement de bout en bout de ce mécanisme (format
d'archive rétro-compatible entre versions, restauration testée, et l'ajout
d'une vraie commande `manage.py export_tenant`/`import_tenant`) est un
chantier séparé déjà identifié dans le plan du projet, pas encore clôturé à
la date de rédaction de ce document — à traiter avant de se reposer
exclusivement sur ce mécanisme pour un plan de sauvegarde de production.
En attendant, une sauvegarde régulière du volume `db_data` (`pg_dump`
planifié, copié hors du VM) reste la garantie la plus simple et la plus
éprouvée.

## 11. Dépannage rapide

- **`unknown flag: -f` (ou similaire) en lançant `docker compose -f ...`** :
  le plugin Compose V2 n'est pas installé (`docker compose`, avec un
  espace, est un plugin CLI — pas la commande historique `docker-compose`
  avec un tiret). Vérifier avec `docker compose version` ; si elle échoue,
  retirer les paquets conflictuels (`apt-get remove -y docker.io
  docker-compose containerd runc`) puis réinstaller via
  `curl -fsSL https://get.docker.com | sh` (cf. section 4) — ne jamais
  mélanger le paquet `docker.io` du dépôt Ubuntu avec le dépôt officiel
  Docker sur le même VM.
- **Le certificat n'est jamais émis** (`caddy` boucle en erreur dans ses
  logs) : vérifier que `dig +short <sous-domaine>` renvoie bien l'IP du VM
  (étape 5), et que le port 80 est ouvert depuis Internet (pas seulement en
  local) — `curl -I http://<sous-domaine>` depuis une machine externe doit
  répondre, pas timeout.
- **`authz_status: valid` puis `HTTP 403 unauthorized - authorizations for
  these identifiers not valid` à la finalisation de la commande** (le défi
  HTTP-01 réussit, mais l'émission échoue juste après) : Let's Encrypt/
  ZeroSSL revérifient certaines conditions (dont le CAA) juste avant
  l'émission, pas seulement à l'autorisation — un échec à ce stade précis
  n'est donc pas forcément lié au port 80/DNS (déjà validés à ce moment-là).
  Causes les plus fréquentes, à vérifier dans cet ordre :
  1. **Tentatives concurrentes/répétées sur le même nom** : plusieurs
     `docker compose up`/redémarrages de `caddy` rapprochés créent des
     commandes ACME concurrentes pour le même domaine, qui peuvent
     s'invalider mutuellement — arrêter de relancer en boucle (chaque échec
     compte dans la limite Let's Encrypt de 5 validations échouées par
     compte/nom d'hôte/heure, cf. entrée 429 ci-dessous), attendre
     quelques minutes, puis un seul essai propre :
     `docker compose -f docker-compose.prod.yml down && docker compose
     -f docker-compose.prod.yml up -d`.
  2. **Enregistrement CAA bloquant** : `dig CAA <sous-domaine> +short` et
     `dig CAA <domaine racine> +short` — l'absence de résultat est normale
     (aucune restriction) ; un enregistrement présent qui ne liste pas
     `letsencrypt.org` (et `sectigo.com`/`ssl.com` pour ZeroSSL) bloque
     l'émission malgré un défi HTTP-01 réussi.
  3. Si l'échec bascule ensuite sur ZeroSSL et que celui-ci échoue en
     timeout (`context deadline exceeded`) plutôt qu'en erreur applicative :
     problème réseau sortant du VM vers `acme.zerossl.com`, pas un problème
     de configuration — vérifier avec `curl -v
     https://acme.zerossl.com/v2/DV90/directory` depuis le VM.
- **`CSRF verification failed` sur un formulaire** : `DJANGO_CSRF_TRUSTED_ORIGINS`
  dans `.env` ne correspond pas exactement au sous-domaine servi (schéma
  `https://` obligatoire, cf. section 6) — vérifier puis redémarrer `web`.
- **Redirection HTTPS en boucle infinie** : signe que `SECURE_PROXY_SSL_HEADER`
  n'est pas pris en compte — s'assurer que Caddy est bien le seul point
  d'entrée HTTP (jamais d'accès direct au port 8000 de `web` depuis
  l'extérieur du VM, ce port n'est d'ailleurs pas publié dans
  `docker-compose.prod.yml`).
- **429 Too Many Requests de Let's Encrypt** : limite de taux atteinte après
  plusieurs tentatives rapprochées sur le même nom — attendre (la fenêtre de
  Let's Encrypt est glissante sur 1 semaine) plutôt que de relancer en boucle;
  utiliser leur [environnement de staging](https://letsencrypt.org/docs/staging-environment/)
  pour tester la configuration Caddy sans consommer le quota réel si besoin
  de multiples essais.
