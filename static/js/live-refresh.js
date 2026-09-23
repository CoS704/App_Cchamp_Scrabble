/* Actualisation automatique des tableaux de bord (§ mise à jour sans rechargement).
 *
 * Remplace le contenu de #dashboard-content par celui de la même page
 * rechargée en arrière-plan. Robuste face aux cas rencontrés en production :
 *  - onglet en arrière-plan / « onglet en veille » : les minuteurs y sont
 *    ralentis ou gelés, donc on actualise aussi dès que l'onglet redevient
 *    visible, reprend le focus ou retrouve le réseau ;
 *  - cache HTTP/proxy : paramètre unique + no-store à chaque requête ;
 *  - session expirée : la réponse n'a plus le conteneur, on le signale au lieu
 *    d'échouer en silence ;
 *  - une erreur dans le rendu des graphiques ne doit jamais arrêter le cycle.
 */
(function () {
  const CONTAINER_ID = "dashboard-content";
  let inFlight = false;

  function setStatus(text) {
    const el = document.getElementById("last-updated");
    if (el) el.textContent = text;
  }

  async function refresh(onSwap) {
    if (inFlight) return;
    inFlight = true;
    try {
      const url = new URL(window.location.href);
      url.searchParams.set("_", Date.now().toString());
      const resp = await fetch(url.toString(), {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        cache: "no-store",
        credentials: "same-origin",
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const html = await resp.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const fresh = doc.getElementById(CONTAINER_ID);
      const current = document.getElementById(CONTAINER_ID);
      if (!fresh || !current) {
        setStatus("session expirée — rechargez la page");
        return;
      }
      current.innerHTML = fresh.innerHTML;
      try {
        if (onSwap) onSwap();
      } catch (e) {
        console.error("Rendu des graphiques impossible :", e);
      }
      setStatus(new Date().toLocaleTimeString("fr-FR"));
    } catch (e) {
      setStatus("actualisation impossible, nouvel essai…");
    } finally {
      inFlight = false;
    }
  }

  window.startLiveRefresh = function (options) {
    const opts = options || {};
    const run = () => refresh(opts.onSwap);
    setInterval(run, opts.intervalMs || 20000);
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") run();
    });
    window.addEventListener("focus", run);
    window.addEventListener("online", run);
    const button = document.getElementById("refresh-now");
    if (button) button.addEventListener("click", run);
    return run;
  };
})();
