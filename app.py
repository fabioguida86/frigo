"""Frigo AI — inventario di frigo, freezer e dispensa a partire da foto.

Fonti di inserimento:
  * Scontrino      -> l'AI elenca i prodotti e STIMA la scadenza (data acquisto + durata tipica).
  * Codice a barre -> il codice viene decodificato in locale, il prodotto cercato su Open Food Facts;
                      con la foto della data stampata l'AI legge la scadenza REALE.
  * Manuale

Avvio:  streamlit run app.py
Dati:   salvati nel localStorage del browser di ogni utente (componenti/archivio), con backup scaricabile.
Chiave: ogni utente collega la PROPRIA chiave Gemini dall'app (con consenso esplicito).
        La chiave non viene salvata sul server: resta nella sessione e, se l'utente lo sceglie,
        in un cookie del suo browser. Lo sviluppatore non paga le chiamate AI degli utenti.
Opzionale in .streamlit/secrets.toml:  GEMINI_MODEL = "gemini-2.5-flash"
"""
import calendar
import html
import json
import os
import re
import typing
import uuid
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from PIL import Image, ImageOps
from pydantic import BaseModel

# =============================================================================
# CONFIGURAZIONE
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent
# I dati di ogni utente vivono nel localStorage del SUO browser: nessun dato personale sul server
# (e su Streamlit Cloud il disco del server viene comunque azzerato a ogni riavvio).
CHIAVE_ARCHIVIO = "frigo_ai_db"
_archivio_browser = components.declare_component("archivio_browser", path=str(BASE_DIR / "componenti" / "archivio"))


def leggi_segreto(nome: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if nome in st.secrets:
            return st.secrets[nome]
    except Exception:  # nessun secrets.toml presente
        pass
    return os.environ.get(nome, default)


# Di proposito NON si legge nessuna chiave dai secrets: ogni utente usa la propria.
MODELLO = leggi_segreto("GEMINI_MODEL", "gemini-2.5-flash")

# categoria -> (icona, luogo predefinito, giorni di conservazione tipici da chiuso)
CATEGORIE: dict[str, tuple[str, str, int]] = {
    "Latticini": ("🥛", "frigo", 7),
    "Formaggi": ("🧀", "frigo", 20),
    "Carne": ("🥩", "frigo", 3),
    "Pesce": ("🐟", "frigo", 2),
    "Salumi": ("🥓", "frigo", 10),
    "Uova": ("🥚", "frigo", 28),
    "Verdura": ("🥦", "frigo", 5),
    "Frutta": ("🍎", "dispensa", 7),
    "Pasta fresca": ("🥟", "frigo", 14),
    "Pane e forno": ("🥖", "dispensa", 3),
    "Pasta, riso e cereali": ("🍝", "dispensa", 365),
    "Conserve e salse": ("🥫", "dispensa", 365),
    "Dolci e snack": ("🍪", "dispensa", 120),
    "Surgelati": ("🧊", "freezer", 180),
    "Bevande": ("🥤", "dispensa", 180),
    "Alcolici": ("🍷", "dispensa", 1000),
    "Altro": ("📦", "dispensa", 30),
}
LUOGHI = ["frigo", "freezer", "dispensa"]
NOMI_LUOGHI = {"frigo": "Frigo", "freezer": "Freezer", "dispensa": "Dispensa"}
GIORNI_FREEZER = 90  # durata stimata di un prodotto fresco una volta congelato

# Parole chiave per ricondurre categorie libere (vecchio database) a quelle fisse
PAROLE_CATEGORIA = {
    "pasta fresca": "Pasta fresca", "formagg": "Formaggi", "latt": "Latticini", "yogurt": "Latticini",
    "salum": "Salumi", "carn": "Carne", "pesc": "Pesce", "uov": "Uova", "verdur": "Verdura",
    "frutt": "Frutta", "pane": "Pane e forno", "pasta": "Pasta, riso e cereali",
    "cereal": "Pasta, riso e cereali", "riso": "Pasta, riso e cereali", "salsa": "Conserve e salse",
    "condiment": "Conserve e salse", "conserv": "Conserve e salse", "dolc": "Dolci e snack",
    "biscott": "Dolci e snack", "snack": "Dolci e snack", "surgel": "Surgelati", "alcol": "Alcolici",
    "vino": "Alcolici", "birr": "Alcolici", "bevand": "Bevande",
}


def normalizza_categoria(testo: str) -> str:
    if testo in CATEGORIE:
        return testo
    t = str(testo).lower()
    for parola, cat in PAROLE_CATEGORIA.items():
        if parola in t:
            return cat
    return "Altro"


# =============================================================================
# DATABASE (file JSON, scrittura atomica, riletto a ogni esecuzione)
# =============================================================================
def db_vuoto() -> dict:
    return {"versione": 4, "prodotti": [], "lista_spesa": []}


def nuovo_prodotto(nome, categoria="Altro", luogo=None, qta=1, scadenza=None,
                   tipo_scadenza="stimata", marca=None, codice=None) -> dict:
    categoria = normalizza_categoria(categoria)
    return {
        "id": uuid.uuid4().hex[:12],
        "nome": str(nome).strip() or "Senza nome",
        "marca": marca or None,
        "qta": max(1, int(qta or 1)),
        "categoria": categoria,
        "luogo": luogo if luogo in LUOGHI else CATEGORIE[categoria][1],
        "scadenza": scadenza.isoformat() if isinstance(scadenza, date) else scadenza,
        "tipo_scadenza": tipo_scadenza,  # "reale" (letta sulla confezione) | "stimata"
        "codice": codice or None,
        "aggiunto": date.today().isoformat(),
    }


def converti_vecchio(vecchio: dict) -> dict:
    """Importa il formato del vecchio dispensa_v3.json."""
    db = db_vuoto()
    for chiave, luogo in (("d", None), ("c", "freezer")):
        for v in vecchio.get(chiave, []):
            qta = re.findall(r"\d+", str(v.get("qta", "1")))
            # la vecchia "scad" era un numero di giorni senza data di riferimento: non è recuperabile
            db["prodotti"].append(nuovo_prodotto(v.get("nome", "?"), v.get("cat", "Altro"), luogo,
                                                 int(qta[0]) if qta else 1))
    db["lista_spesa"] = [{"id": uuid.uuid4().hex[:12], "testo": t, "fatto": False}
                         for t in vecchio.get("l", [])]
    return db


def pulisci_db(grezzo) -> dict:
    """Valida dati che arrivano dal browser o da un file di backup: non sono fidati."""
    if not isinstance(grezzo, dict):
        raise ValueError("formato non riconosciuto")
    if "prodotti" not in grezzo and ("d" in grezzo or "c" in grezzo):
        return converti_vecchio(grezzo)  # vecchio dispensa_v3.json
    if not isinstance(grezzo.get("prodotti"), list):
        raise ValueError("formato non riconosciuto")
    db, visti = db_vuoto(), set()
    for p in grezzo["prodotti"]:
        if not isinstance(p, dict) or not str(p.get("nome") or "").strip():
            continue
        try:
            qta = int(p.get("qta") or 1)
        except (TypeError, ValueError):
            qta = 1
        tipo = p.get("tipo_scadenza") if p.get("tipo_scadenza") in ("reale", "stimata") else "stimata"
        nuovo = nuovo_prodotto(str(p["nome"])[:120], str(p.get("categoria") or "Altro"), p.get("luogo"),
                               min(qta, 999), parse_data(p.get("scadenza")), tipo,
                               str(p.get("marca") or "")[:80] or None, str(p.get("codice") or "")[:40] or None)
        pid = str(p.get("id") or "")
        if re.fullmatch(r"[\w-]{1,40}", pid) and pid not in visti:
            nuovo["id"] = pid
        visti.add(nuovo["id"])
        if aggiunto := parse_data(p.get("aggiunto")):
            nuovo["aggiunto"] = aggiunto.isoformat()
        db["prodotti"].append(nuovo)
    for v in grezzo.get("lista_spesa") or []:
        if isinstance(v, dict) and str(v.get("testo") or "").strip():
            db["lista_spesa"].append({"id": uuid.uuid4().hex[:12], "testo": str(v["testo"])[:120],
                                      "fatto": bool(v.get("fatto"))})
    return db


def leggi_backup(testo: str) -> dict:
    return pulisci_db(json.loads(testo))


def sincronizza_archivio() -> None:
    """Al primo caricamento legge i dati dal browser; poi li riscrive ogni volta che cambiano."""
    nonce = st.session_state.get("_db_nonce", 0)
    da_scrivere = "db" in st.session_state and nonce > st.session_state.get("_db_ack", 0)
    risposta = _archivio_browser(
        chiave=CHIAVE_ARCHIVIO, nonce=nonce, key="archivio", default=None,
        scrivi=json.dumps(st.session_state.db, ensure_ascii=False) if da_scrivere else None)
    if risposta is None:
        if "db" not in st.session_state:  # il browser non ha ancora risposto
            st.info("⏳ Caricamento dei tuoi dati...")
            st.stop()
        return
    if "db" not in st.session_state:
        if risposta.get("errore"):
            st.session_state._avviso_archivio = ("Questo browser non permette di salvare i dati "
                                                 "(navigazione privata?). Scarica un backup prima di chiudere.")
        try:
            st.session_state.db = leggi_backup(risposta["valore"]) if risposta.get("valore") else db_vuoto()
        except ValueError:
            st.session_state.db = db_vuoto()
            st.session_state._avviso_archivio = "I dati salvati in questo browser erano illeggibili."
    if risposta.get("nonce", 0) > st.session_state.get("_db_ack", 0):
        st.session_state._db_ack = risposta["nonce"]


def salva_db(db: dict) -> None:
    st.session_state.db = db
    st.session_state._db_nonce = st.session_state.get("_db_nonce", 0) + 1


def aggiungi_a_lista(db: dict, testo: str) -> bool:
    testo = testo.strip()
    if not testo or any(x["testo"].lower() == testo.lower() and not x["fatto"] for x in db["lista_spesa"]):
        return False
    db["lista_spesa"].append({"id": uuid.uuid4().hex[:12], "testo": testo, "fatto": False})
    return True


# =============================================================================
# DATE
# =============================================================================
def parse_data(valore) -> Optional[date]:
    if valore is None or (not isinstance(valore, str) and pd.isna(valore)):
        return None
    if isinstance(valore, datetime):
        return valore.date()
    if isinstance(valore, date):
        return valore
    try:
        return date.fromisoformat(str(valore).strip()[:10])
    except ValueError:
        return None


def giorni_mancanti(p: dict) -> Optional[int]:
    d = parse_data(p.get("scadenza"))
    return None if d is None else (d - date.today()).days


def badge(giorni: Optional[int], tipo: str) -> tuple[str, str]:
    stima = "~" if tipo == "stimata" else ""
    if giorni is None:
        return "?", "#757575"
    if giorni < 0:
        return f"Scaduto da {-giorni} gg", "#c62828"
    if giorni == 0:
        return "Scade oggi", "#c62828"
    if giorni == 1:
        return f"{stima}Domani", "#ef6c00"
    if giorni <= 3:
        return f"{stima}{giorni} gg", "#ef6c00"
    return f"{stima}{giorni} gg", "#2e7d32"


# =============================================================================
# CODICI A BARRE (decodifica locale + standard GS1 + Open Food Facts)
# =============================================================================
def apri_immagine(file) -> Image.Image:
    return ImageOps.exif_transpose(Image.open(file)).convert("RGB")


def ridimensiona(img: Image.Image, lato: int = 1600) -> Image.Image:
    copia = img.copy()
    copia.thumbnail((lato, lato))
    return copia


def leggi_codici(img: Image.Image) -> list[tuple[str, str]]:
    """Restituisce [(tipo, contenuto)] dei codici trovati nella foto."""
    grigio = img.convert("L")
    trovati: list[tuple[str, str]] = []
    try:
        from pyzbar.pyzbar import decode
        for versione in (grigio, ridimensiona(grigio, 1600)):
            trovati = [(c.type, c.data.decode("utf-8", "replace")) for c in decode(versione)]
            if trovati:
                return trovati
    except Exception:
        pass
    try:  # piano B: rilevatore di OpenCV
        import cv2
        import numpy as np
        ok, testi, tipi, _ = cv2.barcode.BarcodeDetector().detectAndDecodeWithType(np.array(grigio))
        if ok:
            trovati = [(t, s) for s, t in zip(testi, tipi) if s]
    except Exception:
        pass
    return trovati


def _data_gs1(aammgg: str) -> Optional[date]:
    if not re.fullmatch(r"\d{6}", aammgg or ""):
        return None
    anno, mese, giorno = 2000 + int(aammgg[:2]), int(aammgg[2:4]), int(aammgg[4:])
    if not 1 <= mese <= 12:
        return None
    if giorno == 0:  # GS1: giorno 00 = fine mese
        giorno = calendar.monthrange(anno, mese)[1]
    try:
        return date(anno, mese, giorno)
    except ValueError:
        return None


def analizza_gs1(testo: str) -> dict:
    """Estrae GTIN e scadenza da codici GS1 (GS1-128, DataBar, QR Digital Link).
    AI 17 = da consumarsi entro, AI 15 = da consumarsi preferibilmente entro."""
    campi: dict[str, str] = {}
    s = re.sub(r"^\][A-Za-z]\d", "", testo.strip())  # identificatore di simbologia (]C1, ]e0, ...)
    if "/01/" in s:  # GS1 Digital Link: https://.../01/<gtin>/...?17=AAMMGG
        if m := re.search(r"/01/(\d{14})", s):
            campi["01"] = m.group(1)
        for ai in ("17", "15"):
            if m := re.search(rf"[/?&]{ai}[=/](\d{{6}})", s):
                campi[ai] = m.group(1)
    elif "(" in s:  # forma leggibile: (01)0801...(17)261130
        campi = dict(re.findall(r"\((\d{2,4})\)([^(]+)", s))
    elif re.match(r"^(01|02)\d{14}", s):  # stringa grezza con separatore FNC1 (\x1d)
        fissi = {"00": 18, "01": 14, "02": 14, "11": 6, "12": 6, "13": 6, "15": 6, "16": 6, "17": 6, "20": 2}
        i = 0
        while i < len(s):
            if s[i] == "\x1d":
                i += 1
                continue
            ai = s[i:i + 2]
            if ai in fissi:
                campi[ai] = s[i + 2:i + 2 + fissi[ai]]
                i += 2 + fissi[ai]
            elif ai in ("31", "32", "33", "34", "35", "36"):  # pesi/misure: AI di 4 cifre + 6
                campi[s[i:i + 4]] = s[i + 4:i + 10]
                i += 10
            else:  # lunghezza variabile fino al separatore
                j = s.find("\x1d", i + 2)
                j = len(s) if j < 0 else j
                campi[ai] = s[i + 2:j]
                i = j
    risultato: dict = {}
    gtin = campi.get("01") or campi.get("02")
    if gtin:
        risultato["gtin"] = gtin.strip()
    for ai, tipo in (("17", "entro"), ("15", "preferibilmente")):
        if d := _data_gs1(campi.get(ai, "").strip()):
            risultato["scadenza"], risultato["tipo"] = d, tipo
            break
    return risultato


def estrai_ean(codici: list[tuple[str, str]]) -> tuple[Optional[str], Optional[date]]:
    """Dai codici letti ricava (codice prodotto, eventuale scadenza GS1)."""
    ean, scadenza = None, None
    for _, contenuto in codici:
        gs1 = analizza_gs1(contenuto)
        if gs1.get("scadenza") and not scadenza:
            scadenza = gs1["scadenza"]
        if gs1.get("gtin") and not ean:
            ean = gs1["gtin"]
        elif re.fullmatch(r"\d{8}|\d{12,14}", contenuto) and not ean:
            ean = contenuto
    if ean and len(ean) == 14 and ean.startswith("0"):
        ean = ean[1:]  # GTIN-14 -> EAN-13
    return ean, scadenza


@st.cache_data(ttl=7 * 24 * 3600, show_spinner=False)
def cerca_open_food_facts(codice: str) -> Optional[dict]:
    try:
        r = requests.get(
            f"https://world.openfoodfacts.org/api/v2/product/{codice}.json",
            params={"fields": "product_name_it,product_name,brands,categories,categories_tags,quantity"},
            headers={"User-Agent": "FrigoAI/1.0 (app personale)"},
            timeout=8,
        )
        dati = r.json() if r.ok else {}
    except (requests.RequestException, ValueError):
        return None
    return dati.get("product") if dati.get("status") == 1 else None


# Tag delle categorie di Open Food Facts (in inglese) -> categorie dell'app. L'ordine conta.
OFF_CATEGORIE = [
    ("frozen", "Surgelati"), ("cheese", "Formaggi"), ("yogurt", "Latticini"), ("milk", "Latticini"),
    ("dairies", "Latticini"), ("cream", "Latticini"), ("butter", "Latticini"), ("eggs", "Uova"),
    ("ham", "Salumi"), ("sausage", "Salumi"), ("salami", "Salumi"), ("prepared-meats", "Salumi"),
    ("meat", "Carne"), ("poultr", "Carne"), ("fish", "Pesce"), ("seafood", "Pesce"),
    ("fresh-pasta", "Pasta fresca"), ("pasta", "Pasta, riso e cereali"), ("rice", "Pasta, riso e cereali"),
    ("cereal", "Pasta, riso e cereali"), ("flour", "Pasta, riso e cereali"), ("bread", "Pane e forno"),
    ("sweet-spread", "Dolci e snack"), ("hazelnut", "Dolci e snack"), ("cocoa", "Dolci e snack"),
    ("biscuit", "Dolci e snack"), ("chocolate", "Dolci e snack"), ("snack", "Dolci e snack"),
    ("confection", "Dolci e snack"), ("dessert", "Dolci e snack"), ("cake", "Dolci e snack"),
    ("sauce", "Conserve e salse"), ("pesto", "Conserve e salse"), ("condiment", "Conserve e salse"),
    ("canned", "Conserve e salse"), ("spread", "Conserve e salse"), ("oil", "Conserve e salse"),
    ("alcoholic", "Alcolici"), ("wine", "Alcolici"), ("beer", "Alcolici"), ("spirit", "Alcolici"),
    ("juice", "Bevande"), ("water", "Bevande"), ("beverage", "Bevande"), ("drink", "Bevande"),
    ("fruit", "Frutta"), ("vegetable", "Verdura"),
]


def categoria_da_off(off: dict) -> str:
    for tag in reversed(off.get("categories_tags") or []):  # dal più specifico al più generico
        t = tag.split(":", 1)[-1]
        if t.startswith("plant-based-foods"):
            continue
        for parola, categoria in OFF_CATEGORIE:
            if parola in t:
                return categoria
    return normalizza_categoria(off.get("categories") or "")


def dati_off(off: dict) -> tuple[str, Optional[str], str]:
    """(nome, marca, categoria) da un prodotto di Open Food Facts."""
    nome = (off.get("product_name_it") or off.get("product_name") or "").strip()
    quantita = (off.get("quantity") or "").strip()
    if nome and quantita and quantita not in nome:
        nome = f"{nome} {quantita}"
    marca = (off.get("brands") or "").split(",")[0].strip() or None
    return nome or "Prodotto senza nome", marca, categoria_da_off(off)


def ean_valido(codice: str) -> bool:
    if not re.fullmatch(r"\d{8}|\d{12,14}", codice or ""):
        return False
    cifre = [int(c) for c in codice]
    controllo = cifre.pop()
    somma = sum(c * (3 if i % 2 == 0 else 1) for i, c in enumerate(reversed(cifre)))
    return (10 - somma % 10) % 10 == controllo


# =============================================================================
# GEMINI (output JSON strutturato)
# =============================================================================
Categoria = Enum("Categoria", [(re.sub(r"\W+", "_", k).upper(), k) for k in CATEGORIE], type=str)
Luogo = Enum("Luogo", [(k.upper(), k) for k in LUOGHI], type=str)


class ArticoloScontrino(BaseModel):
    testo_scontrino: str
    nome: str
    quantita: int
    categoria: Categoria
    luogo: Luogo
    giorni_conservazione: int


class Scontrino(BaseModel):
    data_acquisto: Optional[str]
    articoli: list[ArticoloScontrino]


class ProdottoFoto(BaseModel):
    alimento: bool
    nome: str
    marca: Optional[str]
    codice_a_barre: Optional[str]
    categoria: Categoria
    luogo: Luogo
    data_scadenza: Optional[str]
    giorni_conservazione: int


# -----------------------------------------------------------------------------
# Chiave Gemini dell'utente (mai salvata sul server)
# -----------------------------------------------------------------------------
COOKIE_CHIAVE = "frigo_ai_gemini"
FORMATO_CHIAVE = re.compile(r"[A-Za-z0-9_\-.]{20,200}")  # impedisce anche l'iniezione nello script del cookie
LINK_CHIAVE = "https://aistudio.google.com/apikey"


def chiave_utente() -> Optional[str]:
    if "gemini_key" not in st.session_state:  # primo caricamento: guarda se il browser la ricorda
        try:
            dal_cookie = st.context.cookies.get(COOKIE_CHIAVE)
        except Exception:
            dal_cookie = None
        valida = isinstance(dal_cookie, str) and FORMATO_CHIAVE.fullmatch(dal_cookie)
        st.session_state.gemini_key = dal_cookie if valida else None
    return st.session_state.gemini_key


def client_gemini() -> genai.Client:
    chiave = chiave_utente()
    if not chiave:
        raise RuntimeError("Nessuna chiave Gemini collegata.")
    # un client per sessione: le chiavi degli utenti non finiscono in cache condivise
    salvato = st.session_state.get("_client")
    if not salvato or salvato[0] != chiave:
        salvato = (chiave, genai.Client(api_key=chiave))
        st.session_state._client = salvato
    return salvato[1]


def programma_cookie(valore: Optional[str]) -> None:
    """Il cookie viene scritto dal browser al caricamento successivo (vedi applica_cookie)."""
    st.session_state._cookie_da_scrivere = valore or ""


def applica_cookie() -> None:
    if "_cookie_da_scrivere" not in st.session_state:
        return
    valore = st.session_state.pop("_cookie_da_scrivere")
    if valore and not FORMATO_CHIAVE.fullmatch(valore):
        return
    durata = 365 * 24 * 3600 if valore else 0  # 0 = cancella
    st.html(f"""<script>
document.cookie = "{COOKIE_CHIAVE}=" + {json.dumps(valore)} + "; max-age={durata}; path=/; SameSite=Strict"
  + (location.protocol === "https:" ? "; Secure" : "");
</script>""", unsafe_allow_javascript=True)


def scollega_chiave() -> None:
    st.session_state.gemini_key = None
    st.session_state.pop("_client", None)
    programma_cookie(None)


def pannello_chiave(prefisso: str) -> None:
    """Richiesta di collegamento della chiave, con consenso esplicito."""
    with st.container(border=True):
        st.markdown("#### 🔑 Collega la tua AI Gemini")
        st.markdown(
            "Le funzioni AI usano la **tua chiave personale Gemini**, gratuita entro la quota giornaliera di Google.\n"
            f"1. Apri **[Google AI Studio]({LINK_CHIAVE})** e accedi con il tuo account Google\n"
            "2. Premi **Create API key** e copia la chiave\n"
            "3. Incollala qui sotto")
        with st.form(f"chiave_{prefisso}"):
            chiave = st.text_input("La tua chiave Gemini", type="password", placeholder="AIza...")
            with st.expander("ℹ️ Come viene usata la chiave"):
                st.markdown(
                    "- Serve solo a inviare a Google le foto e le richieste che fai tu, **a tuo nome e sulla "
                    "tua quota**.\n"
                    "- **Non viene salvata sul server** dell'app: resta in memoria finché la pagina è aperta.\n"
                    "- Se scegli *Ricorda su questo dispositivo*, viene conservata in un cookie di questo "
                    "browser per 12 mesi. Puoi cancellarla in ogni momento dal menu laterale (**Scollega**).\n"
                    "- Con il piano gratuito di Gemini, Google può usare i contenuti inviati per migliorare "
                    "i propri servizi: evita di fotografare dati personali.\n"
                    f"- Puoi revocare la chiave quando vuoi da [Google AI Studio]({LINK_CHIAVE}).")
            ricorda = st.checkbox("Ricorda su questo dispositivo")
            consenso = st.checkbox("Ho letto come viene usata la chiave e acconsento")
            if st.form_submit_button("Collega", type="primary"):
                chiave = chiave.strip()
                if not consenso:
                    st.error("Per collegare la chiave serve il tuo consenso.")
                elif not FORMATO_CHIAVE.fullmatch(chiave):
                    st.error("Questa non sembra una chiave Gemini valida.")
                else:
                    # il client va tenuto in una variabile: se viene distrutto si chiude la connessione
                    client = genai.Client(api_key=chiave)
                    try:
                        with st.spinner("Verifico la chiave..."):
                            client.models.get(model=MODELLO)
                    except Exception as e:
                        st.error(f"Google ha rifiutato la chiave: {str(e)[:200]}")
                    else:
                        st.session_state.gemini_key = chiave
                        st.session_state._client = (chiave, client)
                        if ricorda:
                            programma_cookie(chiave)
                        st.rerun()


def _json_dal_testo(testo: str, schema: type[BaseModel]) -> BaseModel:
    """Estrae e ripara il JSON da una risposta di testo libero (modelli senza modalità JSON)."""
    inizio, fine = (testo or "").find("{"), (testo or "").rfind("}")
    if inizio < 0 or fine <= inizio:
        raise ValueError("l'AI non ha restituito dati leggibili, riprova.")
    dati = json.loads(testo[inizio:fine + 1])

    def ripara(oggetto, modello: type[BaseModel]):
        if not isinstance(oggetto, dict):
            return
        for nome, campo in modello.model_fields.items():
            if type(None) in typing.get_args(campo.annotation):
                oggetto.setdefault(nome, None)  # campi facoltativi omessi dal modello
        if "categoria" in oggetto:
            oggetto["categoria"] = normalizza_categoria(str(oggetto["categoria"]))
        if "luogo" in oggetto:
            luogo = str(oggetto["luogo"]).lower()
            oggetto["luogo"] = luogo if luogo in LUOGHI else "dispensa"
        if modello is Scontrino:
            for articolo in oggetto.get("articoli") or []:
                ripara(articolo, ArticoloScontrino)

    ripara(dati, schema)
    return schema.model_validate(dati)


def chiedi_gemini(contenuti: list, schema: Optional[type[BaseModel]] = None):
    client = client_gemini()
    if schema is None:
        config = types.GenerateContentConfig(temperature=0.2)
        return client.models.generate_content(model=MODELLO, contents=contenuti, config=config).text
    try:
        config = types.GenerateContentConfig(temperature=0.2, response_mime_type="application/json",
                                             response_schema=schema)
        risposta = client.models.generate_content(model=MODELLO, contents=contenuti, config=config)
        return risposta.parsed if isinstance(risposta.parsed, schema) else schema.model_validate_json(risposta.text)
    except genai_errors.ClientError as e:
        messaggio = str(e).lower()
        if not any(x in messaggio for x in ("json mode", "response_schema", "response schema", "mime")):
            raise
    # Il modello non supporta l'output JSON strutturato: chiedo il JSON nel testo della risposta.
    istruzioni = ("Rispondi SOLO con un oggetto JSON valido (niente testo prima o dopo, niente ```), "
                  "conforme a questo JSON Schema:\n" + json.dumps(schema.model_json_schema(), ensure_ascii=False))
    config = types.GenerateContentConfig(temperature=0.2)
    risposta = client.models.generate_content(model=MODELLO, contents=list(contenuti) + [istruzioni], config=config)
    return _json_dal_testo(risposta.text, schema)


PROMPT_SCONTRINO = """Analizza questa foto di uno scontrino di un supermercato italiano.
Elenca SOLO alimenti e bevande: escludi detersivi, igiene, sacchetti, sconti, totali, resto, punti fedeltà, IVA.
Per ogni articolo:
- testo_scontrino: il testo esattamente come stampato;
- nome: nome del prodotto per esteso e in italiano corretto (gli scontrini abbreviano, es. "MOZZ.FIORDIL.200G" -> "Mozzarella fior di latte 200 g"), con la marca se presente;
- quantita: numero di pezzi (righe ripetute o "x2" vanno sommate; prodotti a peso = 1);
- luogo: dove si conserva il prodotto appena acquistato e ancora chiuso;
- giorni_conservazione: stima realistica dei giorni di conservazione dal giorno di acquisto per un prodotto chiuso di quel tipo (latte fresco ~6, carne fresca ~3, pasta secca ~365, ...).
data_acquisto: la data stampata sullo scontrino in formato AAAA-MM-GG, null se non leggibile."""

PROMPT_PRODOTTO = """Identifica il prodotto alimentare nelle foto. Oggi è il {oggi}.
{contesto}
Regole:
- Se ci sono dati da Open Food Facts usali per nome, marca e categoria (sono affidabili).
- codice_a_barre: le cifre del codice se leggibili nella foto, altrimenti null.
- data_scadenza: SOLO se leggi chiaramente una data stampata sulla confezione ("da consumarsi entro", "preferibilmente entro", "scad.", "TMC", data vicino al lotto). Formato AAAA-MM-GG. Se ci sono solo mese e anno usa l'ultimo giorno del mese. Se non la leggi con certezza: null. Non inventare.
- giorni_conservazione: stima dei giorni di conservazione da oggi per il prodotto chiuso, conservato nel luogo indicato.
- luogo: dove va conservato il prodotto chiuso.
- alimento: false se nelle foto non c'è un alimento o una bevanda."""


def riga_bozza(nome, categoria, luogo, qta, scadenza, tipo, marca=None, codice=None) -> dict:
    return {"Salva": True, "Nome": nome, "Marca": marca or "", "Qtà": max(1, int(qta or 1)),
            "Categoria": normalizza_categoria(categoria), "Dove": luogo if luogo in LUOGHI else "dispensa",
            "Scadenza": scadenza, "Tipo": tipo, "Codice": codice or ""}


def analizza_scontrino(img: Image.Image) -> list[dict]:
    dati: Scontrino = chiedi_gemini([ridimensiona(img, 2000), PROMPT_SCONTRINO], Scontrino)
    acquisto = parse_data(dati.data_acquisto)
    if acquisto is None or acquisto > date.today() or (date.today() - acquisto).days > 60:
        acquisto = date.today()
    return [riga_bozza(a.nome, a.categoria.value, a.luogo.value, a.quantita,
                       acquisto + timedelta(days=max(0, a.giorni_conservazione)), "stimata")
            for a in dati.articoli]


def analizza_prodotto(img_codice: Image.Image, img_data: Optional[Image.Image]) -> tuple[dict, list[str]]:
    note: list[str] = []
    codici = leggi_codici(img_codice) + (leggi_codici(img_data) if img_data else [])
    ean, scad_gs1 = estrai_ean(codici)
    off = cerca_open_food_facts(ean) if ean else None

    if ean:
        note.append(f"Codice letto: **{ean}**")
        note.append("Trovato su Open Food Facts ✅" if off else "Non presente su Open Food Facts.")
    if scad_gs1:
        note.append(f"Scadenza contenuta nel codice GS1: **{scad_gs1:%d/%m/%Y}** ✅")

    if not chiave_utente():  # modalità senza AI: solo codice a barre + Open Food Facts
        if not ean:
            raise ValueError("codice a barre non letto. Inquadra solo il codice, da vicino, dritto e senza "
                             "riflessi, poi riprova. Con la chiave AI collegata posso anche riconoscere la confezione.")
        if off:
            nome, marca, categoria = dati_off(off)
        else:
            nome, marca, categoria = f"Prodotto {ean}", None, "Altro"
            note.append("Scrivi il nome del prodotto nella tabella qui sotto.")
        if scad_gs1:
            scadenza, tipo = scad_gs1, "reale"
        else:
            scadenza, tipo = date.today() + timedelta(days=CATEGORIE[categoria][2]), "stimata"
            note.append("Scadenza **stimata** per categoria: correggila nella tabella con la data sulla confezione.")
        return riga_bozza(nome, categoria, CATEGORIE[categoria][1], 1, scadenza, tipo, marca, ean), note

    if not ean:
        note.append("Codice a barre non decodificato: provo a riconoscere la confezione.")

    contesto = f"Codice a barre letto: {ean}." if ean else "Codice a barre non decodificato."
    if off:
        contesto += (f"\nDati Open Food Facts: nome={off.get('product_name_it') or off.get('product_name')!r}, "
                     f"marca={off.get('brands')!r}, categorie={off.get('categories')!r}, "
                     f"quantità={off.get('quantity')!r}.")
    contenuti: list = [PROMPT_PRODOTTO.format(oggi=date.today().isoformat(), contesto=contesto),
                       "FOTO 1 (codice a barre / confezione):", ridimensiona(img_codice)]
    if img_data:
        contenuti += ["FOTO 2 (data di scadenza):", ridimensiona(img_data)]
    p: ProdottoFoto = chiedi_gemini(contenuti, ProdottoFoto)
    if not p.alimento:
        raise ValueError("Nella foto non sembra esserci un alimento.")

    nome, marca = p.nome, p.marca
    codice_ai = re.sub(r"\D", "", p.codice_a_barre or "")
    if not ean and ean_valido(codice_ai):  # l'AI ha letto le cifre che il lettore locale non ha decodificato
        ean = codice_ai
        if off_ai := cerca_open_food_facts(ean):
            nome, marca_off, _ = dati_off(off_ai)
            marca = marca_off or marca
            note.append(f"Codice letto dall'AI: **{ean}**, trovato su Open Food Facts ✅")

    scad_ai = parse_data(p.data_scadenza)
    if scad_gs1:
        scadenza, tipo = scad_gs1, "reale"
    elif scad_ai:
        scadenza, tipo = scad_ai, "reale"
        note.append(f"Data letta sulla confezione: **{scad_ai:%d/%m/%Y}** — controlla che sia corretta.")
    else:
        scadenza, tipo = date.today() + timedelta(days=max(0, p.giorni_conservazione)), "stimata"
        note.append("Nessuna data leggibile: scadenza **stimata**. Fotografa la data per averla esatta.")
    riga = riga_bozza(nome, p.categoria.value, p.luogo.value, 1, scadenza, tipo, marca, ean or codice_ai)
    return riga, note


# =============================================================================
# INTERFACCIA
# =============================================================================
st.set_page_config(page_title="Frigo AI", page_icon="🥗", layout="centered")
st.markdown("""
<style>
.fa-header {text-align:center; padding:14px; margin-bottom:12px; border-radius:16px;
            background:linear-gradient(135deg,#43a047,#1b5e20); color:#fff;}
.fa-header h1 {color:#fff; margin:0; font-size:1.7rem;}
.fa-card {padding:10px 14px; border-radius:12px; margin:10px 0 6px; border-left:6px solid #2e7d32;
          background:rgba(128,128,128,.08);}
.fa-row {display:flex; justify-content:space-between; align-items:center; gap:10px;}
.fa-nome {font-weight:600; font-size:1.02rem;}
.fa-sub {font-size:.82rem; opacity:.75;}
.fa-badge {color:#fff; padding:4px 10px; border-radius:10px; font-weight:700; white-space:nowrap; font-size:.85rem;}
</style>
""", unsafe_allow_html=True)

applica_cookie()
sincronizza_archivio()
db = st.session_state.db
if avviso := st.session_state.pop("_avviso_archivio", None):
    st.warning(avviso)
st.session_state.setdefault("bozza", [])
st.session_state.setdefault("bozza_ver", 0)
st.session_state.setdefault("note", [])

st.markdown('<div class="fa-header"><h1>🥗 Frigo AI</h1></div>', unsafe_allow_html=True)

with st.sidebar:
    st.subheader("🔑 AI Gemini")
    if chiave_utente():
        st.success(f"Collegata con la tua chiave (…{chiave_utente()[-4:]})")
        if st.button("Scollega e cancella la chiave", width="stretch"):
            scollega_chiave()
            st.rerun()
    else:
        st.info("Non collegata. Puoi collegarla dalla scheda 📸 Aggiungi o 🍲 Ricette.")
    st.caption(f"Modello: {MODELLO}")

    st.divider()
    st.subheader("💾 I tuoi dati")
    st.caption("Frigo e lista spesa sono salvati **solo in questo browser**, non sul server. "
               "Scarica un backup per non perderli o per passare a un altro dispositivo.")
    st.download_button("⬇️ Scarica backup", json.dumps(db, ensure_ascii=False, indent=1),
                       file_name=f"frigo-ai-backup-{date.today():%Y-%m-%d}.json",
                       mime="application/json", width="stretch")
    with st.expander("⬆️ Ripristina backup"):
        file_backup = st.file_uploader("File di backup (.json)", type=["json"],
                                       key=f"up_backup_{st.session_state.get('_backup_ver', 0)}")
        if file_backup and st.button("Ripristina (sostituisce i dati attuali)", width="stretch"):
            try:
                ripristinato = leggi_backup(file_backup.getvalue().decode("utf-8"))
            except ValueError as e:
                st.error(f"File non valido: {e}")
            else:
                st.session_state._backup_ver = st.session_state.get("_backup_ver", 0) + 1
                salva_db(ripristinato)
                st.toast(f"Ripristinati {len(ripristinato['prodotti'])} prodotti ✅")
                st.rerun()
    with st.expander("🗑️ Cancella tutti i dati"):
        conferma = st.checkbox("Confermo: elimina frigo e lista spesa da questo browser")
        if st.button("Cancella tutto", disabled=not conferma, width="stretch"):
            salva_db(db_vuoto())
            st.rerun()
    with st.expander("🔒 Privacy"):
        st.markdown(
            "- L'app **non usa account**. Frigo e lista spesa restano nel tuo browser: il server li "
            "elabora solo mentre usi la pagina e non li conserva.\n"
            "- Le foto e le richieste AI vengono inviate a **Google Gemini** tramite la tua chiave personale.\n"
            "- I codici a barre vengono cercati su **Open Food Facts**, un database pubblico di prodotti.\n"
            "- Puoi scaricare o cancellare i tuoi dati in qualsiasi momento da questo menu.")

scaduti = [p for p in db["prodotti"] if (g := giorni_mancanti(p)) is not None and g < 0]
in_scadenza = [p for p in db["prodotti"] if (g := giorni_mancanti(p)) is not None and 0 <= g <= 2]
if scaduti:
    st.error(f"⚠️ {len(scaduti)} scaduti: " + ", ".join(p["nome"] for p in scaduti))
if in_scadenza:
    st.warning(f"⏰ In scadenza entro 2 giorni: " + ", ".join(p["nome"] for p in in_scadenza))

tab_frigo, tab_aggiungi, tab_spesa, tab_ricette = st.tabs(["🏠 Il mio frigo", "📸 Aggiungi", "🛒 Spesa", "🍲 Ricette"])


def esegui_e_ricarica(messaggio: Optional[str] = None) -> None:
    salva_db(db)
    if messaggio:
        st.toast(messaggio)
    st.rerun()


# ----------------------------------------------------------------------------- INVENTARIO
with tab_frigo:
    filtro = st.radio("Mostra", ["Tutti", "Frigo", "Freezer", "Dispensa"], horizontal=True,
                      label_visibility="collapsed")
    elenco = [p for p in db["prodotti"] if filtro == "Tutti" or p["luogo"] == filtro.lower()]
    elenco.sort(key=lambda p: (giorni_mancanti(p) is None, giorni_mancanti(p) or 0, p["nome"].lower()))

    if not elenco:
        st.info("Nessun prodotto qui. Vai su **📸 Aggiungi** per inserirne.")

    for p in elenco:
        pid = p["id"]
        giorni = giorni_mancanti(p)
        testo, colore = badge(giorni, p["tipo_scadenza"])
        icona = CATEGORIE.get(p["categoria"], CATEGORIE["Altro"])[0]
        scad = parse_data(p.get("scadenza"))
        dettagli = [NOMI_LUOGHI.get(p["luogo"], p["luogo"])]
        if p.get("marca"):
            dettagli.insert(0, p["marca"])
        dettagli.append(f"scad. {scad:%d/%m/%Y}" + (" (stimata)" if p["tipo_scadenza"] == "stimata" else "")
                        if scad else "scadenza sconosciuta")
        st.markdown(f"""
<div class="fa-card" style="border-left-color:{colore}">
  <div class="fa-row">
    <div><div class="fa-nome">{icona} {html.escape(p['nome'])} <span class="fa-sub">×{p['qta']}</span></div>
         <div class="fa-sub">{html.escape(' · '.join(dettagli))}</div></div>
    <div class="fa-badge" style="background:{colore}">{testo}</div>
  </div>
</div>""", unsafe_allow_html=True)

        c1, c2, c3 = st.columns(3)
        if c1.button("➖ Usato 1", key=f"usa_{pid}", width="stretch"):
            p["qta"] -= 1
            if p["qta"] <= 0:
                db["prodotti"].remove(p)
                aggiunto = aggiungi_a_lista(db, p["nome"])
                esegui_e_ricarica(f"{p['nome']} finito" + (" — aggiunto alla lista spesa 🛒" if aggiunto else ""))
            esegui_e_ricarica()
        if p["luogo"] != "freezer":
            if c2.button("🧊 Congela", key=f"cong_{pid}", width="stretch"):
                p["luogo"] = "freezer"
                if p["categoria"] != "Surgelati":
                    p["scadenza"] = (date.today() + timedelta(days=GIORNI_FREEZER)).isoformat()
                    p["tipo_scadenza"] = "stimata"
                esegui_e_ricarica(f"{p['nome']} spostato nel freezer")
        elif c2.button("♨️ Scongela", key=f"scong_{pid}", width="stretch"):
            p["luogo"] = "frigo"
            p["scadenza"] = (date.today() + timedelta(days=1)).isoformat()
            p["tipo_scadenza"] = "stimata"
            esegui_e_ricarica(f"{p['nome']} in frigo: consumalo entro domani")
        with c3.popover("✏️ Modifica", width="stretch"):
            with st.form(f"form_{pid}"):
                nome = st.text_input("Nome", p["nome"])
                marca = st.text_input("Marca", p.get("marca") or "")
                qta = st.number_input("Quantità", 1, 999, int(p["qta"]))
                categoria = st.selectbox("Categoria", list(CATEGORIE), list(CATEGORIE).index(p["categoria"])
                                         if p["categoria"] in CATEGORIE else len(CATEGORIE) - 1)
                luogo = st.selectbox("Dove", LUOGHI, LUOGHI.index(p["luogo"]), format_func=NOMI_LUOGHI.get)
                nuova_scad = st.date_input("Scadenza", scad, format="DD/MM/YYYY")
                reale = st.checkbox("Data letta sulla confezione", p["tipo_scadenza"] == "reale")
                salva_btn, elimina_btn = st.columns(2)
                if salva_btn.form_submit_button("💾 Salva"):
                    p.update(nome=nome.strip() or p["nome"], marca=marca.strip() or None, qta=int(qta),
                             categoria=categoria, luogo=luogo,
                             scadenza=nuova_scad.isoformat() if nuova_scad else None,
                             tipo_scadenza="reale" if reale else "stimata")
                    esegui_e_ricarica("Modifiche salvate")
                if elimina_btn.form_submit_button("🗑️ Elimina"):
                    db["prodotti"].remove(p)
                    esegui_e_ricarica(f"{p['nome']} eliminato")

# ----------------------------------------------------------------------------- AGGIUNTA
with tab_aggiungi:
    area_scansione = st.container()
    area_bozza = st.container()

    # La tabella di revisione viene costruita per prima (ma mostrata sotto) così le modifiche
    # dell'utente non si perdono quando una nuova scansione aggiunge righe.
    with area_bozza:
        bozza_modificata = None
        if st.session_state.bozza:
            st.divider()
            st.subheader("✅ Controlla e salva")
            for nota in st.session_state.note:
                st.caption(nota)
            bozza_modificata = st.data_editor(
                pd.DataFrame(st.session_state.bozza),
                key=f"editor_{st.session_state.bozza_ver}",
                num_rows="dynamic", hide_index=True, width="stretch",
                column_config={
                    "Salva": st.column_config.CheckboxColumn(width="small"),
                    "Nome": st.column_config.TextColumn(required=True),
                    "Qtà": st.column_config.NumberColumn(min_value=1, step=1, width="small"),
                    "Categoria": st.column_config.SelectboxColumn(options=list(CATEGORIE), required=True),
                    "Dove": st.column_config.SelectboxColumn(options=LUOGHI, required=True),
                    "Scadenza": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "Tipo": st.column_config.SelectboxColumn(options=["stimata", "reale"],
                                                             help="reale = letta sulla confezione"),
                    "Codice": st.column_config.TextColumn(disabled=True),
                },
            )
            da_salvare = bozza_modificata[bozza_modificata["Salva"].fillna(False).astype(bool)]
            col_a, col_b = st.columns(2)
            if col_a.button(f"💾 Salva {len(da_salvare)} prodotti", type="primary", width="stretch",
                            disabled=da_salvare.empty):
                for _, r in da_salvare.iterrows():
                    if str(r["Nome"] or "").strip():
                        qta = 1 if pd.isna(r["Qtà"]) else r["Qtà"]
                        db["prodotti"].append(nuovo_prodotto(
                            r["Nome"], r["Categoria"] or "Altro", r["Dove"], qta, parse_data(r["Scadenza"]),
                            r["Tipo"] or "stimata", str(r["Marca"] or "").strip() or None,
                            str(r["Codice"] or "").strip() or None))
                st.session_state.bozza, st.session_state.note = [], []
                st.session_state.bozza_ver += 1
                esegui_e_ricarica(f"{len(da_salvare)} prodotti salvati ✅")
            if col_b.button("✖️ Annulla", width="stretch"):
                st.session_state.bozza, st.session_state.note = [], []
                st.session_state.bozza_ver += 1
                st.rerun()

    def aggiungi_alla_bozza(righe: list[dict], note: list[str]) -> None:
        attuali = (bozza_modificata.to_dict("records") if bozza_modificata is not None
                   else st.session_state.bozza)
        st.session_state.bozza = attuali + righe
        st.session_state.note = note
        st.session_state.bozza_ver += 1
        st.rerun()

    with area_scansione:
        modo = st.radio("Cosa vuoi fotografare?", ["🧾 Scontrino", "🔍 Prodotto (codice a barre)", "✍️ Manuale"],
                        horizontal=True)
        ai_pronta = bool(chiave_utente())
        if not ai_pronta and modo == "🧾 Scontrino":
            pannello_chiave("aggiungi")

        if modo == "🧾 Scontrino":
            st.caption("Scontrino disteso, ben illuminato e tutto nell'inquadratura. "
                       "Le scadenze saranno **stimate** in base al tipo di prodotto.")
            foto = st.file_uploader("Foto dello scontrino", type=["jpg", "jpeg", "png", "webp"], key="up_scontrino")
            if foto and st.button("🚀 Analizza scontrino", disabled=not ai_pronta, type="primary"):
                with st.spinner("Lettura dello scontrino..."):
                    try:
                        righe = analizza_scontrino(apri_immagine(foto))
                    except Exception as e:
                        st.error(f"Analisi non riuscita: {e}")
                    else:
                        if righe:
                            aggiungi_alla_bozza(righe, [f"{len(righe)} alimenti trovati sullo scontrino. "
                                                        "Correggi nomi e date se serve."])
                        st.warning("Nessun alimento trovato sullo scontrino.")

        elif modo == "🔍 Prodotto (codice a barre)":
            if ai_pronta:
                st.caption("1️⃣ Fotografa il **codice a barre**. 2️⃣ (consigliato) Fotografa la **data di scadenza** "
                           "stampata: senza, la scadenza viene solo stimata.")
            else:
                st.caption("Fotografa il **codice a barre** da vicino: il prodotto viene cercato nel database "
                           "Open Food Facts e la scadenza è stimata (puoi correggerla).")
                with st.expander("✨ Vuoi che legga anche la data sulla confezione? Collega l'AI (facoltativo)"):
                    pannello_chiave("codice")
            foto_codice = st.file_uploader("Foto del codice a barre", type=["jpg", "jpeg", "png", "webp"],
                                           key="up_codice")
            foto_data = (st.file_uploader("Foto della data di scadenza (facoltativa)",
                                          type=["jpg", "jpeg", "png", "webp"], key="up_data")
                         if ai_pronta else None)
            if foto_codice and st.button("🚀 Riconosci prodotto", type="primary"):
                with st.spinner("Riconoscimento in corso..."):
                    try:
                        riga, note = analizza_prodotto(apri_immagine(foto_codice),
                                                       apri_immagine(foto_data) if foto_data else None)
                    except Exception as e:
                        st.error(f"Riconoscimento non riuscito: {e}")
                    else:
                        aggiungi_alla_bozza([riga], note)

        else:
            with st.form("manuale", clear_on_submit=True):
                nome = st.text_input("Nome *")
                c1, c2 = st.columns(2)
                categoria = c1.selectbox("Categoria", list(CATEGORIE))
                qta = c2.number_input("Quantità", 1, 999, 1)
                luogo = c1.selectbox("Dove", ["(automatico)"] + LUOGHI)
                scadenza = c2.date_input("Scadenza", None, format="DD/MM/YYYY",
                                         help="Vuota = stima in base alla categoria")
                if st.form_submit_button("➕ Aggiungi", type="primary"):
                    if not nome.strip():
                        st.error("Inserisci il nome.")
                    else:
                        tipo = "reale" if scadenza else "stimata"
                        scadenza = scadenza or date.today() + timedelta(days=CATEGORIE[categoria][2])
                        db["prodotti"].append(nuovo_prodotto(nome, categoria,
                                                             None if luogo == "(automatico)" else luogo,
                                                             qta, scadenza, tipo))
                        esegui_e_ricarica(f"{nome} aggiunto ✅")

# ----------------------------------------------------------------------------- LISTA SPESA
with tab_spesa:
    with st.form("spesa", clear_on_submit=True):
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        voce = c1.text_input("Aggiungi alla lista")
        if c2.form_submit_button("➕", width="stretch") and voce.strip():
            if aggiungi_a_lista(db, voce):
                esegui_e_ricarica()
            st.info("È già in lista.")

    if not db["lista_spesa"]:
        st.caption("Lista vuota. I prodotti finiti vengono aggiunti qui in automatico.")
    for voce in db["lista_spesa"]:
        fatto = st.checkbox(voce["testo"], voce["fatto"], key=f"sp_{voce['id']}")
        if fatto != voce["fatto"]:
            voce["fatto"] = fatto
            esegui_e_ricarica()
    if any(v["fatto"] for v in db["lista_spesa"]) and st.button("🧹 Togli gli spuntati"):
        db["lista_spesa"] = [v for v in db["lista_spesa"] if not v["fatto"]]
        esegui_e_ricarica()

# ----------------------------------------------------------------------------- RICETTE
with tab_ricette:
    disponibili = [p for p in db["prodotti"] if (giorni_mancanti(p) is None or giorni_mancanti(p) >= 0)]
    if not chiave_utente():
        pannello_chiave("ricette")
    elif not disponibili:
        st.info("Aggiungi qualche prodotto per ricevere ricette.")
    else:
        preferenze = st.text_input("Preferenze (facoltative)", placeholder="es. vegetariano, pronto in 20 minuti")
        if st.button("🤖 Cosa cucino?", type="primary"):
            disponibili.sort(key=lambda p: (giorni_mancanti(p) is None, giorni_mancanti(p) or 0))
            ingredienti = "\n".join(
                f"- {p['nome']} (x{p['qta']}, {NOMI_LUOGHI[p['luogo']]}"
                + (f", scade tra {giorni_mancanti(p)} giorni)" if giorni_mancanti(p) is not None else ")")
                for p in disponibili)
            prompt = ("Proponi 2 ricette casalinghe in italiano usando soprattutto questi ingredienti, "
                      "dando priorità a quelli che scadono prima. Puoi dare per scontati sale, olio, "
                      "pepe e acqua. Per ogni ricetta: titolo, tempo, ingredienti, passaggi brevi. "
                      f"Preferenze: {preferenze or 'nessuna'}.\n\nIngredienti:\n{ingredienti}")
            with st.spinner("Penso a qualcosa di buono..."):
                try:
                    st.session_state.ricetta = chiedi_gemini([prompt])
                except Exception as e:
                    st.error(f"Errore: {e}")
        if st.session_state.get("ricetta"):
            st.markdown(st.session_state.ricetta)
