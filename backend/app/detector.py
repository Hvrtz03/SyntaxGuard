import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

import joblib
import nltk
import pandas as pd
import spacy
from bs4 import BeautifulSoup
from rapidfuzz import fuzz
from zss import Node, simple_distance

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_PATH = BASE_DIR / "models" / "clasificador.pkl"
METRICS_PATH = BASE_DIR / "models" / "metricas.json"

MAX_CHARS = 3000
MAX_DOM_NODOS = 80
MAX_URLS = 20

SPAM_WORDS = {
    "free", "win", "winner", "won", "prize", "cash", "urgent", "click", "offer",
    "limited", "buy", "credit", "loan", "congratulations", "congrats", "claim",
    "guaranteed", "bonus", "discount", "deal", "viagra", "cheap", "money", "earn",
    "income", "subscribe", "unsubscribe", "password", "verify", "account",
    "suspended", "txt", "reward", "gift", "voucher", "ringtone", "stop", "call",
}
SHORTENERS = {
    "bit.ly", "tinyurl.com", "goo.gl", "t.co", "ow.ly", "is.gd", "buff.ly",
    "cutt.ly", "rebrand.ly", "shorturl.at", "tiny.cc",
}
LEGIT_DOMAINS = [
    "google.com", "gmail.com", "paypal.com", "amazon.com", "apple.com",
    "microsoft.com", "outlook.com", "facebook.com", "instagram.com",
    "netflix.com", "linkedin.com", "twitter.com", "github.com", "ebay.com",
    "dropbox.com", "yahoo.com", "whatsapp.com", "bankofamerica.com",
    "chase.com", "wellsfargo.com",
]
URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"']+")
IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

FEATURE_NAMES = [
    "txt_longitud", "txt_mayusculas", "txt_exclamaciones", "txt_exclam_repetidas",
    "txt_ratio_spam", "txt_n_spam", "txt_digitos", "txt_monedas",
    "pos_sustantivos", "pos_verbos", "pos_adjetivos", "pos_pronombres",
    "pos_numeros", "pos_adverbios", "pos_modales",
    "dep_prof_max", "dep_prof_media", "dep_n_oraciones", "dep_ratio_imperativas",
    "url_n", "url_long_max", "url_tiene_ip", "url_acortador",
    "url_especiales_max", "url_similitud_max", "url_lookalike",
    "dom_presente", "dom_n_nodos", "dom_profundidad", "dom_ratio_enlaces",
    "dom_distancia_ref", "dom_enlaces_enganosos", "dom_ocultos",
]


# ---------- Recursos (carga perezosa) ----------
@lru_cache(maxsize=1)
def _ensure_nltk() -> bool:
    recursos = [
        ("punkt", "tokenizers/punkt"),
        ("punkt_tab", "tokenizers/punkt_tab"),
        ("averaged_perceptron_tagger", "taggers/averaged_perceptron_tagger"),
        ("averaged_perceptron_tagger_eng", "taggers/averaged_perceptron_tagger_eng"),
    ]
    for nombre, ruta in recursos:
        try:
            nltk.data.find(ruta)
        except LookupError:
            nltk.download(nombre, quiet=True)
    return True


@lru_cache(maxsize=1)
def _get_nlp():
    try:
        return spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"])
    except OSError as e:
        raise RuntimeError(
            "Falta el modelo de spaCy. Ejecuta: python -m spacy download en_core_web_sm"
        ) from e


# ---------- Utilidades de URL ----------
def _host(url: str) -> str:
    u = url.strip()
    if not re.match(r"(?i)^[a-z][a-z0-9+.-]*://", u):
        u = "http://" + u
    try:
        return (urlparse(u).hostname or "").lower()
    except ValueError:
        return ""


def _dominio_base(host: str) -> str:
    partes = host.split(".")
    return ".".join(partes[-2:]) if len(partes) >= 2 else host


def _extraer_urls(texto: str, hrefs: list) -> list:
    urls = [u.rstrip(".,;:!?)") for u in URL_RE.findall(texto)]
    urls += [h for h in hrefs if re.match(r"(?i)^(https?://|www\.)", h.strip())]
    vistos, unicos = set(), []
    for u in urls:
        if u not in vistos:
            vistos.add(u)
            unicos.append(u)
    return unicos[:MAX_URLS]


# ---------- Rasgos de texto ----------
def _feat_texto(texto: str, palabras: list) -> dict:
    letras = [c for c in texto if c.isalpha()]
    mayus = sum(c.isupper() for c in letras)
    hits = sum(1 for w in palabras if w in SPAM_WORDS)
    return {
        "txt_longitud": float(len(texto)),
        "txt_mayusculas": mayus / max(len(letras), 1),
        "txt_exclamaciones": float(texto.count("!")),
        "txt_exclam_repetidas": float(len(re.findall(r"!{2,}", texto))),
        "txt_ratio_spam": hits / max(len(palabras), 1),
        "txt_n_spam": float(hits),
        "txt_digitos": sum(c.isdigit() for c in texto) / max(len(texto), 1),
        "txt_monedas": float(len(re.findall(r"[$£€]", texto))),
    }


# ---------- POS con NLTK ----------
def _feat_pos(tokens: list) -> dict:
    toks = tokens[:300]
    tags = [t for _, t in nltk.pos_tag(toks)] if toks else []
    n = max(len(tags), 1)

    def r(*prefijos):
        return sum(1 for t in tags if t.startswith(prefijos)) / n

    return {
        "pos_sustantivos": r("NN"), "pos_verbos": r("VB"), "pos_adjetivos": r("JJ"),
        "pos_pronombres": r("PRP"), "pos_numeros": r("CD"),
        "pos_adverbios": r("RB"), "pos_modales": r("MD"),
    }


# ---------- Dependencias con spaCy ----------
def _feat_dep(texto: str) -> dict:
    doc = _get_nlp()(texto)
    toks = [t for t in doc if not t.is_space]
    if not toks:
        return {"dep_prof_max": 0.0, "dep_prof_media": 0.0,
                "dep_n_oraciones": 0.0, "dep_ratio_imperativas": 0.0}
    profs = [sum(1 for _ in t.ancestors) for t in toks]
    sents = list(doc.sents)
    imperativas = 0
    for s in sents:
        raiz = s.root
        sin_sujeto = not any(c.dep_ in ("nsubj", "nsubjpass", "expl") for c in raiz.children)
        if raiz.tag_ == "VB" and sin_sujeto:
            imperativas += 1
    return {
        "dep_prof_max": float(max(profs)),
        "dep_prof_media": sum(profs) / len(profs),
        "dep_n_oraciones": float(len(sents)),
        "dep_ratio_imperativas": imperativas / max(len(sents), 1),
    }


# ---------- DOM + distancia de edición (zss) ----------
def _n(label, *hijos):
    nodo = Node(label)
    for h in hijos:
        nodo.addkid(h)
    return nodo


@lru_cache(maxsize=1)
def _arbol_referencia_spam() -> Node:
    """Estructura típica de correo spam HTML: tablas anidadas, enlaces con imagen,
    texto en negrita/font y bloques centrados con llamadas a la acción."""
    return _n("doc", _n("html",
        _n("head", _n("title")),
        _n("body",
            _n("table", _n("tr", _n("td", _n("a", _n("img")), _n("b"), _n("a")))),
            _n("div",
               _n("center", _n("a", _n("img")), _n("a")),
               _n("font", _n("b"), _n("a"))))))

def _construir_arbol(tag, estado: dict, prof: int = 0) -> Node:
    nodo = Node(tag.name)
    estado["n"] += 1
    estado["prof"] = max(estado["prof"], prof)
    if prof >= 10:
        return nodo
    for hijo in tag.children:
        if getattr(hijo, "name", None) and estado["n"] < MAX_DOM_NODOS:
            nodo.addkid(_construir_arbol(hijo, estado, prof + 1))
    return nodo


def _contar(nodo: Node) -> int:
    return 1 + sum(_contar(h) for h in nodo.children)


def _feat_dom(soup: BeautifulSoup) -> dict:
    raiz = Node("doc")
    estado = {"n": 0, "prof": 0}
    for hijo in soup.children:
        if getattr(hijo, "name", None) and estado["n"] < MAX_DOM_NODOS:
            raiz.addkid(_construir_arbol(hijo, estado, 1))
    ref = _arbol_referencia_spam()
    dist = simple_distance(raiz, ref, label_dist=lambda a, b: 0 if a == b else 1)
    n_nodos = _contar(raiz)
    n_enlaces = len(soup.find_all("a"))

    enganosos = 0
    for a in soup.find_all("a", href=True):
        txt = a.get_text(strip=True)
        if re.match(r"(?i)^(https?://|www\.)", txt):
            h_txt, h_href = _host(txt), _host(a["href"])
            if h_txt and h_href and _dominio_base(h_txt) != _dominio_base(h_href):
                enganosos += 1

    ocultos = len(soup.find_all(
        style=re.compile(r"display\s*:\s*none|font-size\s*:\s*0|visibility\s*:\s*hidden", re.I)
    ))
    return {
        "dom_presente": 1.0,
        "dom_n_nodos": float(n_nodos),
        "dom_profundidad": float(estado["prof"]),
        "dom_ratio_enlaces": n_enlaces / max(n_nodos, 1),
        "dom_distancia_ref": dist / max(n_nodos, _contar(ref)),
        "dom_enlaces_enganosos": float(enganosos),
        "dom_ocultos": float(ocultos),
    }


def _dom_vacio() -> dict:
    return {"dom_presente": 0.0, "dom_n_nodos": 0.0, "dom_profundidad": 0.0,
            "dom_ratio_enlaces": 0.0, "dom_distancia_ref": 1.0,
            "dom_enlaces_enganosos": 0.0, "dom_ocultos": 0.0}


# ---------- URLs ----------
def _feat_urls(urls: list) -> dict:
    f = {"url_n": float(len(urls)), "url_long_max": 0.0, "url_tiene_ip": 0.0,
         "url_acortador": 0.0, "url_especiales_max": 0.0,
         "url_similitud_max": 0.0, "url_lookalike": 0.0}
    for u in urls:
        host = _host(u)
        base = _dominio_base(host)
        f["url_long_max"] = max(f["url_long_max"], float(len(u)))
        if IP_RE.match(host):
            f["url_tiene_ip"] = 1.0
        if host in SHORTENERS or base in SHORTENERS:
            f["url_acortador"] = 1.0
        especiales = sum(1 for c in u if c in "@%~=&_") + host.count("-")
        f["url_especiales_max"] = max(f["url_especiales_max"], float(especiales))
        if base and base not in LEGIT_DOMAINS:
            sim = max(fuzz.ratio(base, legit) for legit in LEGIT_DOMAINS) / 100.0
            f["url_similitud_max"] = max(f["url_similitud_max"], sim)
            if sim >= 0.80:
                f["url_lookalike"] = 1.0
    return f


# ---------- Extracción principal ----------
def extraer_rasgos(texto: str, html: str | None = None) -> dict:
    _ensure_nltk()
    texto = texto[:MAX_CHARS]
    tokens = nltk.word_tokenize(texto)
    palabras = [t.lower() for t in tokens if t.isalpha()]

    f = {}
    f.update(_feat_texto(texto, palabras))
    f.update(_feat_pos(tokens))
    f.update(_feat_dep(texto))

    hrefs = []
    if html and html.strip():
        soup = BeautifulSoup(html, "html.parser")
        f.update(_feat_dom(soup))
        hrefs = [a["href"] for a in soup.find_all("a", href=True)]
    else:
        f.update(_dom_vacio())

    f.update(_feat_urls(_extraer_urls(texto, hrefs)))
    return f


# ---------- Explicación (rasgos_detectados) ----------
def explicar(f: dict) -> list:
    items = []

    def add(rasgo, categoria, activo, desc, siempre=False):
        if activo or siempre:
            items.append({"rasgo": rasgo, "categoria": categoria,
                          "valor": round(float(f[rasgo]), 4),
                          "activo": bool(activo), "descripcion": desc})

    add("txt_mayusculas", "texto", f["txt_mayusculas"] > 0.30,
        "Alta densidad de letras mayúsculas")
    add("txt_exclamaciones", "texto",
        f["txt_exclamaciones"] >= 3 or f["txt_exclam_repetidas"] >= 1,
        "Exceso de signos de exclamación")
    add("txt_ratio_spam", "texto", f["txt_ratio_spam"] >= 0.08,
        "Alta proporción de palabras de la lista de spam")
    add("url_tiene_ip", "url", f["url_tiene_ip"] > 0, "URL con dirección IP en lugar de dominio")
    add("url_acortador", "url", f["url_acortador"] > 0, "URL con acortador de enlaces")
    add("url_especiales_max", "url", f["url_especiales_max"] >= 3,
        "URL con muchos caracteres especiales")
    add("url_long_max", "url", f["url_long_max"] >= 75, "URL inusualmente larga")
    add("url_similitud_max", "url", f["url_lookalike"] > 0,
        "Dominio muy parecido a uno legítimo (posible suplantación)")
    if f["dom_presente"]:
        add("dom_distancia_ref", "dom", f["dom_distancia_ref"] <= 0.60,
            "Estructura DOM cercana al árbol de referencia de spam (distancia de edición zss normalizada)",
            siempre=True)
        add("dom_enlaces_enganosos", "dom", f["dom_enlaces_enganosos"] > 0,
            "Enlaces cuyo texto visible apunta a un dominio distinto del href")
        add("dom_ocultos", "dom", f["dom_ocultos"] > 0, "Elementos ocultos en el HTML")

    add("dep_prof_max", "sintactico", f["dep_prof_max"] >= 8,
        "Profundidad máxima del árbol de dependencias (spaCy)", siempre=True)
    add("dep_ratio_imperativas", "sintactico", f["dep_ratio_imperativas"] >= 0.30,
        "Alta proporción de oraciones imperativas (llamadas a la acción)", siempre=True)
    add("pos_verbos", "sintactico", f["pos_verbos"] >= 0.25,
        "Proporción de verbos según etiquetado POS (NLTK)", siempre=True)
    add("pos_pronombres", "sintactico", f["pos_pronombres"] >= 0.15,
        "Proporción de pronombres (apelación directa al lector)", siempre=True)
    add("pos_numeros", "sintactico", f["pos_numeros"] >= 0.10,
        "Alta proporción de números (precios, teléfonos, códigos)", siempre=True)
    return items


# ---------- Predictor ----------
class SpamDetector:
    def __init__(self, ruta: Path = MODEL_PATH):
        paquete = joblib.load(ruta)
        self.modelo = paquete["modelo"]
        self.feature_names = paquete["feature_names"]
        self.umbral = paquete.get("umbral", 0.5)
        self.idx_spam = list(self.modelo.classes_).index(1)
        _ensure_nltk()
        _get_nlp()

    def predecir(self, texto: str, html: str | None = None) -> dict:
        f = extraer_rasgos(texto, html)
        X = pd.DataFrame([f], columns=self.feature_names)
        proba = float(self.modelo.predict_proba(X)[0][self.idx_spam])
        return {
            "es_spam": proba >= self.umbral,
            "probabilidad": round(proba, 4),
            "rasgos_detectados": explicar(f),
        }