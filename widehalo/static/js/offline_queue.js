/*
 * File d'attente de soumissions hors-ligne -- Sprint 10 (L6 Personnalisation
 * & offline, cf. docs/planning/2026-refonte-ux-sprints.md). Amelioration
 * progressive posee par-dessus des formulaires HTML natifs : sans ce
 * script (JS desactive), un formulaire soumis hors connexion echoue
 * normalement (erreur reseau du navigateur) -- comportement honnete, deja
 * coherent avec la discipline "coeur applicatif fonctionne sans JS" du
 * reste de ce chantier (cf. profile.html, set_language_view...). Ce
 * script se contente d'intercepter, uniquement quand `navigator.onLine`
 * est faux, la soumission des <form method="post"> du site, de la
 * stocker dans localStorage, puis de la rejouer au retour du reseau
 * (evenement `online`).
 *
 * Volontairement generique (branché sur tout <form>, pas d'integration
 * ecran par ecran) et volontairement simple (un tableau JSON dans
 * localStorage, pas d'IndexedDB) -- proportionne aux 6 JT du sprint.
 * Ne gere PAS les formulaires multipart (upload de fichier) : les champs
 * fichier ne sont pas serialisables en JSON, ces formulaires echouent donc
 * normalement hors-ligne, comme sans ce script -- jamais silencieusement
 * ignores.
 */
(function () {
  "use strict";

  var STORAGE_KEY = "wh-offline-queue";

  function readQueue() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : [];
    } catch (e) {
      return [];
    }
  }

  function writeQueue(queue) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(queue));
    } catch (e) {
      /* quota localStorage depasse ou indisponible (navigation privee) :
         la file ne persiste pas pour cette soumission, mais l'echec reste
         visible via le message affiche par showOfflineNotice(). */
    }
  }

  function showNotice(message, level) {
    var container = document.querySelector(".wh-toast-container");
    if (!container) {
      // Pas de conteneur de toasts sur cette page (ecrans hors base.html) :
      // repli minimal mais toujours visible, jamais un simple console.log
      // silencieux -- l'utilisateur doit voir la confirmation demandee.
      window.alert(message);
      return;
    }
    var toast = document.createElement("div");
    toast.className = "wh-toast wh-toast-" + (level || "success");
    toast.textContent = message;
    container.appendChild(toast);
    window.setTimeout(function () {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 6000);
  }

  function isMultipart(form) {
    var enctype = (form.getAttribute("enctype") || "").toLowerCase();
    return enctype.indexOf("multipart") !== -1 || form.querySelector('input[type="file"]') !== null;
  }

  function queueSubmission(form) {
    var formData = new FormData(form);
    var fields = [];
    formData.forEach(function (value, key) {
      fields.push([key, String(value)]);
    });
    var queue = readQueue();
    queue.push({
      method: (form.getAttribute("method") || "post").toUpperCase(),
      action: form.getAttribute("action") || window.location.pathname,
      fields: fields,
      queued_at: new Date().toISOString(),
    });
    writeQueue(queue);
  }

  function flushQueue() {
    var queue = readQueue();
    if (queue.length === 0) {
      return;
    }
    var remaining = [];
    var failures = 0;
    var pending = queue.map(function (entry) {
      var body = new URLSearchParams();
      entry.fields.forEach(function (pair) {
        body.append(pair[0], pair[1]);
      });
      return fetch(entry.action, { method: entry.method, body: body, credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok) {
            throw new Error("HTTP " + response.status);
          }
        })
        .catch(function () {
          failures += 1;
          remaining.push(entry);
        });
    });
    Promise.all(pending).then(function () {
      writeQueue(remaining);
      var sent = queue.length - remaining.length;
      if (sent > 0) {
        showNotice(
          sent === 1
            ? "1 formulaire en attente envoyé avec succès."
            : sent + " formulaires en attente envoyés avec succès.",
          "success"
        );
      }
      if (failures > 0) {
        showNotice(
          failures === 1
            ? "1 formulaire en attente n’a pas pu être envoyé — nouvelle tentative au prochain retour réseau."
            : failures + " formulaires en attente n’ont pas pu être envoyés — nouvelle tentative au prochain retour réseau.",
          "error"
        );
      }
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) {
      return;
    }
    var method = (form.getAttribute("method") || "get").toLowerCase();
    if (method !== "post") {
      return; // jamais de mise en file d'une navigation GET.
    }
    if (navigator.onLine) {
      return; // en ligne : comportement natif, aucune interception.
    }
    if (isMultipart(form)) {
      return; // upload de fichier : non serialisable, echec natif honnete.
    }
    event.preventDefault();
    queueSubmission(form);
    showNotice(
      "Enregistré hors connexion — sera envoyé automatiquement au retour du réseau.",
      "success"
    );
  });

  window.addEventListener("online", flushQueue);

  // Au chargement (page rouverte apres une periode hors-ligne, reseau deja
  // revenu) : tente aussi un flush immediat plutot que d'attendre un futur
  // evenement `online` qui ne se declenchera plus si la connexion est deja
  // la.
  if (navigator.onLine) {
    flushQueue();
  }
})();
