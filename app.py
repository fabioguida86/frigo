import streamlit as st
import google.generativeai as genai
import PIL.Image
import json
import os

# --- 1. CONFIGURAZIONE CHIAVE ---
try:
    MY_MASTER_KEY = st.secrets["GEMINI_KEY"]
except KeyError:
    MY_MASTER_KEY = ""

if MY_MASTER_KEY:
    genai.configure(api_key=MY_MASTER_KEY)

st.set_page_config(page_title="Frigo Pro AI", layout="centered", page_icon="🥗")

# --- 2. GESTIONE LINGUE (TRADUZIONI) ---
languages = {
    "Italiano": {
        "scan": "📸 Scanner", "freezer": "🧊 Freezer", "recipes": "🍲 Ricette", "legal": "⚖️ Legale",
        "mode": "Modalità:", "receipt": "Scontrino", "barcode": "Codice a Barre",
        "upload_text": "Scatta foto (Solo Alimenti)", "btn_scan": "Analizza Solo Alimenti 🚀",
        "pantry": "🍎 Dispensa", "manual_add": "Aggiunta Rapida Freezer", "btn_freeze": "Metti in Freezer",
        "chef": "🍲 Chef AI", "btn_recipe": "Genera Ricetta", "expiry": "Scadenza", "days": "gg",
        "frozen_label": "Surgelato", "ai_msg": "Filtrando gli alimenti...", "prompt_rules": "Estrai SOLO prodotti alimentari."
    },
    "English": {
        "scan": "📸 Scanner", "freezer": "🧊 Freezer", "recipes": "🍲 Recipes", "legal": "⚖️ Legal",
        "mode": "Mode:", "receipt": "Receipt", "barcode": "Barcode",
        "upload_text": "Take photo (Food Only)", "btn_scan": "Analyze Food Only 🚀",
        "pantry": "🍎 Pantry", "manual_add": "Quick Add Freezer", "btn_freeze": "Add to Freezer",
        "chef": "🍲 AI Chef", "btn_recipe": "Generate Recipe", "expiry": "Expiry", "days": "days",
        "frozen_label": "Frozen", "ai_msg": "Filtering food items...", "prompt_rules": "Extract ONLY food products."
    },
    "Español": {
        "scan": "📸 Scanner", "freezer": "🧊 Congelador", "recipes": "🍲 Recetas", "legal": "⚖️ Legal",
        "mode": "Modo:", "receipt": "Recibo", "barcode": "Código de Barras",
        "upload_text": "Tomar foto (Solo Alimento)", "btn_scan": "Analizar Alimento 🚀",
        "pantry": "🍎 Despensa", "manual_add": "Añadir al Congelador", "btn_freeze": "Congelar",
        "chef": "🍲 Chef AI", "btn_recipe": "Generar Receta", "expiry": "Caducidad", "days": "días",
        "frozen_label": "Congelado", "ai_msg": "Filtrando alimentos...", "prompt_rules": "Extraer SOLO productos alimenticios."
    }
}

# Selettore Lingua nella Sidebar (Barra laterale)
st.sidebar.title("Settings")
sel_lang = st.sidebar.selectbox("Language / Lingua", list(languages.keys()))
t = languages[sel_lang]

# --- 3. CSS CUSTOM ---
st.markdown(f"""
    <style>
    .main-header {{ text-align: center; padding: 15px; background: linear-gradient(135deg, #4CAF50, #2E7D32); color: white; border-radius: 0 0 20px 20px; margin-bottom: 15px; }}
    .card {{ background: white; padding: 12px; border-radius: 12px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 8px; border-left: 4px solid #4CAF50; }}
    .product-name {{ color: #1a1a1a !important; font-size: 1rem; font-weight: 600; }}
    .expiry-text {{ color: #555 !important; font-size: 0.85rem; }}
    .stButton>button {{ width: 100%; border-radius: 8px; height: 35px; }}
    </style>
    """, unsafe_allow_html=True)

# --- 4. DATABASE ---
DATABASE_FILE = "dispensa_v3.json"
if "dispensa" not in st.session_state:
    st.session_state.dispensa, st.session_state.congelati = [], []
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, "r") as f:
                data = json.load(f)
                st.session_state.dispensa = data.get("d", [])
                st.session_state.congelati = data.get("c", [])
        except: pass

def salva():
    with open(DATABASE_FILE, "w") as f:
        json.dump({"d": st.session_state.dispensa, "c": st.session_state.congelati}, f)

# --- 5. INTERFACCIA ---
st.markdown('<div class="main-header"><h1>🥗 Frigo Pro AI</h1></div>', unsafe_allow_html=True)

tabs = st.tabs([t["scan"], t["freezer"], t["recipes"], t["legal"]])

with tabs[0]:
    tipo_scan = st.radio(t["mode"], [t["receipt"], t["barcode"]], horizontal=True)
    f_img = st.file_uploader(t["upload_text"], type=["jpg", "png", "jpeg"])
    
    if f_img and st.button(t["btn_scan"]):
        img = PIL.Image.open(f_img)
        img.thumbnail((1024, 1024))
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = f"{t['prompt_rules']} Extract as: NAME | DAYS_TO_EXPIRY. Language: {sel_lang}."
        
        with st.spinner(t["ai_msg"]):
            res = model.generate_content([prompt, img])
            for riga in res.text.strip().split('\n'):
                if "|" in riga:
                    parti = riga.split("|")
                    nome = parti[0].strip()
                    scad = "".join(filter(str.isdigit, parti[1])) if len(parti)>1 else "7"
                    st.session_state.dispensa.append({"nome": nome, "scad": scad if scad else "7"})
            salva(); st.rerun()

with tabs[1]:
    st.subheader(f"❄️ {t['manual_add']}")
    nuovo = st.text_input(f"{t['pantry']} name:")
    if st.button(t["btn_freeze"]):
        if nuovo:
            st.session_state.congelati.append({"nome": nuovo, "scad": "❄️"})
            salva(); st.rerun()

with tabs[2]:
    st.subheader(t["chef"])
    if st.session_state.dispensa:
        prodotti = ", ".join([p['nome'] for p in st.session_state.dispensa])
        if st.button(t["btn_recipe"]):
            model = genai.GenerativeModel('gemini-2.5-flash')
            res = model.generate_content(f"Create a short recipe in {sel_lang} using: {prodotti}.")
            st.write(res.text)

# --- 6. VISUALIZZAZIONE ---
st.divider()
col1, col2 = st.columns(2)

with col1:
    st.markdown(f"### {t['pantry']}")
    for i, v in enumerate(list(st.session_state.dispensa)):
        st.markdown(f'<div class="card"><div class="product-name">{v["nome"]}</div><div class="expiry-text">{v["scad"]} {t["days"]}</div></div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🗑️", key=f"d_{i}"):
                st.session_state.dispensa.pop(i); salva(); st.rerun()
        with c2:
            if st.button("🧊", key=f"m_{i}"):
                item = st.session_state.dispensa.pop(i)
                st.session_state.congelati.append({"nome": item['nome'], "scad": "❄️"})
                salva(); st.rerun()

with col2:
    st.markdown(f"### {t['freezer']}")
    for i, v in enumerate(list(st.session_state.congelati)):
        st.markdown(f'<div class="card" style="border-left-color: #2196F3;"><div class="product-name">{v["nome"]}</div><div
