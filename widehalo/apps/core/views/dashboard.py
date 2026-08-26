from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Page d'accueil — volontairement legere (texte + quelques liens),
    aucun tableau lourd ici, pour respecter le budget de 200 Ko compresse."""
    return render(request, "dashboard.html", {})
