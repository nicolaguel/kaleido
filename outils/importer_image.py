"""Importe une illustration dans le site.

Convertit une image source (JPEG, PNG…) en deux versions WebP, de 800 et
1400 pixels de large, dans static/images/, et note ses proportions dans
illustrations.json pour que le build réserve la bonne place à l'image.

Usage : python3 outils/importer_image.py chemin/vers/source.jpg nom-court
"""

import json
import sys
from pathlib import Path

from PIL import Image

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "static" / "images"
MANIFESTE = RACINE / "illustrations.json"
LARGEURS = (800, 1400)


def importer(source: Path, nom: str) -> None:
    DOSSIER.mkdir(parents=True, exist_ok=True)
    image = Image.open(source)
    image = image.convert("RGB")
    largeur, hauteur = image.size
    for cible in LARGEURS:
        l = min(cible, largeur)
        h = round(hauteur * l / largeur)
        copie = image.resize((l, h), Image.LANCZOS)
        copie.save(DOSSIER / f"{nom}-{cible}.webp", "WEBP", quality=82, method=6)
    manifeste = json.loads(MANIFESTE.read_text()) if MANIFESTE.exists() else {}
    manifeste[nom] = {"largeur": largeur, "hauteur": hauteur}
    MANIFESTE.write_text(json.dumps(manifeste, indent=2, ensure_ascii=False) + "\n")
    print(f"{nom} : {largeur}×{hauteur}, versions {LARGEURS} écrites")


if __name__ == "__main__":
    importer(Path(sys.argv[1]), sys.argv[2])
