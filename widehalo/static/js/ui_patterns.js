/*
 * Patterns Alpine.js reutilisables (UI1-3, refonte ergonomie/interactivite).
 *
 * Poses UNE FOIS ici, charges par `templates/base.html`, consommes par tous
 * les ecrans sans qu'aucun des ~160 templates n'ait besoin d'etre modifie
 * individuellement. Aucune dependance vendorisee/CDN supplementaire — pur
 * JS + l'Alpine.js deja servi localement (paquet `django-unfold`).
 *
 * 1. `whModal()` : composant modale generique (x-data), ouverture/fermeture
 *    + overlay, utilisable sur n'importe quel ecran via
 *    `x-data="whModal()"` (cf. la modale de confirmation ci-dessous, qui
 *    est une simple application de ce meme patron via le store partage
 *    `confirmDialog`).
 *
 * 2. Confirmation destructrice generalisee : au lieu d'un `onclick="return
 *    confirm(...)"` disperse dans les templates (aucun trouve dans l'audit
 *    de ce chantier — cf. plan), on intercepte l'evenement standard htmx
 *    `htmx:confirm` (declenche par l'attribut `hx-confirm="..."` deja
 *    supporte nativement par htmx) et on remplace le `window.confirm()`
 *    natif du navigateur par notre modale Alpine accessible. Tout ecran,
 *    present ou futur, qui ajoute `hx-confirm="Etes-vous sur ?"` a un
 *    bouton/lien recoit automatiquement ce patron, sans configuration
 *    supplementaire.
 *
 * 3. Toasts de notification : store Alpine `toast`, affiche un message
 *    temporaire (succes/erreur) apres une action. Alimente par
 *    l'evenement DOM `wh-toast` — que htmx declenche automatiquement pour
 *    toute cle presente dans l'en-tete de reponse `HX-Trigger` (mecanisme
 *    deja supporte nativement par htmx, aucune bibliotheque
 *    supplementaire). Cote Django, AUCUNE vue de ce chantier n'emet
 *    encore cet en-tete (verifie par audit : aucun `HX-Trigger` existant) —
 *    c'est documente ici comme une extension mineure prete a l'emploi :
 *    une vue peut faire
 *        response["HX-Trigger"] = json.dumps({"wh-toast": {"message": "...", "level": "success"}})
 *    pour declencher un toast, sans modifier ce fichier ni base.html.
 *
 * 4. `menuGroup(key)` : accordeon des groupes de la sidebar "Modules
 *    metier" (chantier "accordeon RBAC"). Chaque groupe est independant
 *    des autres (jamais un accordeon strict). L'etat ouvert/ferme est
 *    persiste dans localStorage (chaque navigation dans cette appli
 *    declenche un rechargement de page complet — sans persistance, l'etat
 *    Alpine en memoire serait perdu a chaque clic sur un lien, ce qui
 *    reintroduirait la friction que la decision "toujours visible" (cf.
 *    chantier E3) avait justement supprimee). En complement : le groupe
 *    contenant le lien correspondant a la page actuellement affichee
 *    s'ouvre automatiquement au chargement (jamais ecrit dans
 *    localStorage — c'est une consequence de la page courante, pas un
 *    choix persistant de l'utilisateur), sans jamais refermer un autre
 *    groupe deja ouvert manuellement.
 */
function readMenuGroupState(key) {
  try {
    return window.localStorage.getItem(`wh-menu-group-${key}`) === "1";
  } catch (e) {
    return false;
  }
}

function writeMenuGroupState(key, open) {
  try {
    window.localStorage.setItem(`wh-menu-group-${key}`, open ? "1" : "0");
  } catch (e) {
    /* localStorage indisponible (navigation privee, desactive) — l'etat
     * ne persiste simplement pas, jamais d'exception qui casserait le
     * rendu de la sidebar. */
  }
}

function menuGroupContainsCurrentPage(el) {
  const path = window.location.pathname;
  const links = el.querySelectorAll("a[href]");
  for (const link of links) {
    const href = link.getAttribute("href");
    if (href && href !== "#" && path.startsWith(href)) return true;
  }
  return false;
}

document.addEventListener("alpine:init", () => {
  Alpine.data("menuGroup", (key) => ({
    key,
    open: false,
    init() {
      this.open = readMenuGroupState(this.key) || menuGroupContainsCurrentPage(this.$el);
    },
    toggle() {
      this.open = !this.open;
      writeMenuGroupState(this.key, this.open);
    },
  }));

  Alpine.data("whModal", (initiallyOpen = false) => ({
    open: initiallyOpen,
    show() {
      this.open = true;
    },
    hide() {
      this.open = false;
    },
  }));

  Alpine.store("confirmDialog", {
    open: false,
    message: "",
    _resolve: null,
    ask(message) {
      this.message = message;
      this.open = true;
      return new Promise((resolve) => {
        this._resolve = resolve;
      });
    },
    confirm() {
      this.open = false;
      if (this._resolve) this._resolve(true);
      this._resolve = null;
    },
    cancel() {
      this.open = false;
      if (this._resolve) this._resolve(false);
      this._resolve = null;
    },
  });

  Alpine.store("toast", {
    items: [],
    push(message, level) {
      const id = `${Date.now()}-${Math.random()}`;
      this.items.push({ id, message, level: level || "success" });
      setTimeout(() => this.remove(id), 5000);
    },
    remove(id) {
      this.items = this.items.filter((item) => item.id !== id);
    },
  });
});

document.body.addEventListener("htmx:confirm", (event) => {
  if (!event.detail || !event.detail.question) return;
  event.preventDefault();
  Alpine.store("confirmDialog")
    .ask(event.detail.question)
    .then((confirmed) => {
      if (confirmed) event.detail.issueRequest(true);
    });
});

document.body.addEventListener("wh-toast", (event) => {
  const detail = event.detail || {};
  if (!detail.message) return;
  Alpine.store("toast").push(detail.message, detail.level);
});

/*
 * Fil d'ariane calcule cote client (chantier UI signale par l'utilisateur
 * apres test reel de l'interface). Zero modification des ~200 templates :
 * derive uniquement de deux sources deja presentes sur chaque page rendue
 * via base.html — le lien de la sidebar dont le href est le prefixe le
 * plus long de location.pathname (miette "Module") et le texte de
 * `.page-head h1` (miette "Page", ajoutee seulement si distincte du
 * libelle du module). Toujours en tete : "Accueil" vers /dashboard/.
 * Purement derive du DOM deja rendu — un ecran sans lien sidebar
 * correspondant ni `.page-head h1` affiche seulement "Accueil", jamais une
 * miette cassee/vide.
 */
function buildBreadcrumb() {
  const container = document.querySelector(".crumbs");
  if (!container) return;

  const path = window.location.pathname;
  const links = Array.from(document.querySelectorAll(".app-menu a[href]"));
  let bestMatch = null;
  for (const link of links) {
    const href = link.getAttribute("href");
    if (!href || href === "/" || href === "#") continue;
    if (path.startsWith(href) && (!bestMatch || href.length > bestMatch.href.length)) {
      const label = Array.from(link.childNodes)
        .filter((node) => node.nodeType === Node.TEXT_NODE)
        .map((node) => node.textContent.trim())
        .join(" ")
        .trim();
      if (label) bestMatch = { href, label };
    }
  }

  const crumbs = [{ href: "/dashboard/", label: container.dataset.home || "Accueil" }];
  if (bestMatch) crumbs.push({ href: bestMatch.href, label: bestMatch.label });

  const pageHeading = document.querySelector(".page-head h1");
  if (pageHeading) {
    const pageLabel = pageHeading.textContent.trim();
    if (pageLabel && (!bestMatch || pageLabel !== bestMatch.label)) {
      crumbs.push({ href: null, label: pageLabel });
    }
  }

  container.textContent = "";
  crumbs.forEach((crumb, index) => {
    if (index > 0) {
      const sep = document.createElement("span");
      sep.className = "crumb-sep";
      sep.setAttribute("aria-hidden", "true");
      sep.textContent = "›";
      container.appendChild(sep);
    }
    const isLast = index === crumbs.length - 1;
    if (crumb.href && !isLast) {
      const a = document.createElement("a");
      a.href = crumb.href;
      a.textContent = crumb.label;
      container.appendChild(a);
    } else {
      const span = document.createElement("span");
      span.className = "crumb-current";
      span.textContent = crumb.label;
      container.appendChild(span);
    }
  });
}

document.addEventListener("DOMContentLoaded", buildBreadcrumb);
