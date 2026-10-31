/* Kaléido — recherche et filtres de la mosaïque.
   Amélioration progressive : sans JavaScript, la liste complète reste lisible
   et les outils restent masqués. */
(function () {
    var outils = document.querySelector(".outils");
    var cartes = Array.prototype.slice.call(document.querySelectorAll(".mosaique .carte"));
    if (!outils || !cartes.length) return;
    outils.hidden = false;

    var champ = outils.querySelector("input[type=search]");
    var boutons = Array.prototype.slice.call(outils.querySelectorAll(".filtres button"));
    var aucun = document.querySelector(".aucun");
    var nature = "";

    function normaliser(texte) {
        return texte.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/œ/g, "oe");
    }

    function appliquer() {
        var mots = normaliser(champ.value).split(/\s+/).filter(Boolean);
        var visibles = 0;
        cartes.forEach(function (carte) {
            var texte = carte.getAttribute("data-recherche");
            var ok = (!nature || carte.getAttribute("data-nature") === nature)
                && mots.every(function (m) { return texte.indexOf(m) !== -1; });
            carte.hidden = !ok;
            if (ok) visibles++;
        });
        if (aucun) aucun.hidden = visibles > 0;
    }

    boutons.forEach(function (bouton) {
        bouton.addEventListener("click", function () {
            nature = bouton.getAttribute("data-nature") || "";
            boutons.forEach(function (b) { b.setAttribute("aria-pressed", b === bouton ? "true" : "false"); });
            appliquer();
        });
    });
    champ.addEventListener("input", appliquer);
})();
