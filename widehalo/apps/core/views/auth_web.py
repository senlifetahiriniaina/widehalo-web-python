"""Connexion web (session Django) — distincte de l'authentification JWT de
l'API (etape 4). Le selecteur de societe se limite ici a retenir le
premier tenant accessible de l'utilisateur en session ; un veritable
selecteur multi-societe (si l'utilisateur en a plusieurs) est un
enrichissement d'ecran hors perimetre de ce lot.

Ce module porte aussi les deux ecrans d'amorçage d'instance forces par
`apps.core.middleware.OnboardingMiddleware` : changement de mot de passe
obligatoire (compte cree par `bootstrap_admin`) et parametrage de la
premiere societe de l'instance."""

from __future__ import annotations

from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _

from apps.core.models.regulatory import CountryDefaultsProfile
from apps.core.models.tenant import Tenant
from apps.core.models.user import UserTenantMembership
from apps.core.services.smart_defaults import apply_country_defaults


def login_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        email = request.POST.get("email", "")
        password = request.POST.get("password", "")
        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            membership = (
                UserTenantMembership.objects.filter(user=user).order_by("-is_default").first()
            )
            if membership is not None:
                request.session["tenant_id"] = str(membership.tenant_id)
            return redirect("dashboard")
        return render(request, "login.html", {"error": True})

    return render(request, "login.html", {})


@login_required
def logout_view(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("login")


@login_required
def change_password_view(request: HttpRequest) -> HttpResponse:
    """Ecran force par `OnboardingMiddleware` tant que
    `request.user.must_change_password` est vrai (compte cree par
    `bootstrap_admin`) — reste aussi accessible librement ensuite pour tout
    utilisateur qui veut changer son mot de passe de sa propre initiative."""
    errors: list[str] = []
    if request.method == "POST":
        current_password = request.POST.get("current_password", "")
        new_password = request.POST.get("new_password", "")
        confirm_password = request.POST.get("confirm_password", "")
        if not request.user.check_password(current_password):
            errors.append(_("Mot de passe actuel incorrect."))
        elif new_password != confirm_password:
            errors.append(_("Les deux mots de passe saisis ne correspondent pas."))
        else:
            try:
                validate_password(new_password, user=request.user)
            except DjangoValidationError as exc:
                errors.extend(exc.messages)
        if not errors:
            request.user.set_password(new_password)
            request.user.must_change_password = False
            request.user.save(update_fields=["password", "must_change_password"])
            # Necessaire sans quoi Django invalide la session courante des
            # que le hash du mot de passe change, deconnectant l'utilisateur
            # en pleine ecran d'amorçage force.
            update_session_auth_hash(request, request.user)
            return redirect("dashboard")
    return render(request, "change_password.html", {"errors": errors})


@login_required
def setup_company_view(request: HttpRequest) -> HttpResponse:
    """Ecran force par `OnboardingMiddleware` tant qu'aucune societe n'existe
    encore sur l'instance (`Tenant.objects.exists()` — un controle global,
    jamais par utilisateur). Reprend la meme logique que la commande de
    management `create_tenant` (SmartDefaults par pays), sous forme
    d'ecran : cree le tenant, y rattache l'utilisateur courant comme membre
    par defaut, et active immediatement cette societe en session."""
    if Tenant.objects.exists():
        return redirect("dashboard")

    country_choices = list(
        CountryDefaultsProfile.objects.order_by("country_code").values_list(
            "country_code", flat=True
        )
    )
    errors: list[str] = []
    if request.method == "POST":
        code = request.POST.get("code", "").strip()
        name = request.POST.get("name", "").strip()
        nif = request.POST.get("nif", "").strip()
        country_code = request.POST.get("country_code", "").strip().upper()
        if not code or not name:
            errors.append(_("Le code et la raison sociale sont obligatoires."))
        elif country_code not in country_choices:
            errors.append(_("Pays non reconnu."))
        elif Tenant.objects.filter(code=code).exists():
            errors.append(_("Ce code société est déjà utilisé."))
        else:
            tenant = Tenant.objects.create(code=code, name=name, nif=nif, country_code=country_code)
            apply_country_defaults(tenant, country_code)
            UserTenantMembership.objects.create(user=request.user, tenant=tenant, is_default=True)
            request.session["tenant_id"] = str(tenant.id)
            return redirect("dashboard")

    return render(
        request,
        "setup_company.html",
        {"errors": errors, "country_choices": country_choices},
    )
