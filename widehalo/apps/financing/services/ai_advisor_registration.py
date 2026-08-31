"""INT2 : auto-enregistrement d'une regle d'advisor d'actions DETERMINISTE
du module `financing` dans `core.services.advisor_rule_registry`, appele
depuis `apps.py::ready()` — meme patron exact que `apps.purchase.services.
ai_advisor_registration.register_advisor_rules()` deja etabli dans ce
chantier.

**Adaptateur mince, pas une nouvelle regle metier** : `_advise_on_
financing` enveloppe DIRECTEMENT `apps.financing.services.guarantees.
check_guarantee_coverage` (FIN2, deja teste — regle de couverture >= 120%
du credit, `GUARANTEE_COVERAGE_RATIO`) — AUCUN nouveau calcul de risque
contrepartie n'est introduit ici, uniquement une decision de QUAND ce
diagnostic deja calcule merite d'etre remonte comme recommandation
(dossier pas encore decide dont les suretes actives ne couvrent pas
encore le seuil)."""

from __future__ import annotations

from django.utils.translation import gettext

from apps.core.services.advisor_rule_registry import RecommendationCandidate, register_advisor_rule


def _advise_on_financing(
    tenant_id: str, action: str, role_code: str
) -> list[RecommendationCandidate]:
    del action, role_code  # pertinent quel que soit l'ecran/role de financement en cours
    from apps.financing.models import FinLoanApplication
    from apps.financing.services.guarantees import check_guarantee_coverage

    applications = FinLoanApplication.objects.filter(
        tenant_id=tenant_id,
        is_active=True,
        state__in=[FinLoanApplication.STATE_DRAFT, FinLoanApplication.STATE_SUBMITTED],
    )

    candidates: list[RecommendationCandidate] = []
    for application in applications:
        coverage = check_guarantee_coverage(application)
        if coverage["is_covered"]:
            continue

        ratio = coverage["coverage_ratio"]
        ratio_pct = (ratio * 100) if ratio is not None else 0
        candidates.append(
            RecommendationCandidate(
                label=gettext(
                    "Dossier %(reference)s : couverture des sûretés insuffisante "
                    "(%(ratio)s%% du credit demande) — completer les garanties"
                )
                % {"reference": application.reference, "ratio": f"{ratio_pct:.0f}"},
                target_module="financing",
            )
        )

    return candidates


def register_ai_advisor_rules() -> None:
    register_advisor_rule(
        "financing.guarantee_coverage_advisor",
        module="financing",
        label="Couverture des suretes insuffisante",
        function=_advise_on_financing,
    )
