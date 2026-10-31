"""Kaléido — build du site statique.

Lit les fiches Markdown (avec en-tête YAML) dans fiches/, produit le site HTML
dans public/. Dépendances : markdown, PyYAML.

Usage :
    python3 build.py                 # site public : seules les fiches « publie: oui »
    python3 build.py --brouillons    # aperçu local : inclut les fiches « publie: non »
                                     # (le site produit est alors noindex)

Règles de publication :
- une fiche n'est publiée que si son en-tête porte « publie: oui » ;
- le build échoue si une fiche publiée contient un marqueur « <!-- À VÉRIFIER » ;
- le build échoue si une fiche publiée n'a pas les champs obligatoires.
"""

import html
import json
import re
import shutil
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

import markdown
import yaml

RACINE = Path(__file__).parent
CONTENUS = RACINE / "fiches"
STATIC = RACINE / "static"
SORTIE = RACINE / "public"
MANIFESTE_IMAGES = RACINE / "illustrations.json"

NOM_SITE = "Kaléido"
URL_SITE = "https://kaleido.nicolaguel.fr"
AUTEUR = "Nicolas Guelle"
DEVISE = "Un cahier de cultures, glanées au fil des rencontres."
# Tant que le site est en conception : non indexé par les moteurs.
EN_CONCEPTION = True

PREFIXE = "fiches"
NATURES = {  # nature -> (singulier, pluriel)
    "œuvre": ("Œuvre", "Œuvres"),
    "personne": ("Personne", "Personnes"),
    "lieu": ("Lieu", "Lieux"),
    "notion": ("Notion", "Notions"),
    "panorama": ("Panorama", "Panoramas"),
}
OBLIGATOIRES = ("titre", "nature", "chapo", "mise_a_jour")
MARQUEUR = re.compile(r"<!--\s*À VÉRIFIER", re.I)

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]

SECTION_EN_BREF = "en-bref"
SECTIONS_ANNEXES = {"pour-aller-plus-loin", "liens", "sources"}

BROUILLONS = "--brouillons" in sys.argv


# ---------------------------------------------------------------- outils

def slugifier(valeur: str, separateur: str = "-") -> str:
    v = unicodedata.normalize("NFKD", valeur).encode("ascii", "ignore").decode()
    v = re.sub(r"[^\w\s-]", "", v).strip().lower()
    return re.sub(r"[-\s]+", separateur, v)


def date_fr(d) -> str:
    if isinstance(d, date):
        jour = "1er" if d.day == 1 else str(d.day)
        return f"{jour} {MOIS[d.month - 1]} {d.year}"
    return str(d)


def iso(d) -> str:
    return d.isoformat() if isinstance(d, date) else str(d or "")


def typographie(texte: str) -> str:
    """Apostrophe typographique et espaces insécables de la ponctuation française."""
    texte = re.sub(r"(?<=\w)'(?=\w)", "\u2019", texte)
    texte = re.sub(r" ([:;?!»])", "\u202f\\1", texte)
    texte = re.sub(r"« ", "«\u202f", texte)
    texte = re.sub(r"\b(\d{1,2}|1er) (janvier|février|mars|avril|mai|juin|juillet|août|septembre|octobre|novembre|décembre)\b",
                   "\\1\u00a0\\2", texte)
    texte = re.sub(r"(?<=[^\W\d]) (\d{3,4})\b", "\u00a0\\1", texte)
    return texte


def italiques(texte: str) -> str:
    """*titre d'œuvre* -> <em>titre d'œuvre</em> dans les légendes."""
    return re.sub(r"\*([^*]+)\*", r"<em>\1</em>", texte)


def est_oui(valeur) -> bool:
    return valeur is True or str(valeur).strip().lower() == "oui"


# ---------------------------------------------------------------- contenus

def lire_fiche(chemin: Path) -> dict:
    texte = chemin.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", texte, re.S)
    if not m:
        raise ValueError(f"En-tête YAML manquant : {chemin}")
    meta = yaml.safe_load(m.group(1)) or {}
    meta["fichier"] = chemin.name
    meta["publie_ok"] = est_oui(meta.get("publie"))
    meta["marqueurs"] = [n for n, ligne in enumerate(texte.splitlines(), 1)
                         if MARQUEUR.search(ligne)]
    meta["corps_brut"] = m.group(2)
    meta.setdefault("slug", chemin.stem)
    return meta


def verifier_publiee(meta: dict) -> None:
    """Une fiche publiée doit être complète et sans marqueur « À VÉRIFIER »."""
    erreurs = [f"champ absent : {c}" for c in OBLIGATOIRES if not meta.get(c)]
    if meta.get("nature") and meta["nature"] not in NATURES:
        erreurs.append(f"nature inconnue : {meta['nature']}")
    if meta["marqueurs"]:
        erreurs.append("marqueur « À VÉRIFIER » aux lignes "
                       + ", ".join(map(str, meta["marqueurs"])))
    if erreurs:
        raise SystemExit(f"Fiche publiée refusée ({meta['fichier']}) : " + " ; ".join(erreurs))


def preparer(meta: dict) -> dict:
    meta["corps"] = typographie(meta["corps_brut"])
    for cle in ("titre", "chapo"):
        if meta.get(cle):
            meta[cle] = typographie(str(meta[cle]))
    prefixe_nature = NATURES.get(meta.get("nature"), ("Fiche", "Fiches"))
    meta["libelle"] = prefixe_nature[0]
    meta["classe"] = "nature-" + slugifier(str(meta.get("nature", "")).replace("œ", "oe"))
    meta["themes"] = [str(t) for t in (meta.get("themes") or [])]
    meta["url"] = f"/{PREFIXE}/{meta['slug']}/"
    meta["mots"] = len(re.findall(r"\w+", meta["corps"]))
    meta["minutes"] = max(1, round(meta["mots"] / 230))
    meta["cites"] = set(c.split("|")[0].strip()
                        for c in re.findall(r"\[\[([^\]]+)\]\]", meta["corps"]))
    return meta


def liens_wiki(texte: str, index: dict) -> str:
    """[[slug]] ou [[slug|libellé]] -> lien si la fiche existe, mention « à venir » sinon."""

    def remplacer(m):
        slug, _, libelle = m.group(1).partition("|")
        slug = slug.strip()
        page = index.get(slug)
        if page:
            return f"[{libelle.strip() or page['titre']}]({page['url']})"
        texte_lien = libelle.strip() or slug.replace("-", " ")
        if libelle:
            return texte_lien
        return f'<span class="a-venir" title="Fiche à venir">{texte_lien}</span>'

    return re.sub(r"\[\[([^\]]+)\]\]", remplacer, texte)


def liens_retour(page: dict, pages: list) -> list:
    """Les fiches qui citent cette fiche."""
    return [p for p in pages if p is not page and page["slug"] in p["cites"]]


def rendre_markdown(texte: str) -> str:
    md = markdown.Markdown(
        extensions=["tables", "toc", "sane_lists"],
        extension_configs={"toc": {"slugify": slugifier}},
    )
    return md.convert(texte)


def decouper_sections(corps_html: str) -> list:
    morceaux = re.split(r'(?=<h2 id=")', corps_html)
    sections = []
    for m in morceaux:
        t = re.match(r'<h2 id="([^"]+)">(.*?)</h2>', m, re.S)
        if t:
            sections.append({"id": t.group(1), "titre": t.group(2), "html": m})
        elif m.strip():
            sections.append({"id": None, "titre": None, "html": m})
    return sections


# ---------------------------------------------------------------- illustration

def illustration(page: dict, manifeste: dict) -> str:
    """Figure principale, si le bloc « image » est déclaré et l'image importée."""
    bloc = page.get("image") or {}
    nom = bloc.get("fichier")
    if not nom or nom not in manifeste:
        return ""
    dims = manifeste[nom]
    legende = typographie(str(bloc.get("legende", "")))
    credit = typographie(str(bloc.get("credit", "")))
    source = bloc.get("source", "")
    credit_html = html.escape(credit)
    if source:
        credit_html = f'<a href="{html.escape(source)}">{credit_html}</a>'
    classe = "illustration" if dims["largeur"] >= 1100 else "illustration etroite"
    return f"""<figure class="{classe}">
    <img src="/images/{nom}-1400.webp"
         srcset="/images/{nom}-800.webp 800w, /images/{nom}-1400.webp 1400w"
         sizes="(min-width: 72rem) 62rem, 100vw"
         width="{dims["largeur"]}" height="{dims["hauteur"]}"
         alt="{html.escape(str(bloc.get("alt", "")))}" decoding="async">
    <figcaption>{italiques(html.escape(legende))} <span class="credit">{credit_html}</span></figcaption>
</figure>"""


# ---------------------------------------------------------------- gabarits

LOGO = ('<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true">'
        '<rect x="1" y="1" width="12" height="12" fill="#a63d2a"/>'
        '<rect x="15" y="1" width="12" height="12" fill="#2f6b4f"/>'
        '<rect x="1" y="15" width="12" height="12" fill="#8a5a12"/>'
        '<rect x="15" y="15" width="12" height="12" fill="#6b3f6f"/></svg>')


def entete(courant: str = "") -> str:
    liens = []
    for url, libelle in ((f"/{PREFIXE}/", "Fiches"), ("/themes/", "Thèmes")):
        actif = ' aria-current="page"' if courant == url else ""
        liens.append(f'<a href="{url}"{actif}>{libelle}</a>')
    return f"""<a class="lien-evitement" href="#contenu">Aller au contenu</a>
<header class="site-entete">
    <a class="marque" href="/">{LOGO}{NOM_SITE}</a>
    <nav aria-label="Navigation principale">{"".join(liens)}</nav>
</header>"""


PIED = f"""<footer class="site-pied">
    <p class="pied-ligne"><a class="pied-site" href="/">{NOM_SITE}</a><span class="pied-sep" aria-hidden="true">/</span><a class="pied-hub" href="https://nicolaguel.fr/">nicolaguel.fr</a></p>
    <p class="pied-mention">Textes écrits avec l’aide d’une intelligence artificielle, relus et vérifiés par l’auteur.</p>
</footer>"""


def gabarit(titre: str, description: str, contenu: str, courant: str = "",
            url: str = "/", image: str = "", donnees: dict | None = None,
            type_og: str = "website", script: bool = False) -> str:
    robots = ('<meta name="robots" content="noindex, nofollow">\n'
              if EN_CONCEPTION or BROUILLONS else "")
    canonique = URL_SITE + url
    meta_image = (f'<meta property="og:image" content="{URL_SITE}{image}">\n'
                  if image else "")
    jsonld = ""
    if donnees:
        jsonld = ('<script type="application/ld+json">'
                  + json.dumps(donnees, ensure_ascii=False).replace("</", "<\\/")
                  + '</script>\n')
    js = '<script src="/kaleido.js" defer></script>\n' if script else ""
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{html.escape(titre)}</title>
<meta name="description" content="{html.escape(description)}">
<link rel="canonical" href="{canonique}">
<meta property="og:site_name" content="{NOM_SITE}">
<meta property="og:type" content="{type_og}">
<meta property="og:title" content="{html.escape(titre)}">
<meta property="og:description" content="{html.escape(description)}">
<meta property="og:url" content="{canonique}">
<meta property="og:locale" content="fr_FR">
{meta_image}<link rel="alternate" type="application/rss+xml" title="{NOM_SITE}" href="/flux.xml">
{robots}{jsonld}<link rel="preload" href="/polices/literata-latin-400-normal.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/polices/bricolage-grotesque-latin-700-normal.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/style.css">
{js}</head>
<body>
{entete(courant)}
<main id="contenu">
{contenu}
</main>
{PIED}
</body>
</html>
"""


def identite_html(page: dict) -> str:
    """La « carte d'identité » du sujet, en liste de définitions."""
    ident = page.get("identite") or {}
    if not ident:
        return ""
    lignes = "".join(
        f"<div><dt>{html.escape(str(k).replace('_', ' ').capitalize())}</dt>"
        f"<dd>{html.escape(typographie(str(v)))}</dd></div>"
        for k, v in ident.items())
    return f'<dl class="identite">{lignes}</dl>'


def rencontre_html(page: dict) -> str:
    if not page.get("rencontre"):
        return ""
    return f'<p class="rencontre">{html.escape(typographie(str(page["rencontre"])))}</p>'


IMAGE_TEXTE = re.compile(r'^!\[([^\]]*)\]\(image:([a-z0-9-]+)(?:\s+"([^"]*)")?\)\s*$', re.M)


def images_dans_le_texte(texte: str, manifeste: dict) -> str:
    """Une ligne ![alt](image:nom "Légende") devient une figure, si l'image est importée."""

    def remplacer(m):
        alt, nom, legende = m.group(1), m.group(2), m.group(3) or ""
        if nom not in manifeste:
            return ""
        d = manifeste[nom]
        legende_html = f"<figcaption>{italiques(html.escape(legende))}</figcaption>" if legende else ""
        return (f'\n<figure class="illustration dans-le-texte">'
                f'<img src="/images/{nom}-1400.webp" srcset="/images/{nom}-800.webp 800w, /images/{nom}-1400.webp 1400w" '
                f'sizes="(min-width: 44rem) 40rem, 100vw" width="{d["largeur"]}" height="{d["hauteur"]}" '
                f'alt="{html.escape(alt)}" loading="lazy" decoding="async">{legende_html}</figure>\n')

    return IMAGE_TEXTE.sub(remplacer, texte)


def url_theme(theme: str) -> str:
    return f"/themes/{slugifier(theme)}/"


def page_fiche(page: dict, index: dict, pages: list, manifeste: dict) -> str:
    corps_html = rendre_markdown(images_dans_le_texte(liens_wiki(page["corps"], index), manifeste))
    sections = decouper_sections(corps_html)

    blocs, sommaire = [], []
    for s in sections:
        if s["id"] == SECTION_EN_BREF:
            blocs.append(f'<section class="en-bref">{s["html"]}</section>')
        elif s["id"] == "sources":
            blocs.append(f'<section class="annexe sources">{s["html"]}</section>')
        elif s["id"] in SECTIONS_ANNEXES:
            blocs.append(f'<section class="annexe">{s["html"]}</section>')
        else:
            blocs.append(f'<section>{s["html"]}</section>')
        if s["id"]:
            sommaire.append(f'<li><a href="#{s["id"]}">{s["titre"]}</a></li>')

    # « Dans le cahier » : les thèmes de la fiche et les fiches qui la citent
    cahier = []
    if page["themes"]:
        themes = "".join(f'<li><a href="{url_theme(t)}">{html.escape(t)}</a></li>' for t in page["themes"])
        cahier.append(f'<p>Les fiches des mêmes thèmes :</p><ul class="liste-themes">{themes}</ul>')
    retour = liens_retour(page, pages)
    if retour:
        items = "".join(f'<li><a href="{p["url"]}">{html.escape(p["titre"])}</a>'
                        f' <span class="type-lien">{p["libelle"].lower()}</span></li>'
                        for p in sorted(retour, key=lambda p: p["titre"]))
        cahier.append(f'<p>Cité dans :</p><ul class="cites">{items}</ul>')
    cahier_html = (f'<aside class="dans-le-cahier" aria-labelledby="dans-le-cahier">'
                   f'<h2 id="dans-le-cahier">Dans le cahier</h2>{"".join(cahier)}</aside>'
                   if cahier else "")

    maj = date_fr(page.get("mise_a_jour", ""))
    format_ = f" · {page['format']}" if page.get("format") else ""
    brouillon = ('<p class="brouillon">Brouillon : non publié.</p>'
                 if not page["publie_ok"] else "")
    duree = ("moins de 2 minutes" if page["minutes"] < 2
             else f"environ {page['minutes']} minutes")
    nav_sommaire = (f'<nav class="sommaire" aria-label="Sommaire"><p class="sommaire-titre">Dans cette fiche</p>'
                    f'<ol>{"".join(sommaire)}</ol></nav>') if len(sommaire) >= 3 else ""
    contenu = f"""<article class="cadre {page["classe"]}">
<div class="fiche-tete">
    <p class="ariane"><a href="/">Accueil</a> › <a href="/{PREFIXE}/">Fiches</a></p>
    <p class="fiche-nature">{page["libelle"]}{format_}</p>
    <h1>{html.escape(page["titre"])}</h1>
    <p class="chapo">{html.escape(page.get("chapo", ""))}</p>
    <p class="infos">{duree} de lecture. Mis à jour le {maj}.</p>
    {brouillon}
    {rencontre_html(page)}
</div>
{identite_html(page)}
{illustration(page, manifeste)}
<div class="fiche-corps">
{nav_sommaire}
<div class="texte">
{"".join(blocs)}
</div>
</div>
{cahier_html}
</article>"""
    bloc = page.get("image") or {}
    nom_image = bloc.get("fichier")
    image = f"/images/{nom_image}-1400.webp" if nom_image in manifeste else ""
    return gabarit(f"{page['titre']} — {NOM_SITE}", page.get("chapo", ""), contenu,
                   f"/{PREFIXE}/", url=page["url"], image=image,
                   donnees=donnees_structurees(page, image), type_og="article")


def donnees_structurees(page: dict, image: str) -> dict:
    """Données schema.org : un article, avec fil d'Ariane."""
    article = {
        "@type": "Article",
        "headline": page["titre"],
        "description": page.get("chapo", ""),
        "inLanguage": "fr",
        "url": URL_SITE + page["url"],
        "dateModified": iso(page.get("mise_a_jour")),
        "author": {"@type": "Person", "name": AUTEUR},
        "publisher": {"@type": "Organization", "name": NOM_SITE, "url": URL_SITE + "/"},
        "isAccessibleForFree": True,
        "articleSection": page["libelle"],
    }
    if page["themes"]:
        article["keywords"] = ", ".join(page["themes"])
    if image:
        article["image"] = URL_SITE + image
    ariane = {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Accueil", "item": URL_SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Fiches", "item": f"{URL_SITE}/{PREFIXE}/"},
            {"@type": "ListItem", "position": 3, "name": page["titre"], "item": URL_SITE + page["url"]},
        ],
    }
    return {"@context": "https://schema.org", "@graph": [article, ariane]}


# ---------------------------------------------------------------- fichiers pour moteurs et IA

def tous_les_themes(pages: list) -> dict:
    themes: dict = {}
    for p in pages:
        for t in p["themes"]:
            themes.setdefault(t, []).append(p)
    return dict(sorted(themes.items(), key=lambda kv: slugifier(kv[0])))


def sitemap(pages: list) -> str:
    urls = [("/", max((iso(p.get("mise_a_jour")) for p in pages), default="")),
            (f"/{PREFIXE}/", None), ("/themes/", None)]
    urls += [(url_theme(t), None) for t in tous_les_themes(pages)]
    urls += [(p["url"], iso(p.get("mise_a_jour"))) for p in pages]
    lignes = "".join(
        f"  <url><loc>{URL_SITE}{u}</loc>" + (f"<lastmod>{m}</lastmod>" if m else "") + "</url>\n"
        for u, m in urls)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"{lignes}</urlset>\n")


def robots_txt() -> str:
    return f"User-agent: *\nAllow: /\n\nSitemap: {URL_SITE}/sitemap.xml\n"


def flux_rss(pages: list) -> str:
    from email.utils import format_datetime
    recents = sorted(pages, key=lambda p: iso(p.get("mise_a_jour")), reverse=True)[:30]
    items = ""
    for p in recents:
        d = p.get("mise_a_jour")
        quand = format_datetime(datetime(d.year, d.month, d.day, tzinfo=timezone.utc)) if isinstance(d, date) else ""
        items += (f"<item><title>{html.escape(p['titre'])}</title>"
                  f"<link>{URL_SITE}{p['url']}</link><guid>{URL_SITE}{p['url']}</guid>"
                  f"<description>{html.escape(p.get('chapo', ''))}</description>"
                  f"<pubDate>{quand}</pubDate></item>\n")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>\n'
            f"<title>{NOM_SITE}</title><link>{URL_SITE}/</link>"
            f"<description>{html.escape(DEVISE)}</description><language>fr</language>\n"
            f"{items}</channel></rss>\n")


def llms_txt(pages: list) -> str:
    blocs = []
    for nature, (_, pluriel) in NATURES.items():
        de_la_nature = sorted((p for p in pages if p.get("nature") == nature),
                              key=lambda p: slugifier(p["titre"]))
        if not de_la_nature:
            continue
        lignes = "\n".join(f"- [{p['titre']}]({URL_SITE}{p['url']}): {p.get('chapo', '')}"
                           for p in de_la_nature)
        blocs.append(f"## {pluriel}\n\n{lignes}")
    return (f"# {NOM_SITE}\n\n> {DEVISE} Fiches en français sur des œuvres, des lieux, "
            f"des personnes et des notions, écrites par {AUTEUR} avec l'aide "
            "d'une intelligence artificielle, relues et vérifiées par l'auteur.\n\n"
            "Chaque fiche comporte un chapô, une rubrique « En bref », éventuellement "
            "des sections de développement, des pistes pour aller plus loin et les sources.\n\n"
            + "\n\n".join(blocs) + "\n")


# ---------------------------------------------------------------- pages d'ensemble

def normaliser(texte: str) -> str:
    """Même normalisation que la recherche en JavaScript : minuscules, sans accents."""
    t = unicodedata.normalize("NFD", texte.lower().replace("œ", "oe"))
    return "".join(c for c in t if not unicodedata.combining(c))


def carte(p: dict, manifeste: dict) -> str:
    bloc = p.get("image") or {}
    nom = bloc.get("fichier")
    if nom in manifeste:
        d = manifeste[nom]
        visuel = (f'<img class="carte-image" src="/images/{nom}-800.webp" width="{d["largeur"]}" '
                  f'height="{d["hauteur"]}" alt="" loading="lazy" decoding="async">')
    else:
        visuel = f'<span class="carte-aplat" aria-hidden="true">{p["libelle"]}</span>'
    recherche = normaliser(" ".join([p["titre"], " ".join(map(str, p.get("alias") or [])),
                                     p.get("chapo", ""), " ".join(p["themes"]), p["libelle"]]))
    nature = slugifier(str(p.get("nature", "")).replace("œ", "oe"))
    return (f'<li class="carte {p["classe"]}" data-nature="{nature}" data-recherche="{html.escape(recherche)}">'
            f'<a href="{p["url"]}">{visuel}'
            f'<span class="carte-nature">{p["libelle"]}</span>'
            f'<span class="carte-titre">{html.escape(p["titre"])}</span>'
            f'<span class="carte-chapo">{html.escape(p.get("chapo", ""))}</span>'
            f'</a></li>')


def mosaique(pages: list, manifeste: dict, outils: bool = True) -> str:
    if not pages:
        return "<p>Aucune fiche publiée pour le moment.</p>"
    cartes = "\n".join(carte(p, manifeste) for p in sorted(pages, key=lambda p: slugifier(p["titre"])))
    barre = ""
    if outils:
        presentes = [n for n in NATURES if any(p.get("nature") == n for p in pages)]
        boutons = ['<button type="button" aria-pressed="true">Tout</button>'] + [
            f'<button type="button" aria-pressed="false" data-nature="{slugifier(n.replace("œ", "oe"))}">'
            f'{NATURES[n][1]}</button>' for n in presentes]
        barre = f"""<div class="outils" hidden>
    <label class="recherche">
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="8.5" cy="8.5" r="6"/><path d="M13 13l5 5"/></svg>
        <span class="cache">Rechercher dans le cahier</span>
        <input type="search" placeholder="Rechercher une œuvre, un lieu, un nom…" autocomplete="off">
    </label>
    <div class="filtres" role="group" aria-label="Filtrer par nature">{"".join(boutons)}</div>
</div>"""
    return f"""{barre}
<ul class="mosaique">
{cartes}
</ul>
<p class="aucun" hidden>Aucune fiche ne correspond à cette recherche.</p>"""


def page_accueil(pages: list, manifeste: dict) -> str:
    contenu = f"""<div class="cadre">
<section class="ouverture">
    <h1 class="ouverture-titre">{NOM_SITE}</h1>
    <p class="ouverture-accroche">{DEVISE}</p>
</section>
{mosaique(pages, manifeste)}
</div>"""
    donnees = {"@context": "https://schema.org", "@type": "WebSite", "name": NOM_SITE,
               "url": URL_SITE + "/", "inLanguage": "fr", "description": DEVISE,
               "author": {"@type": "Person", "name": AUTEUR}}
    return gabarit(NOM_SITE, DEVISE, contenu, "/", url="/", donnees=donnees, script=True)


def page_index(pages: list, manifeste: dict) -> str:
    intro = ("Chaque fiche présente une œuvre, un lieu, une personne ou une notion : "
             "d’abord en bref, puis, selon le sujet, en détail.")
    contenu = f"""<div class="cadre">
    <h1 class="page-titre">Fiches</h1>
    <p class="page-intro">{intro}</p>
{mosaique(pages, manifeste)}
</div>"""
    return gabarit(f"Fiches — {NOM_SITE}", intro, contenu, f"/{PREFIXE}/", url=f"/{PREFIXE}/", script=True)


def page_themes(themes: dict) -> str:
    items = "".join(f'<li><a href="{url_theme(t)}">{html.escape(t)} <span class="compte">{len(ps)}</span></a></li>'
                    for t, ps in themes.items())
    intro = "Les fiches regroupées par thème. Une fiche peut appartenir à plusieurs thèmes."
    contenu = f"""<div class="cadre">
    <h1 class="page-titre">Thèmes</h1>
    <p class="page-intro">{intro}</p>
    <ul class="liste-themes">{items}</ul>
</div>"""
    return gabarit(f"Thèmes — {NOM_SITE}", intro, contenu, "/themes/", url="/themes/")


def page_theme(theme: str, pages: list, manifeste: dict) -> str:
    n = len(pages)
    intro = f"{n} fiche{'s' if n > 1 else ''} sur le thème « {theme} »."
    contenu = f"""<div class="cadre">
    <p class="ariane" style="margin-top:3rem"><a href="/">Accueil</a> › <a href="/themes/">Thèmes</a></p>
    <h1 class="page-titre" style="margin-top:0">{html.escape(theme[:1].upper() + theme[1:])}</h1>
    <p class="page-intro">{html.escape(intro)}</p>
{mosaique(pages, manifeste, outils=False)}
</div>"""
    return gabarit(f"{theme} — {NOM_SITE}", intro, contenu, "/themes/", url=url_theme(theme))


# ---------------------------------------------------------------- build

def ecrire(chemin_url: str, html_page: str) -> None:
    cible = SORTIE / chemin_url.strip("/") / "index.html"
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible.write_text(html_page, encoding="utf-8")


def main() -> None:
    if SORTIE.exists():
        shutil.rmtree(SORTIE)
    shutil.copytree(STATIC, SORTIE)

    toutes = [lire_fiche(p) for p in sorted(CONTENUS.glob("*.md"))]
    publiees = [m for m in toutes if m["publie_ok"]]
    for m in publiees:
        verifier_publiee(m)
    retenues = toutes if BROUILLONS else publiees
    pages = [preparer(m) for m in retenues]
    manifeste = json.loads(MANIFESTE_IMAGES.read_text()) if MANIFESTE_IMAGES.exists() else {}
    index = {p["slug"]: p for p in pages}
    themes = tous_les_themes(pages)

    for page in pages:
        ecrire(page["url"], page_fiche(page, index, pages, manifeste))
    ecrire(f"/{PREFIXE}/", page_index(pages, manifeste))
    ecrire("/themes/", page_themes(themes))
    for theme, du_theme in themes.items():
        ecrire(url_theme(theme), page_theme(theme, du_theme, manifeste))
    ecrire("/", page_accueil(pages, manifeste))
    (SORTIE / "sitemap.xml").write_text(sitemap(pages), encoding="utf-8")
    (SORTIE / "robots.txt").write_text(robots_txt(), encoding="utf-8")
    (SORTIE / "flux.xml").write_text(flux_rss(pages), encoding="utf-8")
    (SORTIE / "llms.txt").write_text(llms_txt(pages), encoding="utf-8")

    ignorees = len(toutes) - len(publiees)
    print(f"{len(pages)} fiche(s) générée(s) dans {SORTIE}, {len(themes)} thème(s)"
          + (f" ; {ignorees} brouillon(s) {'inclus' if BROUILLONS else 'ignoré(s)'}" if ignorees else ""))
    for m in toutes:
        if not m["publie_ok"] and m["marqueurs"]:
            print(f"  attention : {m['fichier']} (brouillon) a des marqueurs À VÉRIFIER, "
                  f"lignes {', '.join(map(str, m['marqueurs']))}")


if __name__ == "__main__":
    main()
