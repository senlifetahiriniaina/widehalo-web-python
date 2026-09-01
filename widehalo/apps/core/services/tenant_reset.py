"""Reinitialisation des donnees metier d'un tenant (chantier
sauvegarde/restauration/reinitialisation) : supprime TOUTES les donnees
metier de tous les modules (y compris plan comptable, catalogue,
partenaires), conserve le `Tenant`, les `User` et leurs
roles/appartenances de societe — repart d'une base vide, comme un tenant
fraichement cree (decision actee avec l'utilisateur, cf. plan).

Distinct de `apps.core.services.sandbox.purge_expired_sandboxes` : celui-ci
supprime un tenant SANDBOX entier (le `Tenant` lui-meme disparait), jamais
une remise a zero d'un tenant normal qui doit rester utilisable juste
apres. Distinct aussi par la suppression MULTI-PASSES (jamais un ordre de
dependance FK code en dur) : pour chaque modele concret de `BaseModel`,
on tente `Model.all_objects.filter(tenant=tenant).delete()`, on capture
`ProtectedError` pour les modeles dont une FK `on_delete=PROTECT` bloque
encore (typiquement une ligne referencee par un modele pas encore traite
dans ce passage), et on retente au passage suivant — meme garde-fou
« aucun progres » que `tenant_export.import_tenant_archive` (une boucle
qui ne progresse plus jamais signale une dependance reellement
non-resolvable plutot que de tourner indefiniment)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.core.management import call_command
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils.translation import gettext as _

from apps.core.models.backup import TenantBackupSchedule, TenantDataOperation
from apps.core.models.document import Document
from apps.core.models.tenant import Tenant
from apps.core.models.user import User, UserTenantMembership
from apps.core.services.object_remap import iter_concrete_basemodel_subclasses
from apps.core.tenant_context import activate_tenant

if TYPE_CHECKING:
    from apps.core.models.base import BaseModel

# Modeles jamais effaces par une reinitialisation : le `Tenant` lui-meme,
# les comptes `User` (partages entre tenants, cf. `apps.core.models.user`)
# et leurs appartenances de societe (`UserTenantMembership`) — decision
# actee : on conserve le tenant et ses utilisateurs/roles, seules les
# donnees METIER sont supprimees.
#
# `Document`/`TenantDataOperation`/`TenantBackupSchedule` sont exclus pour
# la MEME raison (bookkeeping du socle, pas une donnee metier saisie par
# l'utilisateur), avec une justification supplementaire et imperative,
# propre a ce mecanisme : `tenant_backup.restore_tenant_from_archive`
# appelle `reset_tenant_data(reseed=False)` PUIS cree son
# `TenantDataOperation` final en referencant le `Document` source de la
# restauration — si `reset_tenant_data` effacait ce `Document` au passage
# (comme n'importe quelle autre donnee tenant-scopee), la restauration se
# detruirait elle-meme sa propre source avant meme d'avoir fini, et toute
# reinitialisation effacerait du meme coup l'historique d'audit qui ne
# devient utile qu'APRES l'operation (on veut pouvoir consulter, apres un
# reset, qu'un reset a bien eu lieu — pas seulement avant).
_EXCLUDED_MODELS = {
    Tenant,
    User,
    UserTenantMembership,
    Document,
    TenantDataOperation,
    TenantBackupSchedule,
}


def reset_tenant_data(
    tenant: Tenant, *, reseed: bool = True, triggered_by: User | None = None
) -> dict[str, int]:
    """Vide toutes les donnees metier de `tenant`, puis (si `reseed=True`)
    rejoue la sequence de chargement par defaut d'un tenant neuf
    (`apply_country_defaults` + PCG2005 + journaux + catalogue de tickets +
    pipeline commercial par defaut + motifs de perte par defaut — meme
    sequence exacte que `apps.core.management.commands.create_tenant`).

    `reseed=False` est reserve a l'usage interne de
    `tenant_backup.restore_tenant_from_archive` : la restauration reimporte
    de vraies donnees juste apres le vidage, rejouer les seeds par defaut
    serait a la fois inutile et incorrect (l'archive restauree porte deja
    son propre plan comptable/catalogue).

    Retourne un `dict[str, int]` du nombre de lignes supprimees par
    modele (`app_label.model` -> compte), meme forme que les `dict[str,
    int]` deja retournes par `export_tenant_archive`/
    `import_tenant_archive` (coherence de discipline avec ce module
    voisin)."""
    models: list[type[BaseModel]] = [
        model for model in iter_concrete_basemodel_subclasses() if model not in _EXCLUDED_MODELS
    ]

    deleted_counts: dict[str, int] = {}
    with activate_tenant(tenant.id):
        pending = models
        while pending:
            still_pending: list[type[BaseModel]] = []
            made_progress = False
            for model in pending:
                label = model._meta.label_lower
                try:
                    with transaction.atomic():
                        deleted, _per_model = model.all_objects.filter(tenant=tenant).delete()
                except ProtectedError:
                    still_pending.append(model)
                    continue
                if deleted:
                    made_progress = True
                    deleted_counts[label] = deleted_counts.get(label, 0) + deleted

            if still_pending and not made_progress:
                raise ValueError(
                    _(
                        "Impossible de réinitialiser les données du tenant : des "
                        "dépendances entre modèles ne peuvent pas être résolues "
                        "(référence protégée non supprimable)."
                    )
                )
            pending = still_pending

        if reseed:
            # Meme sequence exacte que
            # `apps.core.management.commands.create_tenant` — le tenant
            # doit ressortir dans le meme etat qu'un tenant neuf, jamais
            # une coquille vide a reconfigurer a la main. PCG charge AVANT
            # les journaux (resolution de `default_account` par prefixe de
            # code), meme ordre imperatif.
            from apps.core.services.smart_defaults import apply_country_defaults

            apply_country_defaults(tenant, tenant.country_code)
            call_command("load_ticket_type_catalog", tenant=tenant.code)
            call_command("load_pcg2005", tenant=tenant.code)
            call_command("load_default_journals", tenant=tenant.code)
            call_command("load_default_pipeline", tenant=tenant.code)
            call_command("load_default_lost_reasons", tenant=tenant.code)
            call_command("load_material_references", tenant=tenant.code)
            call_command("load_epi_standards", tenant=tenant.code)
            call_command("load_customization_options", tenant=tenant.code)
            call_command("load_default_product_catalog", tenant=tenant.code)

    return deleted_counts
