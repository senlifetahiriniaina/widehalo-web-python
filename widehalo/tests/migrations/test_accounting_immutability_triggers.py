"""Couche 7 (T4/MIG du CDC) : reversibilite des migrations `accounting`
qui posent des garanties Postgres (trigger d'immuabilite RG-ACC-2) via
`RunSQL` hors-modele — un `manage.py migrate accounting 0002` doit
restaurer exactement le comportement d'avant, condition necessaire pour
qu'un rollback de deploiement reste sûr.

Ces tests recreent tout le schema (via `django-test-migrations`) et sont
donc plus lents que la moyenne : marques `slow` (cf. TST-5, budget CI)."""

from __future__ import annotations

from datetime import date

import pytest
from apps.core.models.tenant import Tenant
from django.db import Error as DjangoDbError

pytestmark = pytest.mark.slow


def _make_move(apps_state, *, tenant: Tenant, state: str = "draft"):
    """Construit une AccMove posee sur son graphe minimal de FK, au
    shape du modele historique `apps_state` (jamais le modele courant
    importable — c'est tout l'interet de django-test-migrations).

    `tenant_id=` (et non `tenant=`) : le modele historique `Tenant` de
    `apps_state` est une classe distincte de `apps.core.models.tenant.Tenant`
    (meme table, classes Python differentes) — assigner l'instance
    "courante" leverait un `ValueError` d'incompatibilite de type sur le
    descripteur de la FK. Passer le seul UUID contourne cette verification
    et fonctionne puisque la table sous-jacente est identique."""
    fiscal_year_model = apps_state.get_model("accounting", "AccFiscalYear")
    period_model = apps_state.get_model("accounting", "AccPeriod")
    journal_model = apps_state.get_model("accounting", "AccJournal")
    move_model = apps_state.get_model("accounting", "AccMove")

    fiscal_year = fiscal_year_model.objects.create(
        tenant_id=tenant.id,
        code="FY26",
        date_start=date(2026, 1, 1),
        date_end=date(2026, 12, 31),
    )
    period = period_model.objects.create(
        tenant_id=tenant.id,
        fiscal_year=fiscal_year,
        code="2026-01",
        date_start=date(2026, 1, 1),
        date_end=date(2026, 1, 31),
    )
    journal = journal_model.objects.create(
        tenant_id=tenant.id,
        code="OD",
        name="Operations diverses",
        type="misc",
        sequence_prefix="OD",
    )
    return move_model.objects.create(
        tenant_id=tenant.id,
        journal=journal,
        period=period,
        date=date(2026, 1, 15),
        state=state,
    )


@pytest.mark.django_db
def test_move_immutability_trigger_applies_and_reverses(migrator) -> None:
    # `apply_initial_migration` recree tout le schema (drop + replay) :
    # toute donnee doit etre creee APRES cet appel, jamais avant.
    old_state = migrator.apply_initial_migration(
        ("accounting", "0002_accmove_accmoveline_and_more")
    )
    tenant = Tenant.objects.create(code="ACC-T1", name="Tenant test 0003")
    move = _make_move(old_state.apps, tenant=tenant, state="posted")
    move.narration = "modif avant migration : autorisee"
    move.save(update_fields=["narration"])  # pas d'exception : pas encore de trigger

    # --- Migration testee : le trigger d'immuabilite apparait ---
    new_state = migrator.apply_tested_migration(
        ("accounting", "0003_move_balance_and_immutability")
    )
    move_model = new_state.apps.get_model("accounting", "AccMove")
    move = move_model.objects.get(pk=move.pk)
    move.narration = "modif apres migration : doit etre rejetee"
    with pytest.raises(DjangoDbError):
        move.save(update_fields=["narration"])

    move.refresh_from_db()
    assert move.narration == "modif avant migration : autorisee"

    # --- Migration arriere : le trigger doit disparaitre proprement ---
    reverted_state = migrator.apply_tested_migration(
        ("accounting", "0002_accmove_accmoveline_and_more")
    )
    move_model = reverted_state.apps.get_model("accounting", "AccMove")
    move = move_model.objects.get(pk=move.pk)
    move.narration = "modif apres downgrade : de nouveau autorisee"
    move.save(update_fields=["narration"])  # ne doit plus lever


@pytest.mark.django_db
def test_move_field_aware_immutability_refinement_and_intentional_noop_reverse(
    migrator,
) -> None:
    """0005 affine le trigger 0003 (seuls les champs comptables restent
    bloques, `invoice_state` ajoute en 0006 reste modifiable). 0005
    declare volontairement `reverse_sql=migrations.RunSQL.noop` : le
    downgrade ne restaure PAS la fonction 0003 (bloquer TOUT UPDATE), il
    laisse en place la version affinee — qui est un sur-ensemble sûr du
    comportement attendu a cet etat (elle bloque toujours les champs
    comptables). C'est un choix delibere documente dans le fichier de
    migration, pas un defaut de reversibilite a corriger : on le
    verifie explicitement plutot que de forcer un faux test de reverse."""
    # 0004 : trigger 0003 (blunt) deja actif.
    state_0004 = migrator.apply_initial_migration(
        ("accounting", "0004_accpaymentterm_accpaymenttermline_acctax_and_more")
    )
    tenant = Tenant.objects.create(code="ACC-T2", name="Tenant test 0005/0006")
    move = _make_move(state_0004.apps, tenant=tenant, state="posted")
    move.narration = "refus attendu (trigger 0003 blunt)"
    with pytest.raises(DjangoDbError):
        move.save(update_fields=["narration"])
    move.refresh_from_db()

    # 0006 : trigger affine (0005) + colonne invoice_state (0006).
    state_0006 = migrator.apply_tested_migration(
        ("accounting", "0006_alter_accmove_options_accmove_invoice_state")
    )
    move_model = state_0006.apps.get_model("accounting", "AccMove")
    move = move_model.objects.get(pk=move.pk)
    assert move.invoice_state == "draft"  # valeur par defaut, colonne neuve

    # Champ comptable : toujours bloque.
    move.narration = "toujours refuse (champ comptable)"
    with pytest.raises(DjangoDbError):
        move.save(update_fields=["narration"])
    move.refresh_from_db()

    # Statut metier : desormais modifiable meme une fois postee (§5.1.5).
    move.invoice_state = "validated"
    move.save(update_fields=["invoice_state"])
    move.refresh_from_db()
    assert move.invoice_state == "validated"

    # Downgrade jusqu'a 0004 : 0006 s'annule proprement (colonne
    # supprimee), 0005 est un noop assume -> la fonction reste la
    # version affinee, ce qui reste correct (sur-ensemble sûr).
    reverted_state = migrator.apply_tested_migration(
        ("accounting", "0004_accpaymentterm_accpaymenttermline_acctax_and_more")
    )
    move_model = reverted_state.apps.get_model("accounting", "AccMove")
    move = move_model.objects.get(pk=move.pk)
    assert not hasattr(move, "invoice_state")
    move.narration = "toujours refuse apres downgrade (fonction affinee conservee)"
    with pytest.raises(DjangoDbError):
        move.save(update_fields=["narration"])
