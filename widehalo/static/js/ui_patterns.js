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
 */
document.addEventListener("alpine:init", () => {
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
