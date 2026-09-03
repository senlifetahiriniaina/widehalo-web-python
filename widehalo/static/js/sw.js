/*
 * Service Worker minimal -- Sprint 10 (L6 Personnalisation & offline, cf.
 * docs/planning/2026-refonte-ux-sprints.md). Portee VOLONTAIREMENT etroite
 * et honnete : cache-first sur les assets statiques (CSS/JS/polices/icones)
 * plus le "shell" HTML de quelques ecrans d'entree (launchpad/dashboard),
 * jamais une tentative de mettre l'application dynamique entiere hors-ligne
 * -- toute page metier non deja visitee (donc non en cache) reste
 * inatteignable hors connexion, ce qui est le comportement honnete pour un
 * ERP dont l'essentiel des ecrans depend de donnees serveur toujours a
 * jour (stocks, soldes, statuts...), jamais d'un instantane fige.
 */

const CACHE_NAME = "widehalo-shell-v1";

// Assets statiques + shell HTML mis en cache au premier chargement --
// jamais une liste exhaustive de toutes les pages de l'application.
const SHELL_URLS = [
  "/static/css/tokens.css",
  "/static/css/fonts.css",
  "/static/css/app.css",
  "/static/css/tailwind.css",
  "/static/js/ui_patterns.js",
  "/static/js/offline_queue.js",
  "/static/manifest.json",
  "/static/img/logo-mark.svg",
  "/dashboard/",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      // addAll echouerait entierement si une seule URL de la liste est
      // indisponible (ex. utilisateur non connecte pour /dashboard/) --
      // on met donc chaque URL en cache individuellement, en ignorant les
      // echecs isoles plutot que de faire echouer toute l'installation.
      Promise.all(
        SHELL_URLS.map((url) =>
          cache.add(url).catch(() => {
            /* URL indisponible au moment de l'installation : ignoree,
               sera mise en cache a la premiere requete reussie (fetch
               handler ci-dessous) si elle finit par etre visitee. */
          })
        )
      )
    )
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

function isStaticAsset(url) {
  return url.pathname.startsWith("/static/");
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") {
    return; // jamais de cache-first sur une ecriture (POST/PUT/DELETE...).
  }
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) {
    return;
  }

  // Cache-first pour les assets statiques : rapides, versionnes par
  // deploiement, sans risque de servir une donnee metier perimee.
  if (isStaticAsset(url)) {
    event.respondWith(
      caches.match(request).then(
        (cached) =>
          cached ||
          fetch(request).then((response) => {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
            return response;
          })
      )
    );
    return;
  }

  // Pour le reste (ecrans applicatifs dynamiques) : reseau d'abord,
  // secours cache SEULEMENT pour les quelques URL de shell explicitement
  // mises en cache ci-dessus -- jamais un fallback generique qui donnerait
  // l'illusion trompeuse que tout l'ERP fonctionne hors-ligne.
  if (SHELL_URLS.includes(url.pathname)) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          return response;
        })
        .catch(() => caches.match(request))
    );
  }
});
