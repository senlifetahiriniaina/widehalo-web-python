# Licence des icônes vendorisées

`sprite.svg` assemble un sous-ensemble de 39 icônes tirées du projet **Lucide**
(https://lucide.dev, https://github.com/lucide-icons/lucide), distribué sous licence **ISC**
(équivalente MIT), libre pour tout usage y compris commercial et la redistribution.

Texte complet de la licence : https://github.com/lucide-icons/lucide/blob/main/LICENSE

Fichiers sources récupérés individuellement depuis `raw.githubusercontent.com/lucide-icons/lucide`
(jamais via un CDN — `unpkg.com`/`cdnjs.cloudflare.com` sont bloqués par la politique de sortie de
ce projet), assemblés à la main en un seul fichier `<symbol>` par icône (grille 24×24, trait
1.75-2px, `stroke="currentColor"`, jamais de remplissage — conforme aux non-négociables du design
system : icônes outline uniquement, jamais remplies ni multicolores).

Usage dans un template : `<svg class="ic" aria-hidden="true"><use
href="{% static 'icons/sprite.svg' %}#ic-<nom>"></use></svg>` (toujours accompagné d'un
`aria-label`/`sr-only` sur l'élément parent si l'icône seule porte une action).
