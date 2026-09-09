"""T5 — la liaison devient lisible par le point d'entree de webhook, en
lecture seule et sur demande explicite.

**Le defaut ferme, et il rendait tout webhook entrant inutilisable en
production.** Un operateur qui appelle `/api/v1/flows/webhooks/{link_id}`
n'a ni session, ni jeton applicatif, ni en-tete de societe — lui en faire
envoyer un reviendrait a laisser l'appelant choisir la societe dans
laquelle il ecrit. Aucun `app.tenant_id` n'est donc pose, la policy
`tenant_isolation_policy` ne laisse passer aucune ligne, et la lecture de
la liaison rendait 404 sur CHAQUE appel authentique. `all_objects` n'y
change rien : il contourne la RLS applicative de `TenantManager`, jamais
celle de PostgreSQL — `apps.core.management.commands.apply_rls` l'ecrit
deja noir sur blanc.

**Pourquoi pas la derogation `RLS_FORCE_FOR_OWNER = False`.** C'est la
reponse que `PrjGuestAccess` a recue pour le meme probleme de poule et
d'oeuf, et elle a ete ecrite ici avant d'etre retiree. Elle passe
`flw_link` en `NO FORCE`, donc lisible ET ECRIVABLE hors societe par le
proprietaire de la table — et le test FLX-7 `test_writing_into_the_other
_company_is_refused_by_postgresql` est tombe, a juste titre : le critere
demande que l'isolation soit refusee PAR POSTGRESQL, pas seulement par
l'application. Un critere ne se troque pas contre une commodite, et la
mesure l'a dit avant qu'on ait a en debattre.

**Ce que cette migration pose a la place.** Une SECONDE policy, permissive,
sur la meme table :

- `FOR SELECT` uniquement — les ecritures restent gouvernees par la seule
  `tenant_isolation_policy`, donc une ecriture hors societe reste refusee
  par PostgreSQL, `FORCE` compris ;
- conditionnee a `app.webhook_lookup`, un reglage de session que seul
  `apps/flows/services/inbound_routing.py` sait poser, avec un `SET LOCAL`
  qui meurt avec la transaction ;
- et elle n'ouvre rien tant que ce reglage n'est pas pose : `current_setting
  ('app.webhook_lookup', true)` rend NULL par defaut, et la condition est
  fausse.

L'ouverture fait donc exactement la taille du besoin : retrouver une ligne
par son identifiant pour savoir quelle societe activer, puis refermer.
"""

from __future__ import annotations

from django.db import migrations

POLICY_NAME = "webhook_lookup_policy"
TABLE = "flw_link"


def create_lookup_policy(apps, schema_editor) -> None:
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON \"{TABLE}\"")
    schema_editor.execute(
        f'CREATE POLICY {POLICY_NAME} ON "{TABLE}" FOR SELECT '
        "USING (current_setting('app.webhook_lookup', true) = 'on')"
    )


def drop_lookup_policy(apps, schema_editor) -> None:
    """Reversible, et le retour arriere se lit comme ce qu'il est : sans
    cette policy, aucun appel de webhook entrant ne retrouve sa liaison."""
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"DROP POLICY IF EXISTS {POLICY_NAME} ON \"{TABLE}\"")


class Migration(migrations.Migration):
    dependencies = [
        ("flows", "0008_flwtrigger_document_type"),
    ]

    operations = [
        migrations.RunPython(create_lookup_policy, drop_lookup_policy),
    ]
