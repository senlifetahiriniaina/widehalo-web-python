"""L7 — les cinq critères IA, et le bloquant qu'ils cachaient.

**IA-2, le défaut le plus grave du lot.** `data_query_gateway.ask()`
faisait, dans son gestionnaire d'exception :

    except AIProviderError:
        answer, tools_called = _UNABLE_TO_COMPLETE_FR, []

La liste construite dans la boucle — alimentée APRÈS l'exécution réelle de
chaque outil — était détruite. Scénario : au tour 1 le LLM appelle
`sales.revenue_report`, l'outil lit vraiment le chiffre d'affaires du
tenant ; au tour 2 le fournisseur tombe ; l'`AiDataQuery` est persistée
avec `tools_called=[]`. **L'outil a lu les données, l'audit dit que rien
n'a été appelé** — l'inverse exact de ce que promet la docstring du champ.

Et le comportement était *asserté* par un test existant dont le fournisseur
échouait au PREMIER appel, cas où `[]` est correct. Il ne distinguait pas
« aucun outil » de « outils perdus ». D'où le test d'échec au 2ᵉ tour."""

from __future__ import annotations

import time

import pytest
from django.contrib.auth.models import Group
from django.test import Client

from apps.ai.models import AiDataQuery, AiExternalProviderConsent
from apps.ai.services.data_query_gateway import ask
from apps.core.models.tenant import Tenant
from apps.core.models.user import User
from apps.core.services.ai_assistant import (
    AIProviderError,
    AIProviderTimeoutError,
    StubAIProvider,
    ToolCall,
    ToolCallResult,
)
from apps.core.services.data_query_tool_registry import register_data_query_tool
from apps.core.tests.utils import grant_role, use_tenant

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPassw0rd!23"


@pytest.fixture
def tenant() -> Tenant:
    return Tenant.objects.create(code="L7-AI", name="IA L7 SARL")


@pytest.fixture
def user(tenant: Tenant) -> User:
    with use_tenant(tenant.id):
        created = User.objects.create_user(email="l7-ai@example.com", password=PASSWORD)
    grant_role(created, "commercial")
    return created


def _register_probe_tool(calls: list[str]) -> None:
    """Un outil qui ENREGISTRE son exécution : c'est la seule façon de
    prouver qu'il a réellement touché les données, indépendamment de ce que
    l'audit finit par consigner."""

    def _fn(tenant, user, **kwargs):
        calls.append("execute")
        return [{"chiffre_affaires": 1234}]

    register_data_query_tool(
        "l7.probe",
        module="ai",
        label="Sonde L7",
        description="Outil de test",
        parameters_schema={"type": "object", "properties": {}},
        required_permission="crm.view_crmlead",
        read_only=True,
        function=_fn,
        verification_route="crm:list",
    )


class _FailsOnSecondRound:
    """Répond une fois avec un appel d'outil, puis tombe."""

    def __init__(self, error: Exception) -> None:
        self._round = 0
        self._error = error

    def complete_with_tools(self, messages, tools, *, max_tokens=500):
        self._round += 1
        if self._round == 1:
            return ToolCallResult(
                content=None,
                tool_calls=[ToolCall(id="c1", name="l7.probe", arguments={})],
            )
        raise self._error


# --- IA-2 : la trace d'audit ---------------------------------------------------


def test_a_tool_executed_before_a_provider_failure_stays_in_the_audit_trail(
    tenant, user, monkeypatch
) -> None:
    """L'égalité qui était fausse : l'outil s'est exécuté une fois, l'audit
    en comptait zéro."""
    calls: list[str] = []
    _register_probe_tool(calls)
    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda t: _FailsOnSecondRound(AIProviderError("panne au 2e tour")),
    )

    with use_tenant(tenant.id):
        record = ask("Quel est mon chiffre d'affaires ?", tenant=tenant, user=user, locale="fr")

    # L'outil a REELLEMENT lu les donnees du tenant.
    assert calls == ["execute"]
    # ... et l'audit le dit.
    assert record.succeeded is False
    assert [entry["code"] for entry in record.tools_called] == ["l7.probe"]


def test_the_duration_of_the_call_is_recorded(tenant, user, monkeypatch) -> None:
    """IA-2 exige « l'utilisateur, le tenant, l'outil, les paramètres ET LA
    DURÉE ». Les quatre premiers étaient portés ; aucun champ de latence
    n'existait — les sept migrations du module n'en contenaient pas une
    occurrence."""
    calls: list[str] = []
    _register_probe_tool(calls)

    class _Answers:
        """Repond apres un delai MESURABLE.

        Sans cette pause, l'assertion ne pourrait etre que `>= 0` — vraie
        meme si la duree etait cablee a zero. C'est exactement ce qui s'est
        produit au premier jet : la falsification (`duration_ms = 0` en
        dur) laissait le test VERT. Une assertion toujours vraie ne prouve
        rien."""

        def complete_with_tools(self, messages, tools, *, max_tokens=500):
            time.sleep(0.02)
            return ToolCallResult(content="12 M Ar", tool_calls=[])

    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda t: _Answers(),
    )
    with use_tenant(tenant.id):
        record = ask("Question ?", tenant=tenant, user=user, locale="fr")
        # La relecture reste DANS le contexte du tenant : la RLS s'applique
        # aussi aux tests, et lire hors contexte renvoie « n'existe pas ».
        # STRICTEMENT positif : le fournisseur simule a dormi 20 ms.
        assert AiDataQuery.objects.get(pk=record.pk).duration_ms > 0


# --- IA-7 : la réponse d'attente -----------------------------------------------


def test_a_timeout_says_so_instead_of_blaming_the_configuration(tenant, user, monkeypatch) -> None:
    """Une seule phrase couvrait trois causes — fournisseur non configuré,
    budget épuisé, panne — et l'écran y ajoutait les trois hypothèses. Un
    dépassement de délai n'appelle pas la même conduite : le service
    répond, il est lent, et réessayer a du sens."""
    calls: list[str] = []
    _register_probe_tool(calls)
    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda t: _FailsOnSecondRound(AIProviderTimeoutError("delai depasse")),
    )

    with use_tenant(tenant.id):
        record = ask("Question longue ?", tenant=tenant, user=user, locale="fr")

    assert record.succeeded is False
    assert "plus de temps que prevu" in record.answer
    # La trace survit aussi a ce chemin-la.
    assert [entry["code"] for entry in record.tools_called] == ["l7.probe"]


def test_an_ordinary_failure_keeps_the_generic_message(tenant, user, monkeypatch) -> None:
    """La falsification : sans elle, « on distingue le délai » et « on a
    remplacé le message pour tout le monde » seraient indiscernables."""
    calls: list[str] = []
    _register_probe_tool(calls)
    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda t: _FailsOnSecondRound(AIProviderError("panne")),
    )

    with use_tenant(tenant.id):
        record = ask("Question ?", tenant=tenant, user=user, locale="fr")

    assert "plus de temps que prevu" not in record.answer
    assert "Impossible de terminer" in record.answer


# --- IA-4 : isolation à deux tenants -------------------------------------------


def test_a_tool_never_returns_another_tenants_data_even_when_named(monkeypatch) -> None:
    """« Une donnée d'un autre tenant n'est jamais retournée, même si la
    question la nomme explicitement. »

    Les six tests existants de la passerelle ne manipulaient qu'UN SEUL
    tenant : ils ne pouvaient rien dire de ce critère. Ici, l'outil reçoit
    le tenant depuis la passerelle et lit ses propres données — la question
    nomme l'autre société, et cela ne change rien."""
    tenant_a = Tenant.objects.create(code="L7-A", name="Société A")
    tenant_b = Tenant.objects.create(code="L7-B", name="Société B")
    with use_tenant(tenant_a.id):
        user_a = User.objects.create_user(email="l7-a@example.com", password=PASSWORD)
    grant_role(user_a, "commercial")
    with use_tenant(tenant_b.id):
        User.objects.create_user(email="l7-b@example.com", password=PASSWORD)

    seen_tenants: list[str] = []

    def _fn(tenant, user, **kwargs):
        seen_tenants.append(tenant.code)
        return [{"societe": tenant.code}]

    register_data_query_tool(
        "l7.tenant_probe",
        module="ai",
        label="Sonde tenant",
        description="Outil de test",
        parameters_schema={"type": "object", "properties": {}},
        required_permission="crm.view_crmlead",
        read_only=True,
        function=_fn,
    )

    class _CallsTheTool:
        def __init__(self) -> None:
            self._round = 0

        def complete_with_tools(self, messages, tools, *, max_tokens=500):
            self._round += 1
            if self._round == 1:
                return ToolCallResult(
                    content=None,
                    tool_calls=[ToolCall(id="c1", name="l7.tenant_probe", arguments={})],
                )
            return ToolCallResult(content="Réponse", tool_calls=[])

    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda t: _CallsTheTool(),
    )

    with use_tenant(tenant_a.id):
        record = ask(
            "Donne-moi le chiffre d'affaires de la Société B",
            tenant=tenant_a,
            user=user_a,
            locale="fr",
        )

    # L'outil n'a jamais ete invoque pour un autre tenant que l'appelant.
    assert seen_tenants == [tenant_a.code]
    assert record.tenant_id == tenant_a.id
    # L'enregistrement d'audit reste dans le tenant de l'appelant.
    with use_tenant(tenant_b.id):
        assert not AiDataQuery.objects.filter(pk=record.pk).exists()


# --- IA-9 : consentement -------------------------------------------------------


def test_a_configured_provider_stays_unused_without_the_tenants_consent(
    tenant, settings, monkeypatch
) -> None:
    """Le cœur d'IA-9 : brancher un fournisseur ne l'active pas.

    Sur une instance multi-sociétés, `AI_PROVIDER_CONFIG` dit ce que
    l'hébergeur a branché ; il ne dit pas quelle société accepte que ses
    chiffres sortent de son serveur."""
    from apps.ai.services.usage_budget import get_budget_gated_provider

    settings.AI_PROVIDER_CONFIG = {
        "backend": "mistral",
        "base_url": "https://example.invalid/v1",
        "api_key": "k",
        "model": "m",
    }

    with use_tenant(tenant.id):
        # Sans consentement : stub, aucun connecteur reel instancie.
        assert isinstance(get_budget_gated_provider(tenant), StubAIProvider)

        from apps.ai.services.external_consent import grant_consent

        grant_consent(tenant, backend="mistral", user=None)
        # La falsification : une fois consenti, le vrai connecteur revient.
        assert not isinstance(get_budget_gated_provider(tenant), StubAIProvider)


def test_a_consent_given_for_one_provider_does_not_cover_another(tenant, settings) -> None:
    """Changer de fournisseur redemande une acceptation : « acceptez-vous
    que vos données partent chez X ? » n'a pas la même réponse pour tout X.
    """
    from apps.ai.services.external_consent import grant_consent
    from apps.ai.services.usage_budget import get_budget_gated_provider

    settings.AI_PROVIDER_CONFIG = {
        "backend": "mistral",
        "base_url": "https://example.invalid/v1",
        "api_key": "k",
        "model": "m",
    }
    with use_tenant(tenant.id):
        grant_consent(tenant, backend="mistral", user=None)
        assert not isinstance(get_budget_gated_provider(tenant), StubAIProvider)

        settings.AI_PROVIDER_CONFIG = dict(settings.AI_PROVIDER_CONFIG, backend="deepseek")
        assert isinstance(get_budget_gated_provider(tenant), StubAIProvider)


def test_revoking_leaves_the_trace_rather_than_deleting_it(tenant) -> None:
    """Le modèle EST le journal : une révocation date la ligne, elle ne
    l'efface pas. Même discipline « versionner par insertion » que le
    dictionnaire d'indicateurs."""
    from apps.ai.services.external_consent import grant_consent, revoke_consent

    with use_tenant(tenant.id):
        granted = grant_consent(tenant, backend="mistral", user=None)
        assert granted.disclosure_text  # le texte exact montré est conservé
        revoke_consent(tenant, user=None)

        granted.refresh_from_db()
        assert granted.revoked_at is not None
        assert AiExternalProviderConsent.objects.filter(tenant=tenant).count() == 1


def test_the_consent_screen_lists_what_leaves_the_server(tenant, settings) -> None:
    """Le critère exige que l'activation « affiche EXPLICITEMENT quelles
    données sortiront ». L'écran l'énonce avant le bouton, jamais après."""
    settings.AI_PROVIDER_CONFIG = {
        "backend": "mistral",
        "base_url": "https://example.invalid/v1",
        "api_key": "k",
        "model": "m",
    }
    # `admin` est dans `CORE_MFA_REQUIRED_ROLES`, et cet ecran l'exige — la
    # parade habituelle du depot (« choisir un role hors de cette liste »)
    # n'est donc pas applicable ici. Le MFA est ecarte explicitement : son
    # enrolement est un parcours distinct, deja couvert par ses propres
    # tests, et le confondre avec celui-ci ferait echouer l'assertion pour
    # une raison etrangere au critere IA-9.
    settings.CORE_MFA_REQUIRED_ROLES = set()
    with use_tenant(tenant.id):
        admin = User.objects.create_user(email="l7-admin@example.com", password=PASSWORD)
    Group.objects.get_or_create(name="admin")[0].user_set.add(admin)

    client = Client()
    client.force_login(admin)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    body = client.get("/ai/provider-consent/").content.decode()
    assert "Ce qui quitte le serveur" in body
    assert "La question posée" in body
    assert "Aucun mot de passe" in body


# --- IA-8 : le lien de vérification --------------------------------------------


def test_each_consulted_source_links_to_the_screen_that_verifies_it(
    tenant, user, monkeypatch, settings
) -> None:
    """« Chaque réponse chiffrée fournit le lien vers l'écran qui permet de
    vérifier le chiffre. »

    Le bloc « Sources consultées » existait déjà — en `<strong>`. Il nommait
    le rapport sans jamais y mener : nommer la source dit d'où vient le
    chiffre, cela ne permet pas de le recontrôler. Le registre ne portait
    aucune notion d'écran de vérification."""
    settings.CORE_MFA_REQUIRED_ROLES = set()
    calls: list[str] = []
    _register_probe_tool(calls)

    class _CallsThenAnswers:
        def __init__(self) -> None:
            self._round = 0

        def complete_with_tools(self, messages, tools, *, max_tokens=500):
            self._round += 1
            if self._round == 1:
                return ToolCallResult(
                    content=None,
                    tool_calls=[ToolCall(id="c1", name="l7.probe", arguments={})],
                )
            return ToolCallResult(content="1 234 Ar", tool_calls=[])

    monkeypatch.setattr(
        "apps.ai.services.data_query_gateway.get_budget_gated_provider",
        lambda t: _CallsThenAnswers(),
    )

    client = Client()
    client.force_login(user)
    session = client.session
    session["tenant_id"] = str(tenant.id)
    session.save()

    body = client.get("/ai/data-query/?question=Chiffre+affaires").content.decode()
    assert "Sources consultées" in body

    # L'assertion porte sur le bloc « Sources consultées » LUI-MEME, jamais
    # sur la page entiere : le menu lateral contient deja un `href="/crm/"`,
    # et chercher cette chaine dans tout le corps rendait le test VERT meme
    # apres suppression du lien. Falsification a l'appui — c'est elle qui a
    # revele l'assertion creuse.
    block = body.split('aria-label="Sources consultées"', 1)[1].split("</div>", 1)[0]
    assert '<a href="/crm/">Sonde L7</a>' in block


def test_a_tool_without_a_verification_screen_is_still_named(tenant, user, monkeypatch) -> None:
    """La falsification, et elle a un sens : tous les chiffres ne se
    recontrôlent pas sur un écran. Dans ce cas la source reste nommée —
    un lien mort serait pire que pas de lien."""
    from apps.ai.views import _verification_url

    class _NoRoute:
        code = "x"
        verification_route = ""

    class _BadRoute:
        code = "y"
        verification_route = "route:inexistante"

    assert _verification_url(_NoRoute()) == ""
    assert _verification_url(_BadRoute()) == ""
    assert _verification_url(None) == ""
