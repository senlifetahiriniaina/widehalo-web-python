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
 *
 * 5. `lineItems(initial)` : lignes de saisie dynamiques (chantier refonte
 *    creation devis/commande, DT6) — premier usage d'Alpine `x-for` sur
 *    des CHAMPS DE SAISIE dans ce depot (le seul precedent, la liste de
 *    toasts de `templates/base.html`, est en lecture seule). Le tableau
 *    `lines` est rendu cote gabarit avec des noms de champs indexes
 *    (`:name="'variant_id_' + index"`, etc. — jamais un blob JSON cache,
 *    la vue Django lit ces champs avec une simple boucle `while`, cf.
 *    `apps.sales.views._parse_lines_from_post`). Chaque ligne porte une
 *    `key` = compteur incremental JAMAIS reutilise (pas l'index) pour que
 *    `:key` Alpine reste stable meme apres suppression d'une ligne
 *    intermediaire — reutiliser l'index re-attribuerait la `key` d'une
 *    ligne supprimee a la ligne suivante, ce qu'Alpine confondrait avec
 *    "meme ligne, contenu modifie" au lieu de "ligne differente".
 *    `lineTotal(line)` est un APERCU client-side pur (`qty * unit_price`),
 *    jamais autoritaire — `null` tant que `unit_price` n'est pas
 *    renseigne manuellement (le vrai `subtotal` vient de la cascade de
 *    prix cote serveur, connu seulement apres creation).
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

  Alpine.data("tabs", (defaultTab) => ({
    active: defaultTab,
    select(tab) {
      this.active = tab;
    },
    isActive(tab) {
      return this.active === tab;
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

  /* SAL-7 — brouillon de devis/commande sauvegarde automatiquement.
   *
   * Avant ce lot, `lines` ne vivait qu'en memoire Alpine et `init()`
   * repartait d'une ligne vierge a CHAQUE chargement : une fermeture
   * d'onglet, un rechargement, une coupure, et vingt lignes saisies a la
   * main etaient perdues. `offline_queue.js` ne couvre pas ce cas — il
   * n'intercepte qu'a la SOUMISSION, et seulement hors ligne.
   *
   * Il y avait pire, et en ligne : la vue `quotation_create` re-rend le
   * formulaire VIDE apres une erreur de validation (aucun `value=` dans le
   * gabarit, `lines` reinitialise). Une simple date mal saisie faisait donc
   * deja tout perdre, sans aucune panne. Le brouillon repare les deux.
   *
   * `draftKey` separe les brouillons du devis et de la commande : les deux
   * ecrans partagent ce composant, un compteur commun melangerait les
   * lignes de l'un dans l'autre. Sans cle, aucune persistance — le
   * composant reste utilisable ailleurs sans effet de bord.
   */
  Alpine.data("lineItems", (draftKey) => ({
    lines: [],
    _nextKey: 0,
    draftRestored: false,
    _draftKey: draftKey ? "wh-draft-" + draftKey : "",

    _root: null,
    _suppressPersist: false,

    init() {
      /* `$el` est une magie Alpine resolue AU MOMENT DE L'ACCES : appelee
       * depuis un `@click` situe dans un `<template x-if>` (la banniere de
       * brouillon restaure), `this.$el` designe le BOUTON, pas le
       * formulaire. `discardDraft()` ne nettoyait donc rien — les lignes
       * semblaient videes, mais par la reinitialisation de `lines`, tandis
       * que les champs d'en-tete gardaient leur valeur. Un test e2e l'a
       * trouve ; la racine est desormais capturee une fois ici, ou `$el`
       * designe bien le formulaire. */
      this._root = this.$el;
      const draft = this._readDraft();
      /* Distinguer « le POST precedent a echoue » de « il a reussi ».
       * En cas de succes le navigateur part vers la fiche : cette page
       * n'est pas rechargee, et le brouillon marque `submitted` doit etre
       * jete au prochain « Nouveau devis ». En cas d'echec le serveur
       * re-rend CETTE page avec une erreur : le brouillon doit alors etre
       * restaure, c'est precisement le travail que la vue perdait. Le
       * gabarit expose l'etat d'erreur via `data-submit-failed`. */
      const submitFailed = this._root.dataset.submitFailed === "true";
      if (draft && draft.submitted && !submitFailed) {
        this._clearDraft();
      } else if (draft && Array.isArray(draft.lines) && draft.lines.length) {
        this.lines = draft.lines;
        this._nextKey = this.lines.length;
        this.lines.forEach((line, index) => { line.key = index; });
        this._restoreFields(draft.fields || {});
        this.draftRestored = true;
      }
      if (!this.lines.length) this.addLine();

      if (this._draftKey) {
        this.$watch("lines", () => this._writeDraft(false));
        /* Les champs d'en-tete ne sont pas geres par Alpine : on ecoute
         * l'evenement de saisie du formulaire plutot que de les declarer
         * un par un, ce qui obligerait a modifier ce composant a chaque
         * champ ajoute au gabarit. */
        this._root.addEventListener("input", () => this._writeDraft(false));
        this._root.addEventListener("change", () => this._writeDraft(false));
        this._root.addEventListener("submit", () => this._writeDraft(true));
      }
    },

    /* Les champs a NE PAS persister, et pourquoi :
     *  - `csrfmiddlewaretoken` : lie a la session, rejoue plus tard il
     *    serait invalide, et l'ecrire dans le stockage du navigateur
     *    serait sortir un secret de session sans raison ;
     *  - `q` : la boite de recherche du selecteur de tiers. La restaurer
     *    afficherait un texte de recherche sans relancer la recherche —
     *    un ecran qui ment sur son etat. */
    _skippedFields: ["csrfmiddlewaretoken", "q"],

    _isLineField(element) {
      /* Les champs de ligne sont deja portes par `lines`. Les dupliquer
       * dans `fields` les ferait diverger a la restauration : `_restore
       * Fields` ecrirait dans le DOM des valeurs qu'Alpine vient de
       * re-rendre depuis `lines`.
       *
       * Le test les detecte par leur POSITION (dans la table des lignes)
       * et non par un prefixe de nom : les noms reels sont `description_0`,
       * `qty_0`, `unit_price_0`, `variant_id_0` — un filtre par prefixe
       * devrait les enumerer tous et casserait au premier champ ajoute. */
      return Boolean(element.closest(".line-items-table"));
    },

    _formFields() {
      const fields = {};
      const elements = this._root.querySelectorAll("input[name], select[name], textarea[name]");
      elements.forEach((element) => {
        if (!element.name || this._skippedFields.indexOf(element.name) !== -1) return;
        if (this._isLineField(element)) return;
        fields[element.name] = element.value;
      });
      /* Le nom du tiers choisi vit dans un `<span>`, pas dans un champ :
       * le formulaire ne soumet que son UUID. Restaurer l'UUID sans le nom
       * donnerait un brouillon qui s'enregistre correctement mais qui
       * affiche un client vide — l'utilisateur croirait devoir le
       * re-choisir, et le re-choisirait peut-etre autre. */
      const display = this._root.querySelector(".wh-partner-picker-display");
      if (display) fields["__partner_display"] = display.textContent.trim();
      return fields;
    },

    _restoreFields(fields) {
      Object.keys(fields).forEach((name) => {
        if (name === "__partner_display") {
          const display = this._root.querySelector(".wh-partner-picker-display");
          if (display) display.textContent = fields[name];
          return;
        }
        const element = this._root.querySelector("[name='" + name + "']");
        if (element && !this._isLineField(element)) {
          element.value = fields[name];
          element.dispatchEvent(new Event("change", { bubbles: true }));
        }
      });
    },

    _readDraft() {
      if (!this._draftKey) return null;
      try {
        const raw = window.localStorage.getItem(this._draftKey);
        return raw ? JSON.parse(raw) : null;
      } catch (e) {
        /* Navigation privee ou stockage indisponible : pas de brouillon,
         * jamais une page cassee. Meme tolerance que `offline_queue.js`. */
        return null;
      }
    },

    _writeDraft(submitted) {
      if (!this._draftKey || this._suppressPersist) return;
      try {
        window.localStorage.setItem(
          this._draftKey,
          JSON.stringify({
            lines: this.lines,
            fields: this._formFields(),
            submitted: Boolean(submitted),
            saved_at: Date.now(),
          })
        );
      } catch (e) {
        /* Quota depasse : le brouillon ne persiste pas cette fois-ci. On
         * n'affiche rien — contrairement a `offline_queue.js`, ou l'echec
         * signifiait une soumission perdue, ici la saisie en cours reste
         * intacte a l'ecran. Alerter sur chaque frappe serait du bruit. */
      }
    },

    _clearDraft() {
      if (!this._draftKey) return;
      try {
        window.localStorage.removeItem(this._draftKey);
      } catch (e) {
        /* idem */
      }
    },

    discardDraft() {
      /* « Repartir de zero » doit ne RIEN laisser derriere. Sans ce
       * verrou, la reinitialisation de `lines` juste en dessous declenche
       * le `$watch`, qui reecrit aussitot un brouillon (vide, donc inerte
       * a la restauration — mais la cle survit, et une cle qui survit a un
       * effacement demande est une promesse non tenue). */
      this._suppressPersist = true;
      this.lines = [];
      this._nextKey = 0;
      this.addLine();
      this.draftRestored = false;
      this._root.querySelectorAll("input[name], select[name], textarea[name]").forEach((element) => {
        if (!element.name || element.name === "csrfmiddlewaretoken") return;
        /* Les champs de ligne sont deja remis a zero par la
         * reinitialisation de `lines` juste au-dessus, qu'Alpine re-rend. */
        if (this._isLineField(element)) return;
        if (element.tagName === "SELECT") element.selectedIndex = 0;
        else element.value = "";
      });
      const display = this._root.querySelector(".wh-partner-picker-display");
      if (display) display.textContent = "";
      /* Le `$watch` d'Alpine est ASYNCHRONE : il s'execute au tick suivant.
       * Lever le verrou et effacer ici, de facon synchrone, laissait le
       * watch reecrire un brouillon juste apres — la cle survivait a
       * l'effacement demande. On attend donc que la reactivite ait fini. */
      this.$nextTick(() => {
        this._suppressPersist = false;
        this._clearDraft();
      });
    },

    _makeLine() {
      return { key: this._nextKey++, variant_id: "", description: "", qty: "1", unit_price: "" };
    },
    addLine() {
      this.lines.push(this._makeLine());
    },
    removeLine(index) {
      if (this.lines.length <= 1) return;
      this.lines.splice(index, 1);
    },
    lineTotal(line) {
      if (line.unit_price === "" || line.unit_price === null) return null;
      const qty = parseFloat(line.qty);
      const unitPrice = parseFloat(line.unit_price);
      if (Number.isNaN(qty) || Number.isNaN(unitPrice)) return null;
      return (qty * unitPrice).toFixed(2);
    },
  }));

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
 * Picker partenaire reutilisable (`components/_partner_picker.html`,
 * UXR3) : deux gestionnaires vanilla JS delegues au document, pour que
 * le composant fonctionne quel que soit le nombre d'instances presentes
 * sur une meme page, sans configuration cote appelant au-dela des ids
 * `field_id`/`display_id` passes a l'include.
 *
 * 1. Activation d'un resultat de recherche (`<button data-partner-id
 *    data-partner-name>`, fragment rendu par
 *    `apps/partners/views.py::partner_instant_picker`) : peuple le champ
 *    cache et le texte affiche identifies par les attributs
 *    `data-field-id`/`data-display-id` du conteneur `<ul
 *    data-partner-picker-results>` le plus proche.
 * 2. Evenement `wh-partner-created` (declenche par htmx via l'en-tete
 *    `HX-Trigger` que renvoie `partner_create_wizard` en mode
 *    `?embed=1` a l'issue de l'etape 2) : meme peuplement, puis fermeture
 *    de la `whModal()` englobante (`data-wh-partner-picker-modal`) —
 *    identifiee en remontant depuis `event.target` (l'evenement HX-Trigger
 *    est dispatche sur l'element swappe par htmx, qui bouillonne jusqu'au
 *    document en traversant necessairement le wrapper de la modale).
 */
// Le resultat etant un `<button>` (L16/SAL-1), ce meme gestionnaire couvre
// le clic ET l'activation au clavier (Entree/Espace) : le navigateur emet
// un `click` dans les deux cas, aucun gestionnaire de touche a ajouter.
document.body.addEventListener("click", (event) => {
  const item = event.target.closest("[data-partner-id]");
  if (!item) return;
  const container = item.closest("[data-partner-picker-results]");
  if (!container) return;
  populatePartnerPicker(container.dataset.fieldId, container.dataset.displayId, {
    partner_id: item.dataset.partnerId,
    partner_name: item.dataset.partnerName,
  });
  container.innerHTML = "";
});

document.body.addEventListener("wh-partner-created", (event) => {
  const detail = event.detail || {};
  const modal = event.target.closest("[data-wh-partner-picker-modal]");
  if (!modal) return;
  populatePartnerPicker(modal.dataset.fieldId, modal.dataset.displayId, detail);
  if (window.Alpine && typeof Alpine.$data === "function") {
    const scope = Alpine.$data(modal);
    if (scope && typeof scope.hide === "function") scope.hide();
  }
});

function populatePartnerPicker(fieldId, displayId, detail) {
  if (fieldId && detail.partner_id) {
    const field = document.getElementById(fieldId);
    if (field) field.value = detail.partner_id;
  }
  if (displayId && detail.partner_name) {
    const display = document.getElementById(displayId);
    if (display) display.textContent = detail.partner_name;
  }
}

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
