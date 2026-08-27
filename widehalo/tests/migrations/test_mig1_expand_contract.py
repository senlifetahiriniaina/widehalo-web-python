"""MIG-1 (§9.4 du CDC, pattern expand/migrate/contract) : la migration
`accounting.0006_alter_accmove_options_accmove_invoice_state` ajoute la
colonne obligatoire `invoice_state` (`FSMField`, `default="draft"`,
non-nullable) sur `acc_move`. C'est le cas d'ecole du "expand" d'un
rolling deploy : au moment ou la migration tourne, des lignes ecrites par
l'ANCIEN code (qui ignore totalement `invoice_state`) existent deja en
base. La migration doit :

1. s'appliquer sans exiger de valeur explicite pour les lignes
   preexistantes (sinon le déploiement casse) ;
2. leur donner une valeur par defaut correcte (`"draft"`) sans
   intervention manuelle ;
3. laisser le NOUVEAU code ecrire des lignes qui, elles, ignorent aussi
   `invoice_state` (ancien ET nouveau code coexistent pendant le rolling
   deploy, avant que le "contract" ne rende le champ obligatoire cote
   application) — verifie via le modele historique `apps.get_model()`,
   jamais la classe `AccMove` couramment importable, pour rester fidele
   a la forme reelle prise par la base a cet instant precis de
   l'historique des migrations.

Recree tout le schema (django-test-migrations) : marque `slow`."""

from __future__ import annotations

from datetime import date

import pytest
from django.db import Error as DjangoDbError

pytestmark = pytest.mark.slow


@pytest.mark.django_db
def test_invoice_state_column_gets_safe_default_for_preexisting_rows(migrator) -> None:
    old_state = migrator.apply_initial_migration(
        ("accounting", "0005_move_immutability_field_aware")
    )

    tenant_model = old_state.apps.get_model("core", "Tenant")
    fiscal_year_model = old_state.apps.get_model("accounting", "AccFiscalYear")
    period_model = old_state.apps.get_model("accounting", "AccPeriod")
    journal_model = old_state.apps.get_model("accounting", "AccJournal")
    move_model = old_state.apps.get_model("accounting", "AccMove")

    tenant = tenant_model.objects.create(code="MIG1", name="Tenant MIG-1")
    fiscal_year = fiscal_year_model.objects.create(
        tenant=tenant, code="FY26", date_start=date(2026, 1, 1), date_end=date(2026, 12, 31)
    )
    period = period_model.objects.create(
        tenant=tenant,
        fiscal_year=fiscal_year,
        code="2026-01",
        date_start=date(2026, 1, 1),
        date_end=date(2026, 1, 31),
    )
    journal = journal_model.objects.create(
        tenant=tenant, code="OD", name="Operations diverses", type="misc", sequence_prefix="OD"
    )

    # Ligne ecrite par l'ANCIEN code : `invoice_state` n'existe pas
    # encore dans son shape de modele, impossible de le renseigner meme
    # en le voulant.
    preexisting_move = move_model.objects.create(
        tenant=tenant,
        journal=journal,
        period=period,
        date=date(2026, 1, 15),
        state="draft",
    )
    assert not hasattr(preexisting_move, "invoice_state")

    # --- "expand" : la migration MIG-1 tourne pendant que l'ancien code
    # tourne encore (rolling deploy) ---
    new_state = migrator.apply_tested_migration(
        ("accounting", "0006_alter_accmove_options_accmove_invoice_state")
    )
    new_move_model = new_state.apps.get_model("accounting", "AccMove")

    # La ligne preexistante recoit la valeur par defaut sans intervention.
    reloaded = new_move_model.objects.get(pk=preexisting_move.pk)
    assert reloaded.invoice_state == "draft"

    # Le NOUVEAU code peut ecrire en connaissant `invoice_state`...
    new_journal = new_state.apps.get_model("accounting", "AccJournal").objects.get(pk=journal.pk)
    explicit_move = new_move_model.objects.create(
        tenant_id=tenant.id,
        journal=new_journal,
        period=new_state.apps.get_model("accounting", "AccPeriod").objects.get(pk=period.pk),
        date=date(2026, 1, 16),
        state="draft",
        invoice_state="to_validate",
    )
    assert explicit_move.invoice_state == "to_validate"

    # ...et du code qui, comme l'ancien, ignore encore la colonne
    # (deploiement partiel : certains workers tournent encore sur
    # l'ancienne version applicative) continue d'ecrire sans erreur,
    # grace au default — c'est precisement la garantie "expand" avant
    # le "contract" (rendre le champ obligatoire cote application une
    # fois le rollout termine, hors perimetre de cette migration).
    coexisting_move = new_move_model.objects.create(
        tenant_id=tenant.id,
        journal=new_journal,
        period=new_state.apps.get_model("accounting", "AccPeriod").objects.get(pk=period.pk),
        date=date(2026, 1, 17),
        state="draft",
    )
    assert coexisting_move.invoice_state == "draft"


@pytest.mark.django_db
def test_invoice_state_addfield_is_reversible(migrator) -> None:
    old_state = migrator.apply_initial_migration(
        ("accounting", "0005_move_immutability_field_aware")
    )
    tenant_model = old_state.apps.get_model("core", "Tenant")
    tenant = tenant_model.objects.create(code="MIG1B", name="Tenant MIG-1 reverse")

    migrator.apply_tested_migration(
        ("accounting", "0006_alter_accmove_options_accmove_invoice_state")
    )
    reverted_state = migrator.apply_tested_migration(
        ("accounting", "0005_move_immutability_field_aware")
    )
    move_model = reverted_state.apps.get_model("accounting", "AccMove")
    assert "invoice_state" not in {f.name for f in move_model._meta.get_fields()}

    # Verifie aussi que le contract-side (RunSQL 0003/0005 sur les champs
    # comptables) reste actif independamment de MIG-1 : la coherence
    # inter-migrations n'a pas ete cassee par ce test.
    journal_model = reverted_state.apps.get_model("accounting", "AccJournal")
    fiscal_year_model = reverted_state.apps.get_model("accounting", "AccFiscalYear")
    period_model = reverted_state.apps.get_model("accounting", "AccPeriod")
    fiscal_year = fiscal_year_model.objects.create(
        tenant_id=tenant.id, code="FY27", date_start=date(2027, 1, 1), date_end=date(2027, 12, 31)
    )
    period = period_model.objects.create(
        tenant_id=tenant.id,
        fiscal_year=fiscal_year,
        code="2027-01",
        date_start=date(2027, 1, 1),
        date_end=date(2027, 1, 31),
    )
    journal = journal_model.objects.create(
        tenant_id=tenant.id, code="OD2", name="OD", type="misc", sequence_prefix="OD2"
    )
    move = move_model.objects.create(
        tenant_id=tenant.id, journal=journal, period=period, date=date(2027, 1, 5), state="posted"
    )
    move.narration = "doit rester bloque"
    with pytest.raises(DjangoDbError):
        move.save(update_fields=["narration"])
