"""Kaléido — contrôle mécanique d'une fiche avant intégration.

Vérifie l'en-tête YAML, la structure du corps, les marqueurs « À VÉRIFIER »,
les liens [[slug]] et le bloc image. Ne vérifie PAS les faits : c'est le rôle
de la relecture humaine ou du contrôle par échantillon.

Usage :
    python3 controle_fiche.py fiche.md [autre.md ...] [--existantes dossier/]

--existantes : dossier de fiches déjà intégrées (un fichier .md par fiche,
nom = slug), pour savoir quels liens [[slug]] pointent vers une fiche réelle.
Code de sortie : 1 s'il y a au moins une erreur, 0 sinon.
"""

import re
import sys
from pathlib import Path

import yaml

NATURES = {"œuvre", "personne", "lieu", "notion", "panorama"}
FORMATS = {"brève", "complète"}
SLUG = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
LIEN_WIKI = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
MARQUEUR = re.compile(r"<!--\s*À VÉRIFIER", re.I)
URL_NUE = re.compile(r"(?<![(<\[])https?://[^\s)>\]]+")
CHAMPS_IMAGE = ("fichier", "source", "credit", "licence", "legende", "alt")
EXPRESSIONS_A_BANNIR = ("incontournable", "plongez", "il convient de noter",
                        "à noter que", "véritable bijou", "riche histoire")


def mots(texte: str) -> int:
    return len(re.findall(r"\w+", texte))


def sections(corps: str) -> list[tuple[str, str]]:
    """Liste (titre, texte) des sections de niveau 2, dans l'ordre."""
    morceaux = re.split(r"(?m)^## +(.+)$", corps)
    return [(morceaux[i].strip(), morceaux[i + 1]) for i in range(1, len(morceaux), 2)]


def controler(chemin: Path, existantes: set[str]) -> tuple[list[str], list[str]]:
    erreurs, avertissements = [], []
    texte = chemin.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", texte, re.S)
    if not m:
        return ["En-tête YAML manquant ou mal délimité (---)."], []
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        return [f"YAML invalide : {e}"], []
    corps = m.group(2)

    # --- en-tête
    for cle in ("titre", "slug", "nature", "chapo", "publie", "mise_a_jour"):
        if not meta.get(cle):
            erreurs.append(f"Champ obligatoire absent : {cle}")
    slug = str(meta.get("slug", ""))
    if slug and not SLUG.match(slug):
        erreurs.append(f"slug invalide (minuscules, chiffres, tirets, sans accent) : {slug}")
    nature = meta.get("nature")
    if nature and nature not in NATURES:
        erreurs.append(f"nature inconnue : {nature} (attendu : {', '.join(sorted(NATURES))})")
    fmt = meta.get("format")
    if nature != "panorama":
        if fmt not in FORMATS:
            erreurs.append(f"format absent ou inconnu : {fmt} (brève ou complète)")
    elif fmt:
        avertissements.append("Un panorama n'a pas de champ format.")
    if str(meta.get("publie")) not in ("non", "oui", "False", "True"):
        erreurs.append("publie doit valoir non ou oui.")
    if meta.get("publie") in ("oui", True):
        avertissements.append("publie vaut oui : seule la décision de Nicolas le permet.")
    chapo = str(meta.get("chapo", ""))
    if chapo and not 15 <= mots(chapo) <= 60:
        avertissements.append(f"chapo de {mots(chapo)} mots (visé : 15 à 60).")
    themes = meta.get("themes") or []
    if not (1 <= len(themes) <= 4):
        avertissements.append(f"{len(themes)} thème(s) (visé : 1 à 4).")

    # --- image
    image = meta.get("image")
    if image:
        for c in CHAMPS_IMAGE:
            if not (image or {}).get(c):
                erreurs.append(f"image : champ absent : {c}")
        src = str((image or {}).get("source", ""))
        if src and not src.startswith("https://commons.wikimedia.org/"):
            avertissements.append("image : la source n'est pas une page Wikimedia Commons.")
        if image.get("alt") and image.get("alt") == image.get("legende"):
            avertissements.append("image : alt identique à la légende ; l'alt décrit, la légende explique.")

    # --- corps
    marqueurs = [n for n, l in enumerate(texte.splitlines(), 1) if MARQUEUR.search(l)]
    if marqueurs:
        erreurs.append(f"{len(marqueurs)} marqueur(s) À VÉRIFIER (lignes {', '.join(map(str, marqueurs))}) : "
                       "bloquant pour la publication.")
    secs = sections(corps)
    titres = [t for t, _ in secs]
    if nature == "panorama":
        entrees = len(re.findall(r"(?m)^### ", corps))
        if entrees < 3:
            erreurs.append(f"panorama : {entrees} entrée(s) ### (minimum 3).")
    else:
        if not titres or titres[0] != "En bref":
            erreurs.append("La première section doit être « ## En bref ».")
        else:
            n = mots(secs[0][1])
            if not 150 <= n <= 350:
                erreurs.append(f"« En bref » de {n} mots (150 à 350 acceptés, 200 à 300 visés).")
            elif not 200 <= n <= 300:
                avertissements.append(f"« En bref » de {n} mots (200 à 300 visés).")
        total = mots(corps)
        if fmt == "brève" and total > 700:
            avertissements.append(f"Brève de {total} mots : plutôt une fiche complète ?")
        if fmt == "complète" and total < 500:
            avertissements.append(f"Complète de {total} mots : plutôt une brève ?")
        if fmt == "brève" and len(titres) > 4:
            avertissements.append("Une brève n'a normalement pas de sections de contenu au-delà d'En bref.")
    if "Sources" not in titres:
        erreurs.append("Section « ## Sources » absente.")
    elif titres[-1] != "Sources":
        avertissements.append("« Sources » devrait être la dernière section.")
    ordre = [t for t in titres if t in ("Pour aller plus loin", "Liens", "Sources")]
    if ordre != sorted(ordre, key=["Pour aller plus loin", "Liens", "Sources"].index):
        avertissements.append("Ordre attendu des sections finales : Pour aller plus loin, Liens, Sources.")
    for c in sorted(EXPRESSIONS_A_BANNIR):
        if c in texte.lower():
            avertissements.append(f"Formule à éviter : « {c} ».")

    # --- liens
    nues = URL_NUE.findall(corps)
    if nues:
        avertissements.append(f"{len(nues)} URL nue(s) : écrire [libellé](URL) pour qu'elles soient cliquables.")
    for cible in sorted(set(LIEN_WIKI.findall(corps))):
        cible = cible.strip()
        if existantes and cible not in existantes and cible != slug:
            avertissements.append(f"Lien [[{cible}]] vers une fiche inexistante (affiché « à venir »).")
        if cible == slug:
            erreurs.append("La fiche se cite elle-même.")
    return erreurs, avertissements


def main(argv: list[str]) -> int:
    existantes: set[str] = set()
    if "--existantes" in argv:
        i = argv.index("--existantes")
        dossier = Path(argv[i + 1])
        existantes = {p.stem for p in dossier.glob("*.md")}
        del argv[i:i + 2]
    fichiers = [Path(a) for a in argv]
    if not fichiers:
        print(__doc__)
        return 2
    code = 0
    for f in fichiers:
        erreurs, avertissements = controler(f, existantes)
        etat = "ERREUR" if erreurs else ("à surveiller" if avertissements else "OK")
        print(f"\n{f.name} — {etat}")
        for e in erreurs:
            print(f"  ✗ {e}")
        for a in avertissements:
            print(f"  ! {a}")
        code = 1 if erreurs else code
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
