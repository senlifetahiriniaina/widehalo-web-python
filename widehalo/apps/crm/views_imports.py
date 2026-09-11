"""CRM-5, seconde voie — l'ecran d'import d'opportunites.

Meme discipline que `apps.partners.views_imports` et
`apps.accounting.views_imports` : session HTMX, jamais l'API JWT en interne.

**La garde d'ecran n'est pas facultative ici.** `apps.partners.
views_imports.imports_partners` ne porte que `@login_required` — il vit hors
des quatre modules que C-1 a gardes. Un ecran de `crm` qui CREE des
opportunites doit exiger `crm.add_crmlead` pour s'ouvrir, et pas seulement
pour se soumettre : laisser un role en lecture seule remplir un formulaire
d'import pour le refuser a l'envoi lui fait perdre son fichier et ne lui
apprend rien plus tot. C'est la regle posee en C-1d pour les huit ecrans de
creation.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.translation import gettext as _

from apps.core.services.import_xlsx import build_xlsx_template
from apps.core.services.permissions import screen_permission
from apps.core.views.tenant_web import resolve_tenant
from apps.crm.services.lead_import import COLONNES, import_leads_xlsx


@login_required
@screen_permission("crm.add_crmlead")
def download_lead_template(request: HttpRequest) -> HttpResponse:
    """Le modele est derive de `COLONNES`, jamais reecrit a la main.

    Deux listes d'en-tetes divergeraient a la premiere colonne ajoutee, et
    le fichier telecharge ne serait plus celui que le lecteur attend."""
    data = build_xlsx_template(
        [libelle for libelle, _champ in COLONNES],
        example_row=[
            "Extension entrepot Tamatave",
            "Client Exemple SARL",
            "Rakoto Jean",
            "contact@exemple.mg",
            "+261 34 00 000 00",
            "Salon",
            1500000,
        ],
    )
    response = HttpResponse(
        data, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="modele_import_opportunites.xlsx"'
    return response


@login_required
@screen_permission("crm.add_crmlead")
def imports_leads(request: HttpRequest) -> HttpResponse:
    tenant = resolve_tenant(request)
    summary = None
    error = None

    if request.method == "POST":
        fichier = request.FILES.get("file")
        if fichier is None:
            error = _("Aucun fichier fourni.")
        else:
            try:
                summary = import_leads_xlsx(tenant, fichier.read(), filename=fichier.name)
            except ValueError as exc:
                error = str(exc)

    return render(request, "crm/imports.html", {"summary": summary, "error": error})
