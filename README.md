# Kaléido

Cahier de culture : des fiches sur des œuvres, des lieux, des personnes et des notions. « Ce qui m'a arrêté en chemin, et ce que j'en ai compris. »

Site frère d'Aiôn, Acta, Silva et Popote (nicolaguel.fr). La base technique est une copie adaptée du build d'Aiôn.

## Structure

- `fiches/` — une fiche par fichier Markdown avec en-tête YAML (`fiches/<slug>.md`)
- `static/` — feuille de style, polices, images
- `outils/importer_image.py` — importe une illustration (WebP en deux tailles + `illustrations.json`)
- `outils/controle_fiche.py` — contrôle mécanique d'une fiche (en-tête, structure, marqueurs, liens, image)
- `build.py` — transforme les fiches en HTML dans `public/`

## Règles de publication

- Une fiche n'est publiée que si son en-tête porte `publie: oui`. Seul Nicolas le décide.
- Le build échoue si une fiche publiée contient un marqueur `<!-- À VÉRIFIER` ou n'a pas ses champs obligatoires.
- `python3 build.py --brouillons` : aperçu local qui inclut les brouillons (le site produit est alors noindex).
- Tant que `EN_CONCEPTION = True` dans `build.py`, le site est noindex.

## Commandes

    pip install -r requirements.txt
    python3 outils/controle_fiche.py fiches/<slug>.md
    python3 build.py

## Déploiement (Cloudflare)

- Commande de build : `pip install -r requirements.txt && python3 build.py`
- Dossier de sortie : `public`
- Adresse prévue : https://kaleido.nicolaguel.fr (à confirmer)

## Écriture des fiches

Les fiches sont rédigées par GPT sur commande, contrôlées par Claude, validées par Nicolas. Le brief de rédaction et les commandes sont dans Google Drive › Témoins › Kaleido.
