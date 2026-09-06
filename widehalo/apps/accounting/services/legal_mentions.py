"""L17 — la mention de non-assujettissement a la TVA, portee par les
documents legaux d'un tenant qui n'en collecte pas.

**Le defaut ferme.** Depuis que `sales` calcule reellement la TVA (L5), un
tenant au regime de l'Impot Synthetique — ou au regime reel sans
assujettissement — emet des documents parfaitement justes au calcul :
`amount_tax` vaut zero partout, aucun compte de TVA n'est jamais credite.
Mais la facture legale, elle, imprimait sans condition trois lignes :

    Total HT / Subtotal excl. tax   |  1 000 000 Ar
    TVA / VAT                       |          0 Ar
    Total TTC / Total incl. tax     |  1 000 000 Ar

« TVA : 0 » et « TVA non applicable » ne disent pas la meme chose. Le
premier affirme qu'une taxe existe et vaut zero ; le second dit que le
document n'entre pas dans le champ de la taxe. Et « HT »/« TTC » n'ont
aucun sens sur un document sans taxe : ils opposent deux montants qui sont
le meme. Un document `is_legal_document=True`, donc archive et immuable,
n'est pas l'endroit ou laisser cette approximation.

**Pourquoi la mention est automatique plutot que libre.** Le champ
`Tenant.legal_mentions` existe et reste intact : il porte les mentions que
le tenant CHOISIT (escompte, penalites de retard, conditions de reglement).
La non-assujettissement, elle, n'est pas un choix de redaction : c'est une
consequence mecanique du `fiscal_regime` que le tenant a lui-meme
positionne. La laisser au champ libre revient a ce qu'un tenant qui oublie
de la saisir emette des factures incompletes sans que rien ne le signale.

**Reserve OECFM/DGI — a lire avant tout usage en production reelle.** Le
depot ne contient AUCUN referentiel fiscal malgache : le « document
annexe » cite dans tout `apps/accounting/` n'y est pas, aucune obligation
de facturation propre au regime synthetique n'y est documentee, et le
cahier des charges ne parle que de « mentions obligatoires PARAMETREES pour
le tenant » (SAL-8) sans en lister aucune. La formulation ci-dessous est
donc une redaction raisonnable et prudente, pas une citation d'un texte
verifie — meme statut que `tva.taux_normal` ou le bareme IRSA, et meme
consigne : **a confirmer aupres d'un expert-comptable OECFM ou de la DGI**.
Un tenant qui connait la formulation exacte attendue par son administration
peut la surcharger par `Tenant.legal_mentions`, rendu juste en dessous."""

from __future__ import annotations

from django.utils.translation import gettext as _

from apps.accounting.services.taxes import vat_applicable
from apps.core.models.tenant import Tenant


def mandatory_vat_mention(tenant: Tenant) -> str:
    """Mention a porter sur les documents legaux de ce tenant, ou `""`.

    Chaine vide pour un tenant assujetti : il n'a rien a declarer de plus
    que la ventilation HT/TVA/TTC, qui parle d'elle-meme. Jamais une
    exception — un document legal ne doit pas cesser d'etre produit parce
    qu'une mention ne se resout pas."""
    if vat_applicable(tenant):
        return ""
    if tenant.fiscal_regime == Tenant.FISCAL_REGIME_SYNTHETIC:
        return str(_("TVA non applicable — entreprise relevant du régime de l'impôt synthétique."))
    return str(_("TVA non applicable — entreprise non assujettie à la TVA."))
