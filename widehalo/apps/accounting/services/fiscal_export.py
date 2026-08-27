"""A12 — ACC-EXPORT-FISC1 : registre des "canevas" d'export fiscal.

Le document annexe (§3.5, meme reserve OECFM/DGI que partout ailleurs dans
cette app) demande que "chaque rapport fiscal (TVA, DCOM, IRSA...) dispose
d'un export au format attendu par les plateformes de teledeclaration
malgaches (eHetra, DConline)" — sans fournir les canevas exacts (mise en page
byte-pres, ordre des colonnes officiel, en-tetes numerotes). Reconstruire un
format bespoke par rapport a partir d'un document non primaire serait
fabriquer une structure non verifiee et la presenter comme fiable, ce que ce
projet s'interdit explicitement (§0.5/§3.5).

Choix V1 assume : au lieu d'un format d'export distinct par rapport, chaque
rapport fiscal deja construit (A8-A12) est exportable via le mecanisme
CSV/XLSX GENERIQUE deja partage par tous les rapports de cette app
(`services/reports.py::rows_to_bytes`, `format=csv|xlsx` sur chaque
endpoint concerne) — c'est deja un fichier tabulaire ouvrable dans Excel/
LibreOffice puis reimportable/retranscrit dans eHetra/DConline. Ce module
ajoute seulement un REGISTRE documentaire, `CANEVAS_NOTES`, associant a
chaque rapport fiscal une note lisible par un humain sur la plateforme/le
canevas DGI que cet export vise a approcher — pas une specification
d'export supplementaire, pas une garantie de conformite byte-pres.

Reserve OECFM/DGI explicite, rappelee sur CHAQUE entree du registre : ces
notes decrivent une INTENTION d'approximation, jamais une conformite
verifiee — a confirmer aupres d'un cabinet OECFM ou de la DGI avant tout
depot reel sur entreprises.impots.mg/dconline ou eHetra."""

from __future__ import annotations

_RESERVE = "a verifier aupres de la DGI/d'un cabinet OECFM avant tout depot reel"

# Cle : le code fonctionnel du rapport fiscal (tel que nomme au CDC/dans le
# plan de developpement), pas un identifiant technique d'endpoint — stable
# meme si l'URL de l'endpoint change.
CANEVAS_NOTES: dict[str, str] = {
    "ACC-TVA": (
        "Aucune declaration TVA dediee (pas de modele `acc_vat_declaration` a "
        "ce stade) : approche via `trial_balance`/`general_ledger` filtres sur "
        "les comptes de TVA collectee/deductible (`AccTax`, classe 445 PCG). "
        f"Canevas eHetra declaration TVA — {_RESERVE}."
    ),
    "ACC-DCOM": (
        "Export CSV/XLSX deja disponible (`GET /accounting/reports/dcom/"
        "{declaration_id}?format=csv|xlsx`). Classification par classe PCG du "
        "compte de contrepartie (repli documente, cf. `AccDcomDeclaration`, "
        "le document source ne detaille pas ses 9 canevas). "
        f"Canevas DConline 9 rubriques (classification transactions par tiers) — {_RESERVE}."
    ),
    "ACC-IRSA": (
        "Pas encore reportable dans ce codebase : l'IRSA (impot sur les "
        "revenus salariaux et assimiles, retenue a la source par l'employeur) "
        "suppose un module paie qui n'existe pas encore (aucun app `payroll`/"
        "`hr` dans ce monorepo a ce stade) — seule une echeance de calendrier "
        "existe (`AccTaxCalendar.DECLARATION_IRSA`, ACC-CAL1, A8), pas de "
        "donnees de calcul/declaration. Documente ici plutot que fabrique. "
        f"Canevas eHetra declaration IRSA — {_RESERVE} (et hors perimetre tant "
        "que le module paie n'existe pas)."
    ),
    "ACC-IRCM": (
        "Export CSV/XLSX deja disponible en tant que declaration unitaire "
        "(pas encore de rapport `rows_to_bytes` dedie — la declaration "
        "elle-meme, `AccIrcmDeclaration`, est un enregistrement scalaire, pas "
        "une liste de lignes ; consultable via l'API `GET /accounting/"
        "reports/ircm/generate` en JSON). "
        f"Canevas eHetra declaration IRCM annuelle — {_RESERVE}."
    ),
    "ACC-FONCIER": (
        "Enregistrement manuel uniquement (`AccLocalTax`), priorite basse au "
        "CDC — consultable via `GET /accounting/local-taxes` en JSON, pas "
        "encore de format CSV/XLSX dedie (peu de valeur pour un enregistrement "
        "unitaire par propriete). "
        f"Canevas plateforme communale IFT/IFPB — {_RESERVE}."
    ),
    "ACC-IS": (
        "Liasse fiscale composite PDF (`services/tax_returns.py::"
        "generate_liasse_is`) assemblant bilan + CR nature + CR fonction + "
        "flux de tresorerie — chaque etat individuel reste egalement "
        "exportable CSV/XLSX via son propre endpoint "
        "(`/accounting/reports/balance-sheet`, `/income-statement`, "
        "`/income-statement-by-function`, `/cash-flow`, tous `format=csv|xlsx`). "
        f"Canevas liasse ACC-IS (regime Impot Synthetique, seuil haut) — {_RESERVE}."
    ),
    "ACC-IR": (
        "Liasse fiscale composite PDF (`services/tax_returns.py::"
        "generate_liasse_ir`) assemblant les 5 etats financiers de base et "
        "les 4 annexes fiscales — memes etats individuellement exportables "
        "CSV/XLSX (cf. ACC-IS) plus `/accounting/reports/equity-variation` et "
        "`/accounting/reports/fixed-asset-annexes`, tous `format=csv|xlsx`. "
        f"Canevas liasse ACC-IR (regime reel) — {_RESERVE}."
    ),
}


def export_canevas_notes() -> dict[str, str]:
    """Retourne le registre `CANEVAS_NOTES` (fonction plutot que constante
    exposee directement dans l'API pour laisser la porte ouverte a un futur
    filtrage/enrichissement sans casser l'appelant)."""
    return dict(CANEVAS_NOTES)
