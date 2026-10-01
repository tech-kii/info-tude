#!/usr/bin/env python3
"""Tableau de bord infoetude : ajouter, modifier et publier des articles.

Lancement :
    pip install -r requirements.txt
    python dashboard.py            # puis ouvrir http://127.0.0.1:5000

Variables d'environnement (facultatives) :
    DASHBOARD_PASSWORD   protège le tableau de bord par mot de passe (utilisateur : n'importe lequel)
    INFOETUDE_AUTEUR     auteur proposé par défaut
"""
import datetime as dt
import os
import re
import subprocess
import uuid

from flask import (Flask, Response, flash, get_flashed_messages, redirect,
                   render_template_string, request, send_from_directory, url_for)

import infoetude_bot as bot

app = Flask(__name__)
app.secret_key = os.getenv("DASHBOARD_SECRET") or os.urandom(16)
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024  # images de 6 Mo maximum
IMAGES = bot.ROOT / "images"
IMAGES.mkdir(exist_ok=True)
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
PASSWORD = os.getenv("DASHBOARD_PASSWORD")


@app.before_request
def verifier_acces():
    if PASSWORD:
        a = request.authorization
        if not a or a.password != PASSWORD:
            return Response("Authentification requise", 401,
                            {"WWW-Authenticate": 'Basic realm="infoetude"'})


# ---------------------------------------------------------------- modèles HTML
HEAD = """<!doctype html><html lang="fr"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>infoetude · tableau de bord</title>
<style>
:root{--bg:#F2F5FB;--s:#fff;--ink:#0F1E45;--mut:#4C5878;--line:#D5DCEC;--brand:#2440D4;--sun:#FFC62E;--ok:#14794F;--bad:#B3341B}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,'Segoe UI',sans-serif}
.w{max-width:1000px;margin:0 auto;padding:0 20px}
header{background:var(--s);border-bottom:1px solid var(--line)}
header .w{display:flex;justify-content:space-between;align-items:center;padding:14px 20px}
.logo{font:800 22px system-ui;text-decoration:none;color:var(--ink)}.logo b{background:var(--sun);padding:1px 6px;border-radius:5px}
.logo small{font:500 13px system-ui;color:var(--mut);margin-left:8px}
h1{font-size:26px;margin:28px 0 16px}
.btn,button{font:600 15px system-ui;padding:9px 16px;border-radius:8px;border:1.5px solid var(--ink);background:var(--s);color:var(--ink);cursor:pointer;text-decoration:none;display:inline-block}
.primary,.btn{background:var(--brand);border-color:var(--brand);color:#fff}
.danger{border-color:var(--bad);color:var(--bad)}
.flash{background:#FFF3CD;border:1px solid var(--sun);padding:10px 14px;border-radius:8px;margin:16px 0 0;white-space:pre-wrap}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}.actions form{margin:0}
table{width:100%;border-collapse:collapse;background:var(--s);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:middle}
th{font-size:13px;color:var(--mut);font-weight:600}td.r{text-align:right;white-space:nowrap}td form{display:inline;margin:0}
td button{padding:5px 10px;font-size:13px}
.badge{font-size:13px;font-weight:600;padding:2px 9px;border-radius:99px}
.publie{background:#D9F4E7;color:var(--ok)}.brouillon{background:#FFF0C2;color:#6B4E00}
form.f{background:var(--s);border:1px solid var(--line);border-radius:12px;padding:24px;display:grid;gap:18px}
label{display:grid;gap:6px;font-weight:600;font-size:15px}label small{font-weight:400;color:var(--mut)}
input,select,textarea{font:16px system-ui;padding:10px 12px;border:1.5px solid var(--line);border-radius:8px;width:100%;background:var(--bg);color:var(--ink)}
textarea{min-height:240px;resize:vertical}.row{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.src{display:grid;grid-template-columns:1fr 2fr auto;gap:8px;margin-bottom:8px}
.preview{max-width:240px;border-radius:8px;border:1px solid var(--line)}
@media(max-width:700px){.row,.src{grid-template-columns:1fr}table{font-size:14px}}
</style>
<header><div class="w"><a class="logo" href="{{ url_for('liste') }}">info<b>etude</b><small>tableau de bord</small></a>
<a class="btn" href="{{ url_for('formulaire') }}">+ Nouvel article</a></div></header>
<main class="w">
{% for m in get_flashed_messages() %}<p class="flash">{{ m }}</p>{% endfor %}
"""

LISTE = HEAD + """
<h1>Articles ({{ posts|length }})</h1>
<div class="actions">
 <form method="post" action="{{ url_for('generer') }}"><button>Régénérer le site</button></form>
 <form method="post" action="{{ url_for('envoyer_git') }}"><button class="primary">Envoyer sur GitHub</button></form>
</div>
{% if posts %}
<table><tr><th>Titre</th><th>Rubrique</th><th>Auteur</th><th>Statut</th><th>Date</th><th></th></tr>
{% for p in posts %}<tr>
 <td><a href="{{ url_for('formulaire', slug=p.slug) }}">{{ p.titre }}</a></td>
 <td>{{ p.rubrique }}</td><td>{{ p.get('auteur') or '—' }}</td>
 <td><span class="badge {{ p.statut }}">{{ 'Publié' if p.statut == 'publie' else 'Brouillon' }}</span></td>
 <td>{{ p.date }}</td>
 <td class="r">
  <form method="post" action="{{ url_for('changer_statut', slug=p.slug) }}"><button>{{ 'Dépublier' if p.statut == 'publie' else 'Publier' }}</button></form>
  <form method="post" action="{{ url_for('supprimer', slug=p.slug) }}" onsubmit="return confirm('Supprimer cet article ?')"><button class="danger">Supprimer</button></form>
 </td></tr>{% endfor %}</table>
{% else %}<p>Aucun article pour le moment. Cliquez sur « Nouvel article » pour commencer.</p>{% endif %}
</main></html>"""

FORM = HEAD + """
<h1>{{ 'Modifier l’article' if p.slug else 'Nouvel article' }}</h1>
<form class="f" method="post" action="{{ url_for('enregistrer') }}" enctype="multipart/form-data">
 <input type="hidden" name="slug" value="{{ p.slug or '' }}">
 <label>Titre<input name="titre" value="{{ p.titre or '' }}" required></label>
 <div class="row">
  <label>Rubrique<select name="rubrique">{% for r in rubriques %}<option {{ 'selected' if p.rubrique == r }}>{{ r }}</option>{% endfor %}</select></label>
  <label>Auteur<input name="auteur" value="{{ p.auteur or auteur_defaut }}" required></label>
 </div>
 <label>Résumé <small>2 phrases maximum, affiché sur la page d'accueil</small>
  <textarea name="resume" style="min-height:80px" required>{{ p.resume or '' }}</textarea></label>
 <label>Contenu <small>Séparez les paragraphes par une ligne vide</small>
  <textarea name="contenu" required>{{ contenu }}</textarea></label>
 <div class="row">
  <label>Date limite <small>facultatif, alimente le bandeau « Bientôt clôturé »</small>
   <input type="date" name="date_limite" value="{{ p.date_limite or '' }}"></label>
  <label>Statut<select name="statut">
   <option value="brouillon" {{ 'selected' if p.statut != 'publie' }}>Brouillon</option>
   <option value="publie" {{ 'selected' if p.statut == 'publie' }}>Publié</option></select></label>
 </div>
 <div class="row">
  <label>Image <small>JPG, PNG, WebP ou GIF, 6 Mo maximum</small><input type="file" name="image" accept="image/*"></label>
  <label>Description de l'image <small>pour l'accessibilité</small><input name="image_alt" value="{{ p.image_alt or '' }}"></label>
 </div>
 {% if p.image %}<div><img class="preview" src="{{ url_for('image', nom=p.image) }}" alt="">
  <label style="display:flex;gap:8px;align-items:center;font-weight:400"><input type="checkbox" name="retirer_image" style="width:auto"> Retirer l'image</label></div>{% endif %}
 <div><strong>Sources</strong> <small>au moins une, avec l'adresse complète</small>
  <div id="srcs" style="margin-top:8px">
  {% for s in (p.sources or [{'titre': '', 'url': ''}]) %}
   <div class="src"><input name="src_titre" placeholder="Nom de la source" value="{{ s.titre }}">
   <input name="src_url" type="url" placeholder="https://..." value="{{ s.url }}">
   <button type="button" onclick="this.parentNode.remove()" aria-label="Retirer cette source">×</button></div>
  {% endfor %}</div>
  <button type="button" onclick="addSrc()">+ Ajouter une source</button></div>
 <div class="actions"><button class="primary">Enregistrer</button><a class="btn" style="background:var(--s);color:var(--ink)" href="{{ url_for('liste') }}">Annuler</a></div>
</form>
<template id="tpl"><div class="src"><input name="src_titre" placeholder="Nom de la source">
<input name="src_url" type="url" placeholder="https://...">
<button type="button" onclick="this.parentNode.remove()" aria-label="Retirer cette source">×</button></div></template>
<script>function addSrc(){document.getElementById('srcs').appendChild(document.getElementById('tpl').content.cloneNode(true))}</script>
</main></html>"""


# ---------------------------------------------------------------- utilitaires
def trouver(posts, slug):
    return next((p for p in posts if p["slug"] == slug), None)


def image_utilisee(posts, nom):
    return any(p.get("image") == nom for p in posts)


def effacer_image(posts, nom):
    """Supprime le fichier image s'il n'est plus utilisé par aucun article."""
    if nom and not image_utilisee(posts, nom):
        (IMAGES / nom).unlink(missing_ok=True)


def git(*args):
    return subprocess.run(["git", *args], cwd=bot.ROOT, capture_output=True, text=True, timeout=90)


# ---------------------------------------------------------------- pages
@app.route("/")
def liste():
    posts = sorted(bot.charger(), key=lambda p: p["date"], reverse=True)
    return render_template_string(LISTE, posts=posts)


@app.route("/article")
@app.route("/article/<slug>")
def formulaire(slug=None):
    p = trouver(bot.charger(), slug) if slug else {}
    if slug and p is None:
        flash("Article introuvable.")
        return redirect(url_for("liste"))
    return render_template_string(FORM, p=p, contenu="\n\n".join(p.get("paragraphes", [])),
                                  rubriques=list(bot.RUBRIQUES), auteur_defaut=bot.AUTEUR_DEFAUT)


@app.route("/images/<path:nom>")
def image(nom):
    return send_from_directory(IMAGES, nom)


@app.post("/enregistrer")
def enregistrer():
    f = request.form
    posts = bot.charger()
    ancien = trouver(posts, f.get("slug", ""))
    paragraphes = [x.strip() for x in re.split(r"\n\s*\n", f.get("contenu", "")) if x.strip()]
    sources = [{"titre": t.strip() or u.strip(), "url": u.strip()}
               for t, u in zip(f.getlist("src_titre"), f.getlist("src_url"))
               if u.strip().startswith(("http://", "https://"))]
    p = {
        "slug": ancien["slug"] if ancien else "",
        "rubrique": f.get("rubrique", ""), "titre": f.get("titre", "").strip(),
        "resume": f.get("resume", "").strip(), "paragraphes": paragraphes, "sources": sources,
        "date_limite": f.get("date_limite") or None,
        "date": ancien["date"] if ancien else dt.date.today().isoformat(),
        "statut": "publie" if f.get("statut") == "publie" else "brouillon",
        "auteur": f.get("auteur", "").strip(), "image": ancien.get("image") if ancien else None,
        "image_alt": f.get("image_alt", "").strip(),
    }
    erreurs = []
    if p["rubrique"] not in bot.RUBRIQUES:
        erreurs.append("Choisissez une rubrique.")
    for champ, nom in (("titre", "titre"), ("resume", "résumé"), ("auteur", "auteur")):
        if not p[champ]:
            erreurs.append(f"Le champ {nom} est obligatoire.")
    if not paragraphes:
        erreurs.append("Le contenu est vide.")
    if not sources:
        erreurs.append("Ajoutez au moins une source avec une adresse commençant par http.")
    fichier = request.files.get("image")
    ext = os.path.splitext(fichier.filename)[1].lower() if fichier and fichier.filename else ""
    if ext and ext not in EXTENSIONS:
        erreurs.append("Format d'image non pris en charge (JPG, PNG, WebP ou GIF).")
    if erreurs:
        for e in erreurs:
            flash(e)
        return render_template_string(FORM, p=p, contenu="\n\n".join(paragraphes),
                                      rubriques=list(bot.RUBRIQUES), auteur_defaut=bot.AUTEUR_DEFAUT)

    # slug unique pour un nouvel article
    if not ancien:
        base = bot.slugify(p["titre"]) or "article"
        slug, n = base, 2
        while trouver(posts, slug):
            slug, n = f"{base}-{n}", n + 1
        p["slug"] = slug
    # image
    vieille = p["image"]
    if ext:
        nom = f"{p['slug'][:50]}-{uuid.uuid4().hex[:6]}{ext}"
        fichier.save(IMAGES / nom)
        p["image"] = nom
    elif f.get("retirer_image"):
        p["image"] = None
    if ancien:
        posts[posts.index(ancien)] = p
    else:
        posts.append(p)
    if vieille != p["image"]:
        effacer_image(posts, vieille)
    bot.sauver(posts)
    bot.build(posts)
    flash("Article enregistré et site régénéré.")
    return redirect(url_for("liste"))


@app.post("/statut/<slug>")
def changer_statut(slug):
    posts = bot.charger()
    p = trouver(posts, slug)
    if p:
        p["statut"] = "brouillon" if p["statut"] == "publie" else "publie"
        bot.sauver(posts)
        bot.build(posts)
    return redirect(url_for("liste"))


@app.post("/supprimer/<slug>")
def supprimer(slug):
    posts = bot.charger()
    p = trouver(posts, slug)
    if p:
        posts.remove(p)
        effacer_image(posts, p.get("image"))
        bot.sauver(posts)
        bot.build(posts)
        flash("Article supprimé.")
    return redirect(url_for("liste"))


@app.post("/generer")
def generer():
    bot.build()
    flash("Site régénéré dans le dossier « site ».")
    return redirect(url_for("liste"))


@app.post("/github")
def envoyer_git():
    """Synchronise avec GitHub : pull, add, commit, push."""
    chemins = [c for c in ("data", "site", "images")
               if (bot.ROOT / c).is_dir() and any((bot.ROOT / c).iterdir())]
    try:
        etapes = [("pull", "--rebase", "--autostash"), ("add", *chemins),
                  ("commit", "-m", "Mise à jour depuis le tableau de bord"), ("push")]
        sortie = []
        for e in etapes:
            r = git(*([e] if isinstance(e, str) else e))
            texte = (r.stdout + r.stderr).strip()
            if r.returncode and "nothing to commit" in texte:
                sortie.append("Aucun changement à envoyer.")
                break
            if r.returncode:
                sortie.append(f"Échec de « git {e[0] if isinstance(e, tuple) else e} » :\n{texte}")
                break
            sortie.append(f"git {e[0] if isinstance(e, tuple) else e} : ok")
        flash("\n".join(sortie))
    except (OSError, subprocess.TimeoutExpired) as err:
        flash(f"Git indisponible : {err}")
    return redirect(url_for("liste"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
