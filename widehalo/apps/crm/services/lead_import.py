"""CRM-5, seconde voie — l'import d'un fichier d'opportunites.

**Le critere, en entier** : « L'ecran pipeline vide affiche un etat vide
pedagogique proposant la creation d'une opportunite ET L'IMPORT D'UN
FICHIER, jamais un tableau vide sans message. » Le composant d'etat vide
livre par L4 porte deja `import_url`/`import_label`, et sa docstring les
nomme « la seconde voie du critere » — mais `apps/crm/urls.py` ne declarait
aucune route d'import : il n'y avait rien vers quoi pointer. Le critere
etait compte tenu sur sa moitie visible.

**Tout ou rien, avec un rapport ligne a ligne.** C'est la lecon BNK-2, payee
une fois : l'import de releves bancaires levait sur la premiere ligne fautive
alors que les precedentes etaient DEJA ECRITES — un lot a moitie charge, un
400, et des doublons au re-essai. Ici la validation se fait a blanc sur tout
le fichier ; si une seule ligne est invalide, rien n'est ecrit et le rapport
nomme chaque ligne fautive et son motif.

**Le numero de ligne est celui du TABLEUR.** L'import des partenaires rend
`row_index` a partir de zero et ignore la ligne d'en-tete : sa premiere
ligne de donnees s'affiche « Ligne 0 » quand l'utilisateur la voit en
ligne 2 dans Excel. Ici le numero rendu est celui qu'il lit a l'ecran.

**Le tiers se resout par son NOM, EN UN SEUL BALAYAGE.** La regle de
couplage n°1 interdit a `crm` de connaitre le modele `Partner`, et
`CrmLead.partner_id` est un `UUIDField`, jamais une cle etrangere. Le nom
passe donc par la surface publique de `partners` — mais jamais ligne par
ligne : `find_partner_by_name` charge TOUT le referentiel a chaque appel
(`list(Partner.objects.filter(tenant=...))`), ce qui rendrait l'import
quadratique. Un fichier de mille lignes sur un referentiel de mille tiers
ferait un million de comparaisons. C'est le defaut deja paye deux fois dans
ce depot — le rapprochement canonique de T3 et les candidats de lettrage de
BNK-3 — et il se voit en lisant la fonction appelee, jamais son nom.
`resolve_partner_ids_by_name` construit l'index une fois.

Un nom introuvable n'est PAS une erreur : l'opportunite se cree sans tiers,
et le rapport le dit — un prospect n'est souvent pas encore au referentiel,
et refuser la ligne obligerait a creer la fiche tiers avant la premiere
conversation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import transaction

from apps.core.models.tenant import Tenant
from apps.core.services.import_wizard import RowError
from apps.core.services.import_xlsx import fold_header, read_xlsx_rows
from apps.crm.services.leads import create_lead_quick
from apps.partners.services.public import resolve_partner_ids_by_name

#: en-tete attendu -> champ. La comparaison passe par `fold_header`, donc
#: « Montant attendu (MGA) », « montant attendu (mga) » et « MONTANT ATTENDU
#: (MGA) » designent la meme colonne.
COLONNES: tuple[tuple[str, str], ...] = (
    ("Nom", "name"),
    ("Tiers", "partner_name"),
    ("Contact", "contact_name"),
    ("Email", "email"),
    ("Téléphone", "phone"),
    ("Source", "source"),
    ("Montant attendu (MGA)", "expected_revenue_mga"),
)

#: Numero de la premiere ligne de DONNEES telle que l'utilisateur la voit
#: dans son tableur : la ligne 1 porte l'en-tete.
PREMIERE_LIGNE_DE_DONNEES = 2


@dataclass
class CrmLeadImportSummary:
    total_rows: int
    created_count: int = 0
    partner_matched_count: int = 0
    partner_unmatched_count: int = 0
    row_errors: list[RowError] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.row_errors


def _index_des_colonnes(entete: list[str]) -> dict[str, int]:
    replie = [fold_header(cellule) for cellule in entete]
    index: dict[str, int] = {}
    for libelle, champ in COLONNES:
        cible = fold_header(libelle)
        if cible in replie:
            index[champ] = replie.index(cible)
    return index


def _cellule(ligne: list[Any], index: dict[str, int], champ: str) -> str:
    position = index.get(champ)
    if position is None or position >= len(ligne):
        return ""
    valeur = ligne[position]
    return "" if valeur is None else str(valeur).strip()


def import_leads_xlsx(
    tenant: Tenant, file_bytes: bytes, *, filename: str = ""
) -> CrmLeadImportSummary:
    entete, lignes = read_xlsx_rows(file_bytes)
    index = _index_des_colonnes(entete)
    if "name" not in index:
        raise ValueError(
            "Colonne « Nom » absente du fichier : c'est la seule information "
            "sans laquelle une opportunite n'a pas de sens. Telechargez le "
            "modele pour retrouver les en-tetes attendus."
        )

    resume = CrmLeadImportSummary(total_rows=len(lignes))
    preparees: list[dict[str, Any]] = []
    # Un seul balayage du referentiel, pour tout le fichier.
    par_nom = resolve_partner_ids_by_name(
        tenant, {_cellule(ligne, index, "partner_name") for ligne in lignes}
    )

    for decalage, ligne in enumerate(lignes):
        numero = PREMIERE_LIGNE_DE_DONNEES + decalage
        erreurs: dict[str, list[str]] = {}

        nom = _cellule(ligne, index, "name")
        if not nom:
            erreurs["Nom"] = ["Obligatoire : une opportunite sans nom est introuvable a l'ecran."]

        brut = _cellule(ligne, index, "expected_revenue_mga")
        montant = Decimal(0)
        if brut:
            try:
                montant = Decimal(brut.replace(" ", "").replace(",", "."))
            except (InvalidOperation, ValueError):
                erreurs["Montant attendu (MGA)"] = [
                    f"« {brut} » n'est pas un montant. Attendu : un nombre, "
                    "par exemple 1500000 ou 1500000,50."
                ]
            else:
                if montant < 0:
                    erreurs["Montant attendu (MGA)"] = ["Un montant attendu n'est jamais negatif."]

        if erreurs:
            resume.row_errors.append(RowError(row_index=numero, errors=erreurs))
            continue

        nom_tiers = _cellule(ligne, index, "partner_name")
        partner_id = par_nom.get(nom_tiers) if nom_tiers else None
        if partner_id is not None:
            resume.partner_matched_count += 1
        elif nom_tiers:
            resume.partner_unmatched_count += 1

        preparees.append(
            {
                "name": nom,
                "partner_id": partner_id,
                "contact_name": _cellule(ligne, index, "contact_name")[:150],
                "email": _cellule(ligne, index, "email"),
                "phone": _cellule(ligne, index, "phone")[:32],
                "source": _cellule(ligne, index, "source")[:64],
                "expected_revenue_mga": montant,
            }
        )

    if not resume.is_valid:
        # Rien n'est ecrit : le rapport sert a corriger le fichier, pas a
        # deviner ce qui est passe. Les compteurs de rapprochement sont
        # remis a zero — annoncer « 3 tiers rapproches » sur un import
        # refuse ferait croire a une ecriture partielle.
        resume.partner_matched_count = 0
        resume.partner_unmatched_count = 0
        return resume

    with transaction.atomic():
        for champs in preparees:
            create_lead_quick(tenant=tenant, **champs)
            resume.created_count += 1

    return resume
