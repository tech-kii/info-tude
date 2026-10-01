#!/usr/bin/env python3
"""infoetude : Claude cherche l'actualité, rédige des articles et génère le site.

Commandes :
    python infoetude_bot.py run                 # recherche + rédaction + génération du site
    python infoetude_bot.py drafts              # liste les brouillons à relire
    python infoetude_bot.py approve <slug|all>  # valide un brouillon (ou tous) et régénère le site
    python infoetude_bot.py build [--apercu]    # régénère le site (--apercu inclut les brouillons)

Variables d'environnement :
    ANTHROPIC_API_KEY     clé API (obligatoire pour "run")
    AUTO_PUBLISH=1        publie sans relecture humaine (déconseillé au début)
    INFOETUDE_PAYS        zone ciblée, ex. "Sénégal et Afrique francophone"
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "posts.json"
SITE = ROOT / "site"

MODEL = "claude-sonnet-5-5"
ARTICLES_PAR_RUBRIQUE = 2
AUTO_PUBLISH = os.getenv("AUTO_PUBLISH") == "1"
PAYS = os.getenv("INFOETUDE_PAYS", "Sénégal et Afrique francophone")

RUBRIQUES = {
    "Bourses": "bourses d'études, aides financières et appels à candidatures ouverts",
    "Formations": "formations professionnelles et certifiantes, financement, reconversion",
    "Concours": "concours d'entrée aux écoles et à la fonction publique, calendriers",
    "Enseignement supérieur": "réformes, universités, masters, mobilité internationale",
}

SYSTEM = """Tu es le rédacteur en chef d'infoetude, un site francophone sur la formation \
professionnelle et l'enseignement supérieur.
Règles :
- Utilise la recherche web pour trouver des informations récentes (moins de 30 jours) et vérifiables.
- Reformule avec tes propres mots. Ne recopie jamais un texte. Aucune citation de plus de 15 mots.
- N'invente jamais une date, un montant ou une condition. Si l'information manque dans les sources, \
écris « à confirmer » et laisse date_limite à null.
- Chaque article cite au moins une source avec son URL exacte.
- Ton clair, factuel, utile à un étudiant ou à un professionnel.
Réponds UNIQUEMENT avec un objet JSON, sans texte autour ni balises Markdown :
{"articles":[{"titre":"","resume":"2 phrases maximum","paragraphes":["..."],\
"date_limite":"AAAA-MM-JJ ou null","sources":[{"titre":"","url":""}]}]}"""

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]
NOTE_IA = ("Article rédigé avec l'aide de l'IA à partir des sources ci-dessus. "
           "Vérifiez toujours les informations sur le site officiel de l'organisme.")


# ---------------------------------------------------------------- données
def charger():
    return json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else []


def sauver(posts):
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:70]


def valider(a, rubrique):
    """Vérifie la structure renvoyée par Claude. Retourne un article propre ou None."""
    try:
        titre = str(a["titre"]).strip()
        resume = str(a["resume"]).strip()
        paras = [str(x).strip() for x in a["paragraphes"] if str(x).strip()]
        sources = [
            {"titre": str(s.get("titre") or s["url"]).strip(), "url": s["url"].strip()}
            for s in a["sources"]
            if str(s.get("url", "")).startswith(("http://", "https://"))
        ]
    except (KeyError, TypeError, AttributeError):
        return None
    if not (titre and resume and paras and sources):
        return None
    limite = a.get("date_limite")
    try:
        dt.date.fromisoformat(limite)
    except (TypeError, ValueError):
        limite = None
    return {
        "slug": slugify(titre), "rubrique": rubrique, "titre": titre, "resume": resume,
        "paragraphes": paras, "sources": sources, "date_limite": limite,
        "date": dt.date.today().isoformat(),
        "statut": "publie" if AUTO_PUBLISH else "brouillon",
    }


# ---------------------------------------------------------------- Claude
def extraire_json(texte):
    debut = texte.find('{"articles"')
    if debut == -1:
        debut = texte.find("{")
    if debut == -1:
        raise ValueError("Aucun JSON dans la réponse")
    obj, _ = json.JSONDecoder().raw_decode(texte[debut:])
    return obj


def generer(client, rubrique, sujet, deja):
    prompt = (
        f"Date du jour : {dt.date.today().isoformat()}. Zone ciblée : {PAYS}.\n"
        f"Rubrique : {rubrique} ({sujet}).\n"
        f"Rédige {ARTICLES_PAR_RUBRIQUE} articles nouveaux de 4 à 6 paragraphes chacun.\n"
        f"Sujets déjà traités, à éviter : {deja}."
    )
    rep = client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
        messages=[{"role": "user", "content": prompt}],
    )
    texte = "".join(b.text for b in rep.content if b.type == "text")
    return extraire_json(texte)["articles"]


def cmd_run(_args):
    import anthropic # importé ici pour que "build" fonctionne sans la bibliothèque

    client = anthropic.Anthropic()
    posts = charger()
    slugs = {p["slug"] for p in posts}
    urls = {s["url"] for p in posts for s in p["sources"]}  # évite de retraiter une même source
    nouveaux = 0
    for rubrique, sujet in RUBRIQUES.items():
        deja = "; ".join(p["titre"] for p in posts if p["rubrique"] == rubrique)[-1500:] or "aucun"
        try:
            bruts = generer(client, rubrique, sujet, deja)
        except Exception as e:  # une rubrique en échec ne bloque pas les autres
            print(f"[{rubrique}] échec : {e}", file=sys.stderr)
            continue
        for a in bruts:
            p = valider(a, rubrique)
            if not p or p["slug"] in slugs or any(s["url"] in urls for s in p["sources"]):
                continue
            posts.append(p)
            slugs.add(p["slug"])
            urls.update(s["url"] for s in p["sources"])
            nouveaux += 1
            print(f"[{rubrique}] + {p['titre']} ({p['statut']})")
    sauver(posts)
    build(posts)
    print(f"{nouveaux} nouvel(s) article(s).")


# ---------------------------------------------------------------- validation humaine
def cmd_drafts(_args):
    brouillons = [p for p in charger() if p["statut"] == "brouillon"]
    for p in brouillons:
        lim = f" | limite {p['date_limite']}" if p["date_limite"] else ""
        print(f"{p['slug']}\n   {p['titre']} [{p['rubrique']}{lim}]")
    print(f"{len(brouillons)} brouillon(s).")


def cmd_approve(args):
    posts = charger()
    n = 0
    for p in posts:
        if p["statut"] == "brouillon" and args.cible in ("all", p["slug"]):
            p["statut"] = "publie"
            n += 1
    sauver(posts)
    build(posts)
    print(f"{n} article(s) publié(s).")


# ---------------------------------------------------------------- génération du site
esc = html.escape

CSS = """
:root{--bg:#F2F5FB;--surface:#fff;--ink:#0F1E45;--muted:#4C5878;--line:#D5DCEC;--brand:#2440D4;
--sun:#FFC62E;--sun-ink:#3B2A00;--warn:#B3341B;
--head:'Bricolage Grotesque','Trebuchet MS',system-ui,sans-serif;--body:'Public Sans','Segoe UI',system-ui,sans-serif}
@media(prefers-color-scheme:dark){:root{--bg:#0B1230;--surface:#141D42;--ink:#EDF1FF;--muted:#A5B0D3;
--line:#27335F;--brand:#7C93FF;--warn:#FF8A73}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:400 17px/1.65 var(--body)}
a{color:inherit}:focus-visible{outline:3px solid var(--brand);outline-offset:3px}
.wrap{max-width:1120px;margin:0 auto;padding:0 20px}
header{border-bottom:1px solid var(--line)}.bar{padding:16px 0}
.logo{font:800 26px/1 var(--head);text-decoration:none;letter-spacing:-.02em}
.logo b{background:var(--sun);color:var(--sun-ink);padding:1px 7px;border-radius:6px;margin-left:2px}
.hero{display:grid;grid-template-columns:1.1fr 1fr;gap:48px;padding:56px 0;align-items:start}
h1{font:800 clamp(32px,5vw,54px)/1.05 var(--head);letter-spacing:-.03em;margin:0 0 18px}
.lead{color:var(--muted);font-size:19px;max-width:52ch}
.board{background:var(--surface);border:2px solid var(--ink);border-radius:16px;box-shadow:8px 8px 0 var(--sun);overflow:hidden}
.board h2{margin:0;padding:16px 20px;font:700 19px var(--head);border-bottom:2px solid var(--ink)}
.board ul{list-style:none;margin:0;padding:0}
.board li{display:grid;grid-template-columns:auto 1fr;gap:16px;padding:16px 20px;border-bottom:1px solid var(--line);align-items:center}
.board li:last-child{border-bottom:0}
.days{min-width:64px;text-align:center;font:800 28px/1 var(--head)}
.days small{display:block;font:500 12px var(--body);color:var(--muted);margin-top:4px}
.urgent{color:var(--warn)}.board em{font-style:normal;color:var(--muted);font-size:14px;display:block}
.head{display:flex;justify-content:space-between;align-items:end;gap:20px;flex-wrap:wrap;margin:16px 0 24px}
h2.t{font:800 32px/1.1 var(--head);margin:0}
.filters{display:flex;gap:8px;flex-wrap:wrap}
.filters button{font:500 14px var(--body);padding:8px 14px;border-radius:999px;border:1.5px solid var(--line);background:none;color:var(--ink);cursor:pointer}
.filters button[aria-pressed=true]{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;padding-bottom:56px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:22px;display:flex;flex-direction:column;gap:10px}
.card.first{grid-column:span 2;background:var(--brand);color:#fff;border-color:var(--brand)}
.card.first p,.card.first .meta{color:inherit;opacity:.88}
.tag{align-self:flex-start;font:600 13px var(--body);padding:3px 10px;border-radius:6px;background:var(--bg);color:var(--ink)}
.card.first .tag{background:var(--sun);color:var(--sun-ink)}
.card h3{font:700 21px/1.2 var(--head);margin:0}.card.first h3{font-size:28px}
.card h3 a{text-decoration:none}.card p{margin:0;color:var(--muted);font-size:15.5px}
.meta{margin-top:auto;font-size:13.5px;color:var(--muted)}.hidden{display:none}
.art{max-width:720px;padding-top:40px;padding-bottom:56px}.art h1{font-size:clamp(28px,4.4vw,42px)}
.art h2{font:700 22px var(--head);margin-top:36px}
.deadline{background:var(--sun);color:var(--sun-ink);padding:12px 16px;border-radius:10px;font-weight:500}
.note{color:var(--muted);font-size:14.5px;border-top:1px solid var(--line);padding-top:16px;margin-top:32px}
footer{border-top:1px solid var(--line);padding:28px 0 36px;color:var(--muted);font-size:14.5px}
@media(max-width:860px){.hero{grid-template-columns:1fr;padding-top:36px}.grid{grid-template-columns:1fr 1fr}}
@media(max-width:560px){.grid{grid-template-columns:1fr}.card.first{grid-column:auto}}
"""

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family='
         'Bricolage+Grotesque:wght@500;700;800&family=Public+Sans:wght@400;500;600&display=swap">')


def date_fr(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def page(titre, corps, prefix=""):
    return (
        '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>{esc(titre)}</title>{FONTS}"
        f'<link rel="stylesheet" href="{prefix}style.css"></head><body>'
        f'<header><div class="wrap bar"><a class="logo" href="{prefix}index.html">'
        "info<b>etude</b></a></div></header>"
        f"{corps}"
        '<footer><div class="wrap">infoetude : veille sur la formation et l\'enseignement supérieur.'
        "</div></footer></body></html>"
    )


def build_article(p):
    paras = "".join(f"<p>{esc(x)}</p>" for x in p["paragraphes"])
    sources = "".join(
        f'<li><a href="{esc(s["url"])}" rel="noopener nofollow">{esc(s["titre"])}</a></li>'
        for s in p["sources"]
    )
    limite = ""
    if p["date_limite"]:
        limite = f'<p class="deadline">Date limite : <strong>{date_fr(p["date_limite"])}</strong></p>'
    corps = (
        f'<main class="wrap art"><span class="tag">{esc(p["rubrique"])}</span>'
        f'<h1>{esc(p["titre"])}</h1><p class="meta">Publié le {date_fr(p["date"])}</p>'
        f"{limite}{paras}<h2>Sources</h2><ul>{sources}</ul>"
        f'<p class="note">{esc(NOTE_IA)}</p></main>'
    )
    return page(p["titre"] + " – infoetude", corps, prefix="../")


def build_index(posts):
    aujourdhui = dt.date.today()
    urgents = sorted(
        (p for p in posts if p["date_limite"] and p["date_limite"] >= aujourdhui.isoformat()),
        key=lambda p: p["date_limite"],
    )[:4]
    lignes = ""
    for p in urgents:
        jours = (dt.date.fromisoformat(p["date_limite"]) - aujourdhui).days
        cls = " urgent" if jours <= 7 else ""
        lignes += (
            f'<li><div class="days{cls}">{jours}<small>jours</small></div><div>'
            f'<strong><a href="articles/{p["slug"]}.html">{esc(p["titre"])}</a></strong>'
            f'<em>{esc(p["rubrique"])}</em></div></li>'
        )
    if not lignes:
        lignes = "<li><div><em>Aucune date limite à venir.</em></div></li>"

    cartes = ""
    for i, p in enumerate(posts):
        cls = " first" if i == 0 else ""
        cartes += (
            f'<article class="card{cls}" data-c="{esc(p["rubrique"])}">'
            f'<span class="tag">{esc(p["rubrique"])}</span>'
            f'<h3><a href="articles/{p["slug"]}.html">{esc(p["titre"])}</a></h3>'
            f'<p>{esc(p["resume"])}</p><span class="meta">{date_fr(p["date"])}</span></article>'
        )
    if not cartes:
        cartes = "<p>Aucune publication pour le moment.</p>"

    boutons = "".join(
        f'<button type="button" aria-pressed="false" data-c="{esc(r)}">{esc(r)}</button>'
        for r in ["Toutes"] + list(RUBRIQUES)
    )
    script = (
        "<script>var b=document.querySelectorAll('.filters button'),"
        "c=document.querySelectorAll('.card');"
        "function f(r){b.forEach(function(x){x.setAttribute('aria-pressed',x.dataset.c===r)});"
        "c.forEach(function(k){k.classList.toggle('hidden',r!=='Toutes'&&k.dataset.c!==r)})}"
        "b.forEach(function(x){x.onclick=function(){f(x.dataset.c)}});f('Toutes')</script>"
    )
    corps = (
        '<main><div class="wrap hero"><div>'
        "<h1>Formations, bourses et concours, avant la date limite.</h1>"
        '<p class="lead">infoetude suit chaque jour l\'actualité de la formation professionnelle '
        "et de l'enseignement supérieur, et vous dit ce qui ferme bientôt.</p></div>"
        f'<aside class="board"><h2>Bientôt clôturé</h2><ul>{lignes}</ul></aside></div>'
        '<div class="wrap"><div class="head"><h2 class="t">Dernières publications</h2>'
        f'<div class="filters" role="group" aria-label="Filtrer par rubrique">{boutons}</div></div>'
        f'<div class="grid">{cartes}</div></div></main>{script}'
    )
    return page("infoetude – Formation professionnelle et enseignement supérieur", corps)


def build(posts=None, apercu=False):
    posts = charger() if posts is None else posts
    visibles = [p for p in posts if apercu or p["statut"] == "publie"]
    visibles.sort(key=lambda p: p["date"], reverse=True)
    (SITE / "articles").mkdir(parents=True, exist_ok=True)
    (SITE / "style.css").write_text(CSS, encoding="utf-8")
    (SITE / "index.html").write_text(build_index(visibles), encoding="utf-8")
    for ancien in (SITE / "articles").glob("*.html"):
        ancien.unlink()  # supprime les pages dépubliées
    for p in visibles:
        (SITE / "articles" / f"{p['slug']}.html").write_text(build_article(p), encoding="utf-8")
    print(f"Site généré dans {SITE} ({len(visibles)} article(s)).")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="infoetude : site alimenté par Claude")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").set_defaults(fn=cmd_run)
    sub.add_parser("drafts").set_defaults(fn=cmd_drafts)
    a = sub.add_parser("approve")
    a.add_argument("cible", help="slug de l'article, ou 'all'")
    a.set_defaults(fn=cmd_approve)
    b = sub.add_parser("build")
    b.add_argument("--apercu", action="store_true", help="inclut les brouillons")
    b.set_defaults(fn=lambda args: build(apercu=args.apercu))
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
