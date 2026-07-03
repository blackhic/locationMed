import os
import io
import re
import json
from datetime import datetime
from functools import wraps

from flask import (
    Flask, request, session, redirect, url_for,
    render_template_string, send_file, jsonify,
)
from reportlab.pdfgen import canvas
from reportlab.pdfbase.pdfmetrics import stringWidth
from pypdf import PdfReader, PdfWriter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
POSITIONS_PATH = os.path.join(BASE_DIR, "positions.json")
TEMPLATE_PDF = os.path.join(BASE_DIR, "templates", "modele_vierge.pdf")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "autobahn-dev-secret-change-me")

# Identifiants via variables d'environnement (jamais en dur dans le repo)
USERNAME = os.environ.get("USERNAME", "autobahn")
PASSWORD = os.environ.get("PASSWORD", "autobahn2024")

# --- Chargement des positions validées ---
with open(POSITIONS_PATH, encoding="utf-8") as f:
    POSITIONS = json.load(f)
RENDER = POSITIONS["render"]
FIELDS = POSITIONS["fields"]

SCALE = 72.0 / RENDER["dpi_reference"]      # 72/150
PAGE_W = RENDER["pdf_width_pt"]             # 595
PAGE_H = RENDER["pdf_height_pt"]            # 842
FONT = RENDER["font"]                       # Helvetica-Bold
FONT_SIZE = RENDER["font_size"]             # 9
COLOR = RENDER["color_rgb"]                 # [0, 0, 0.55]

# --- Organisation du formulaire ---
SECTIONS = [
    ("Identité", ["nom", "naissance", "nationalite", "adresse", "tel", "tel2"]),
    ("Documents", ["passeport", "passeport_date", "cin", "cin_expire", "permis", "permis_date"]),
    ("Véhicule + Location", ["marque", "immat", "km_depart", "km_retour", "depart",
                             "heure_depart", "retour", "heure_retour", "nbre_jours_veh",
                             "nb_jours", "prix_jour", "montant"]),
]
DATE_FIELDS = {"passeport_date", "cin_expire", "permis_date", "depart", "retour"}
TIME_FIELDS = {"heure_depart", "heure_retour"}
NUMBER_FIELDS = {"prix_jour", "km_depart", "km_retour"}
PRICE_FIELDS = {"prix_jour", "montant"}                      # rendus "X,XX"
COMPUTED_FIELDS = {"nb_jours", "nbre_jours_veh", "montant"}  # auto-calculés, lecture seule


def input_type(key):
    if key in DATE_FIELDS:
        return "date"
    if key in TIME_FIELDS:
        return "time"
    if key in NUMBER_FIELDS:
        return "number"
    if key in {"tel", "tel2"}:
        return "tel"
    return "text"


def build_form_model():
    model = []
    for title, keys in SECTIONS:
        items = []
        for k in keys:
            m = FIELDS[k]
            items.append({
                "key": k,
                "label": m.get("label", k),
                "required": bool(m.get("required")),
                "type": input_type(k),
                "readonly": k in COMPUTED_FIELDS,
            })
        model.append({"title": title, "fields": items})
    return model


def fmt_date(val):
    """AAAA-MM-JJ -> JJ/MM/AAAA (sinon renvoie tel quel)."""
    try:
        return datetime.strptime(val, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return val


def fmt_price(val):
    """Nombre (300, 300.5, "300,50") -> "300,00" (2 décimales, virgule)."""
    s = str(val).strip().replace(" ", "").replace(",", ".")
    try:
        return f"{float(s):.2f}".replace(".", ",")
    except ValueError:
        return str(val)


def build_overlay(values):
    """Dessine le texte aux coordonnées de positions.json sur un calque PDF."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE_W, PAGE_H))
    c.setFont(FONT, FONT_SIZE)
    c.setFillColorRGB(COLOR[0], COLOR[1], COLOR[2])
    for key, meta in FIELDS.items():
        val = values.get(key)
        if val is None:
            continue
        val = str(val).strip()
        if not val:
            continue
        if key in DATE_FIELDS:
            val = fmt_date(val)
        elif key in PRICE_FIELDS:
            val = fmt_price(val)
        elif key == "nb_jours":
            val = f"{val} (J)"
        y_pt = PAGE_H - meta["y"] * SCALE
        if meta.get("align") == "center" and "cell" in meta:
            x1, x2 = meta["cell"]
            center = (x1 + x2) / 2.0 * SCALE
            w = stringWidth(val, FONT, FONT_SIZE)
            c.drawString(center - w / 2.0, y_pt, val)
        else:
            c.drawString(meta["x"] * SCALE, y_pt, val)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf


def generate_pdf(values):
    """Fusionne le calque sur la page 1 du modèle, conserve la page 2."""
    overlay = PdfReader(build_overlay(values))
    base = PdfReader(TEMPLATE_PDF)
    writer = PdfWriter()
    page1 = base.pages[0]
    page1.merge_page(overlay.pages[0])
    writer.add_page(page1)
    for p in base.pages[1:]:      # page 2 = conditions générales, inchangée
        writer.add_page(p)
    out = io.BytesIO()
    writer.write(out)
    out.seek(0)
    return out


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return wrapper


@app.route("/")
def login_page():
    if session.get("logged_in"):
        return redirect(url_for("contrat_page"))
    return render_template_string(LOGIN_HTML)


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or request.form
    u = (data.get("username") or "").strip()
    p = data.get("password") or ""
    if u == USERNAME and p == PASSWORD:
        session["logged_in"] = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Identifiants incorrects"}), 401


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/contrat")
@login_required
def contrat_page():
    return render_template_string(CONTRAT_HTML, sections=build_form_model())


@app.route("/api/generate", methods=["POST"])
@login_required
def api_generate():
    values = request.get_json(silent=True) or request.form.to_dict()
    # Date du jour "Meknès le JJ / MM / AAAA" — injectée côté serveur, hors formulaire
    now = datetime.now()
    values["ville_jour"] = now.strftime("%d")
    values["ville_mois"] = now.strftime("%m")
    values["ville_annee"] = now.strftime("%Y")
    missing = [k for k, m in FIELDS.items()
               if m.get("required") and not str(values.get(k, "")).strip()]
    if missing:
        return jsonify({"ok": False, "error": "Champs obligatoires manquants",
                        "missing": missing}), 400
    pdf = generate_pdf(values)
    nom = re.sub(r"[^A-Za-z0-9_-]+", "_", (values.get("nom") or "contrat").strip()) or "contrat"
    return send_file(pdf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"contrat_autobahn_{nom}.pdf")


# ============================= TEMPLATES =============================
LOGIN_HTML = """<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AUTOBAHN — Connexion</title>
<style>
:root{--navy:#0d1b2a;--gold:#c8a951;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:var(--navy);
  color:#fff;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px}
.card{width:100%;max-width:380px;background:#11243a;border:1px solid rgba(200,169,81,.3);
  border-radius:16px;padding:32px 24px;box-shadow:0 10px 40px rgba(0,0,0,.4)}
.brand{text-align:center;margin-bottom:28px}
.brand h1{font-size:30px;letter-spacing:4px;color:var(--gold);font-weight:800}
.brand .stars{color:var(--gold);letter-spacing:6px;font-size:14px;margin-top:4px}
.brand p{color:#9db0c4;font-size:12px;margin-top:6px;letter-spacing:1px}
label{display:block;font-size:13px;color:#9db0c4;margin:14px 0 6px}
input{width:100%;padding:13px 14px;border-radius:10px;border:1px solid #274056;
  background:#0b1725;color:#fff;font-size:16px}
input:focus{outline:none;border-color:var(--gold)}
button{width:100%;margin-top:24px;padding:14px;border:none;border-radius:10px;
  background:var(--gold);color:var(--navy);font-size:16px;font-weight:700;cursor:pointer}
button:active{opacity:.85}
.err{color:#ff6b6b;font-size:13px;text-align:center;margin-top:14px;min-height:18px}
</style></head><body>
<div class="card">
  <div class="brand"><h1>AUTOBAHN</h1><div class="stars">★ ★ ★</div>
    <p>CONTRAT DE LOCATION</p></div>
  <form id="f">
    <label>Identifiant</label>
    <input name="username" autocomplete="username" required>
    <label>Mot de passe</label>
    <input name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Se connecter</button>
    <div class="err" id="err"></div>
  </form>
</div>
<script>
document.getElementById('f').addEventListener('submit', async e=>{
  e.preventDefault();
  const fd=new FormData(e.target);
  const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:fd.get('username'),password:fd.get('password')})});
  const j=await r.json();
  if(j.ok){location.href='/contrat';}
  else{document.getElementById('err').textContent=j.error||'Erreur';}
});
</script></body></html>"""

CONTRAT_HTML = """<!doctype html>
<html lang="fr"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>AUTOBAHN — Nouveau contrat</title>
<style>
:root{--navy:#0d1b2a;--gold:#c8a951;}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;background:#0b1725;color:#fff;padding-bottom:90px}
header{background:var(--navy);border-bottom:1px solid rgba(200,169,81,.3);padding:16px 18px;
  display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
header h1{font-size:20px;letter-spacing:3px;color:var(--gold);font-weight:800}
header a{color:#9db0c4;font-size:13px;text-decoration:none}
.wrap{max-width:640px;margin:0 auto;padding:16px}
.section{background:#11243a;border:1px solid rgba(200,169,81,.2);border-radius:14px;
  padding:16px;margin-bottom:16px}
.section h2{font-size:14px;color:var(--gold);letter-spacing:1px;text-transform:uppercase;
  margin-bottom:12px;border-bottom:1px solid rgba(200,169,81,.2);padding-bottom:8px}
.field{margin-bottom:12px}
.field label{display:block;font-size:12px;color:#9db0c4;margin-bottom:5px}
.req{color:#ff5c5c;margin-left:3px}
.field input{width:100%;padding:12px;border-radius:9px;border:1px solid #274056;
  background:#0b1725;color:#fff;font-size:16px}
.field input:focus{outline:none;border-color:var(--gold)}
.field input.invalid{border-color:#ff5c5c;background:#2a1315}
.field input[readonly]{background:#16283d;color:var(--gold);font-weight:700}
.bar{position:fixed;bottom:0;left:0;right:0;background:var(--navy);
  border-top:1px solid rgba(200,169,81,.3);padding:14px 16px}
.bar button{width:100%;max-width:640px;margin:0 auto;display:block;padding:15px;border:none;
  border-radius:11px;background:var(--gold);color:var(--navy);font-size:16px;font-weight:700;cursor:pointer}
.bar button:disabled{opacity:.6}
.bar .msg{max-width:640px;margin:6px auto 0;text-align:center;font-size:13px;color:#ff6b6b;min-height:16px}
</style></head><body>
<header><h1>AUTOBAHN ★★★</h1><a href="/logout">Déconnexion</a></header>
<div class="wrap">
  <form id="contrat">
  {% for sec in sections %}
    <div class="section">
      <h2>{{ sec.title }}</h2>
      {% for f in sec.fields %}
        <div class="field">
          <label for="{{f.key}}">{{ f.label }}{% if f.required %}<span class="req">*</span>{% endif %}</label>
          <input id="{{f.key}}" name="{{f.key}}" type="{{f.type}}"
            {% if f.required %}data-required="1"{% endif %}
            {% if f.readonly %}readonly{% endif %}
            {% if f.type=='number' %}inputmode="decimal" min="0"{% endif %}>
        </div>
      {% endfor %}
    </div>
  {% endfor %}
  </form>
</div>
<div class="bar">
  <button id="gen" type="button">Générer le contrat PDF</button>
  <div class="msg" id="msg"></div>
</div>
<script>
const $=id=>document.getElementById(id);
function days(){
  const d=$('depart').value, r=$('retour').value;
  if(!d||!r)return 0;
  const diff=(new Date(r)-new Date(d))/86400000;
  return diff>0?Math.round(diff):0;
}
function recalc(){
  const n=days();
  if(n>0){$('nb_jours').value=n;$('nbre_jours_veh').value=n;}
  else{$('nb_jours').value='';$('nbre_jours_veh').value='';}
  const p=parseFloat($('prix_jour').value);
  const nb=parseInt($('nb_jours').value);
  $('montant').value=(p>0&&nb>0)?(p*nb).toFixed(2).replace('.',','):'';
}
['depart','retour','prix_jour'].forEach(k=>{
  const el=$(k); if(el) el.addEventListener('input',recalc);
});
$('gen').addEventListener('click', async ()=>{
  const form=$('contrat'); const data={}; let firstBad=null;
  form.querySelectorAll('input').forEach(i=>{
    i.classList.remove('invalid');
    data[i.name]=i.value;
    if(i.dataset.required && !i.value.trim()){
      i.classList.add('invalid'); if(!firstBad)firstBad=i;
    }
  });
  if(firstBad){
    $('msg').textContent='Merci de remplir les champs obligatoires (*).';
    firstBad.scrollIntoView({behavior:'smooth',block:'center'}); return;
  }
  $('msg').textContent='';
  const btn=$('gen'); btn.textContent='Génération…'; btn.disabled=true;
  try{
    const res=await fetch('/api/generate',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
    if(!res.ok){const e=await res.json();$('msg').textContent=e.error||'Erreur';return;}
    const blob=await res.blob();
    const cd=res.headers.get('Content-Disposition')||'';
    const m=cd.match(/filename="?([^"]+)"?/);
    const a=document.createElement('a');
    a.href=URL.createObjectURL(blob);
    a.download=m?m[1]:'contrat_autobahn.pdf';
    document.body.appendChild(a); a.click(); a.remove();
  }catch(err){$('msg').textContent='Erreur réseau';}
  finally{btn.textContent='Générer le contrat PDF';btn.disabled=false;}
});
</script></body></html>"""


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
