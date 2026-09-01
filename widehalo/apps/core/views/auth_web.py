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
from django.core.management import call_command
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django_otp import login as otp_login

from apps.core.models.regulatory import CountryDefaultsProfile
from apps.core.models.tenant import Tenant
from apps.core.models.user import PREFERRED_LANGUAGE_CHOICES, UserTenantMembership
from apps.core.services import mfa as mfa_service
from apps.core.services.email_change import confirm_email_change
from apps.core.services.permissions import user_role_codes
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


def confirm_email_view(request: HttpRequest, token: str) -> HttpResponse:
    """UXR1 — vue PUBLIQUE (pas de `@login_required` : le destinataire
    clique depuis sa boite mail, potentiellement sans jamais s'etre
    connecte depuis ce navigateur, cf. docstring de
    `UserEmailChangeRequest`). Rend une page AUTONOME (comme `login.html`,
    jamais `{% extends "base.html" %}`) : `base.html` suppose une session
    (menu compte, recherche, sidebar) que cette vue n'a structurellement
    jamais — meme choix deja fait par `login_view` pour la meme raison."""
    success = confirm_email_change(token)
    return render(request, "confirm_email.html", {"success": success})


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
def profile_view(request: HttpRequest) -> HttpResponse:
    """Ecran de profil editable (chantier menu compte utilisateur signale
    par l'utilisateur : « voir le profil » depuis le nouveau menu topbar).
    Meme style manuel que `change_password_view` (pas de `forms.py`, pas de
    `django.contrib.messages` — jamais utilise dans ce depot). `email`
    reste affiche en lecture seule : c'est l'identite de connexion
    (`USERNAME_FIELD`), la modifier passe desormais par l'ecran admin
    (`apps.core.views.admin_users.admin_user_edit` -> `services/
    email_change.py`), jamais depuis cet auto-service. `Rôle(s)` reste en
    lecture seule (inchange, UXR1 ne touche pas ce point).

    Deux formulaires distincts postent sur cette meme URL, distingues par
    la presence de `tenant_id` (selecteur de societe) — le formulaire
    profil (nom/prenom/telephone/langue) n'en porte jamais.

    **Selecteur de societe (UXR1)** : `tenant_id` soumis n'est JAMAIS pris
    tel quel — on verifie qu'une ligne `UserTenantMembership` (request.user,
    ce tenant) existe reellement avant de positionner
    `request.session["tenant_id"]` (jamais une auto-inscription implicite a
    une societe dont l'utilisateur n'est pas deja membre)."""
    user = request.user
    errors: list[str] = []
    success = False

    if request.method == "POST" and "tenant_id" in request.POST:
        tenant_id = request.POST.get("tenant_id", "").strip()
        membership_exists = UserTenantMembership.objects.filter(
            user=user, tenant_id=tenant_id
        ).exists()
        if membership_exists:
            request.session["tenant_id"] = tenant_id
        return redirect("profile")

    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        phone = request.POST.get("phone", "").strip()
        preferred_language = request.POST.get("preferred_language", "").strip()
        valid_languages = {code for code, _label in PREFERRED_LANGUAGE_CHOICES}
        if preferred_language not in valid_languages:
            errors.append(_("Langue préférée invalide."))
        if not errors:
            user.first_name = first_name
            user.last_name = last_name
            user.phone = phone
            user.preferred_language = preferred_language
            user.save(update_fields=["first_name", "last_name", "phone", "preferred_language"])
            success = True

    return render(
        request,
        "profile.html",
        {
            "errors": errors,
            "success": success,
            "role_codes": sorted(user_role_codes(user)),
            "language_choices": PREFERRED_LANGUAGE_CHOICES,
            "tenant_memberships": UserTenantMembership.objects.filter(user=user).select_related(
                "tenant"
            ),
        },
    )


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
            # Catalogue de types de tickets helpdesk (54 entrees) — jamais
            # vide pour un nouveau tenant, y compris (surtout) via ce
            # parcours web reel, cf. plan section "catalogue de tickets
            # helpdesk vide par defaut". Meme mecanisme `call_command` que
            # `create_tenant.py`/`seed_core.py` (aucune dependance Python
            # declaree vers `helpdesk`).
            call_command("load_ticket_type_catalog", tenant=tenant.code)
            # Plan comptable PCG 2005 (generique + sectoriel, cf. UXR7) et 7
            # journaux comptables par defaut — jamais vides pour un nouveau
            # tenant, meme convention `call_command` que ci-dessus. PCG
            # charge AVANT les journaux : `load_default_journals` resout
            # `default_account` (BQ/CAI) par prefixe de code parmi les
            # comptes deja crees, donc l'ordre importe.
            call_command("load_pcg2005", tenant=tenant.code)
            call_command("load_default_journals", tenant=tenant.code)
            # Pipeline commercial par defaut (HubSpot, 7 etapes — cf. analyse
            # comparative des 5 principaux CRM mondiaux) — meme convention
            # `call_command` que ci-dessus (aucune dependance Python
            # declaree vers `crm`).
            call_command("load_default_pipeline", tenant=tenant.code)
            # Motifs de perte d'opportunite par defaut (7 categories metier
            # — cf. analyse comparative des motifs de perte des 5 principaux
            # CRM mondiaux) — meme convention `call_command` que ci-dessus.
            call_command("load_default_lost_reasons", tenant=tenant.code)
            # Referentiel matieres/normes/personnalisation (LIFE MDG) puis
            # catalogue par defaut de 30 EPI/vetements techniques
            # fabricables a Madagascar (Volet 2 du document source,
            # perimetre coupe-couture-ennoblissement) — meme convention
            # `call_command`. Ordre impose : matieres et normes AVANT le
            # catalogue produit (resolution material_code/standard_codes).
            call_command("load_material_references", tenant=tenant.code)
            call_command("load_epi_standards", tenant=tenant.code)
            call_command("load_customization_options", tenant=tenant.code)
            call_command("load_default_product_catalog", tenant=tenant.code)
            UserTenantMembership.objects.create(user=request.user, tenant=tenant, is_default=True)
            request.session["tenant_id"] = str(tenant.id)
            return redirect("dashboard")

    return render(
        request,
        "setup_company.html",
        {"errors": errors, "country_choices": country_choices},
    )


@login_required
def mfa_view(request: HttpRequest) -> HttpResponse:
    """Ecran web MFA (enrolement TOTP la premiere fois, puis verification a
    chaque session non encore verifiee) — reutilise integralement
    `apps.core.services.mfa` (meme logique que les endpoints API
    `/api/v1/auth/mfa/*`, jamais dupliquee) ; seule la persistance differe :
    ici une session web (`django_otp.login`), la ou l'API retourne un
    couple de jetons JWT.

    Bug reel corrige (jamais construit avant) : `apps.core.middleware.
    MFAEnforcementMiddleware` redirige vers cette URL depuis l'origine du
    socle (Lot 1, etape 4) mais aucune route/vue/template n'existait
    encore — tout compte soumis a MFA obligatoire (admin/direction/
    comptable/rh, cf. `settings.CORE_MFA_REQUIRED_ROLES`, et tout
    superutilisateur) restait bloque en boucle sur une 404 des sa premiere
    connexion web, jamais detecte plus tot faute d'avoir teste ce parcours
    en navigateur reel avec un compte MFA obligatoire."""
    user = request.user
    is_verified = getattr(user, "is_verified", lambda: True)()
    if not mfa_service.mfa_required_for_user(user) or is_verified:
        return redirect("dashboard")

    has_device = mfa_service.has_confirmed_device(user)
    error: str | None = None

    if request.method == "POST":
        token = request.POST.get("token", "").strip()
        if not has_device:
            device = mfa_service.enroll_device(user)
            if mfa_service.confirm_device(device, token):
                otp_login(request, device)
                return redirect("dashboard")
            error = _("Code invalide.")
        else:
            verified_device = mfa_service.verify_token(user, token)
            if verified_device is not None:
                otp_login(request, verified_device)
                return redirect("dashboard")
            error = _("Code invalide.")

    context: dict[str, object] = {"error": error, "has_device": has_device}
    if not has_device:
        device = mfa_service.enroll_device(user)
        context["qr_data_uri"] = mfa_service.generate_totp_qr_data_uri(device)

    return render(request, "mfa.html", context)
