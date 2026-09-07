from __future__ import annotations

from django.db import models

from apps.core.db.uuid7 import uuid7


class IdempotencyKey(models.Model):
    """Rejoue la reponse originale si un POST marque @idempotent est
    soumis a nouveau avec la meme cle (meme corps) — evite les doublons
    d'effet en cas de retransmission reseau (contrainte de connectivite
    malgache variable).

    **`tenant_id` est un UUID nu et non la FK de `BaseModel`**, parce
    qu'un appel peut legitimement n'avoir aucun tenant resolu (appelant
    non authentifie). La consequence est que cette table echappe a
    `apply_rls`, qui selectionne sur `issubclass(model, BaseModel)` — ce
    n'est pas une fuite (la seule lecture du depot filtre sur le triplet
    complet, et le `unique_together` porte sur ce meme triplet), mais un
    filet de securite absent, fige et rendu visible par
    `tests/architecture/test_rls_coverage.py`."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    tenant_id = models.UUIDField(null=True, blank=True)
    user_id = models.UUIDField(null=True, blank=True)
    key = models.CharField(max_length=255)
    request_hash = models.CharField(max_length=64)
    response_status = models.PositiveSmallIntegerField()
    response_body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()

    class Meta:
        db_table = "core_idempotency_key"
        constraints = [
            # **L'unicité ne mordait PAS quand `tenant_id` était nul**, et
            # c'est un `unique_together` classique qui le cachait :
            # PostgreSQL considère par défaut deux NULL comme distincts dans
            # un index unique. Le triplet (NULL, utilisateur, clef)
            # n'entrait donc en collision avec rien — autrement dit
            # l'idempotence n'était pas garantie pour les appels dont le
            # tenant n'est pas résolu, qui sont précisément ceux où
            # l'appelant a le moins de contexte pour se protéger lui-même.
            #
            # Trouvé en FALSIFIANT : retirer le retrait de la ligne périmée
            # avant réécriture aurait dû produire une `IntegrityError`, et
            # ne produisait rien du tout.
            #
            # `nulls_distinct=False` (PostgreSQL 15+, Django 5) dit
            # exactement ce qu'on veut : deux NULL sont ÉGAUX pour cette
            # contrainte. La réponse par contraintes partielles aurait
            # demandé d'en écrire trois — une par combinaison de nullité —
            # et la troisième aurait été oubliée.
            models.UniqueConstraint(
                fields=["tenant_id", "user_id", "key"],
                name="uniq_core_idemp_tenant_user_key",
                nulls_distinct=False,
            )
        ]
        indexes = [
            # La purge périodique et le filtre de TTL balaient tous deux sur
            # ce champ. Sans index, chaque appel à un endpoint idempotent
            # ferait un parcours complet d'une table qui n'a, par
            # construction, aucune raison de rester petite.
            models.Index(fields=["expires_at"], name="idx_core_idemp_expires"),
        ]

    def __str__(self) -> str:
        return f"{self.key} ({self.response_status})"
