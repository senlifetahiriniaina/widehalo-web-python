#!/bin/bash
set -euo pipefail

# Cree le role applicatif Django (widehalo_app par defaut) SEPAREMENT du role
# bootstrap du cluster (POSTGRES_USER/POSTGRES_PASSWORD passes a l'image
# postgres officielle) — ne JAMAIS reutiliser le meme role pour les deux.
#
# Bug reel rencontre et corrige (trouve en CI, invisible en local) : la
# premiere version de ce fichier tentait `ALTER ROLE widehalo_app WITH
# NOSUPERUSER ...` sur le role widehalo_app lui-meme, en partant du principe
# qu'on pouvait le "retrograder" apres coup. Ca fonctionnait en local
# uniquement parce que le role widehalo_app y avait ete cree A LA MAIN comme
# un role ordinaire, jamais le veritable role bootstrap. Mais l'image
# postgres officielle fait de POSTGRES_USER le role BOOTSTRAP du cluster
# (celui cree par initdb, OID 10) — et PostgreSQL REFUSE categoriquement de
# retirer SUPERUSER a ce role precis, quel que soit qui essaie ("ERROR:
# permission denied to alter role / DETAIL: The bootstrap user must have the
# SUPERUSER attribute"), meme en se connectant en tant que lui-meme. Il n'y a
# donc AUCUN moyen de retrograder POSTGRES_USER apres coup : ce role reste
# superuser pour toujours. La seule correction possible est de ne jamais
# faire jouer ce role a l'application — POSTGRES_USER/POSTGRES_PASSWORD
# restent une identite bootstrap pure (jamais utilisee par Django), et ce
# script CREE un role applicatif totalement distinct et ordinaire (non
# superuser des sa creation, jamais retrograde), auquel Django se connecte
# via des identifiants separes.
#
# Invoque de deux facons, avec le meme effet :
#  - docker-compose.yml/docker-compose.prod.yml montent docker/init-db/ dans
#    /docker-entrypoint-initdb.d, execute automatiquement par l'image
#    postgres a la toute premiere initialisation du cluster — $POSTGRES_USER/
#    $POSTGRES_DB y sont deja l'identite bootstrap (fixee par l'image),
#    $APP_DB_USER/$APP_DB_PASSWORD sont fournis par le bloc `environment:` du
#    service `db` (recopies depuis les identifiants applicatifs reels de .env).
#  - .github/workflows/ci.yml l'execute directement via bash apres le
#    checkout (les conteneurs de service GitHub Actions demarrent AVANT le
#    checkout, ils ne peuvent donc pas monter ce fichier automatiquement) —
#    avec les memes variables exportees explicitement par cette etape.

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    DO \$do\$
    BEGIN
        IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${APP_DB_USER}') THEN
            CREATE ROLE "${APP_DB_USER}" WITH LOGIN PASSWORD '${APP_DB_PASSWORD}'
                NOSUPERUSER NOBYPASSRLS NOCREATEROLE CREATEDB;
        END IF;
    END
    \$do\$;
    GRANT ALL PRIVILEGES ON DATABASE "${POSTGRES_DB}" TO "${APP_DB_USER}";
    GRANT ALL ON SCHEMA public TO "${APP_DB_USER}";
EOSQL

# Les protections suivantes restent appliquees automatiquement par les
# migrations Django (pas par ce script), car elles doivent survivre a une
# reinitialisation de la base :
#   - RLS FORCE sur toutes les tables heritant BaseModel, reappliquee a chaque
#     migrate (apps/core/management/commands/apply_rls.py, signal
#     post_migrate) — reellement efficace tant que le role applicatif (celui
#     cree ci-dessus) reste proprietaire des tables qu'il cree ET n'est
#     jamais superuser, ce que ce script garantit des la creation du role.
#   - Immuabilite de core_audit_log via un TRIGGER Postgres (pas un simple
#     REVOKE de privileges, inefficace contre le proprietaire de la table) :
#     voir la migration core.0010_audit_log_immutable — le trigger rejette
#     tout UPDATE/DELETE, y compris pour le role proprietaire.
