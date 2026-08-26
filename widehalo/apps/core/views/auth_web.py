"""Connexion web (session Django) — distincte de l'authentification JWT de
l'API (etape 4). Le selecteur de societe se limite ici a retenir le
premier tenant accessible de l'utilisateur en session ; un veritable
selecteur multi-societe (si l'utilisateur en a plusieurs) est un
enrichissement d'ecran hors perimetre de ce lot."""

from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.core.models.user import UserTenantMembership


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
