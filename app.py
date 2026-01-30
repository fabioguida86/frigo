import streamlit as st
import google.generativeai as genai
import PIL.Image
import json
import os

# --- 1. CONFIGURAZIONE CHIAVE E MODELLO ---
try:
    MY_MASTER_KEY = st.secrets["GEMINI_KEY"]
except KeyError:
    MY_MASTER_KEY = ""

if MY_MASTER_KEY:
    genai.configure(api_key=MY_MASTER_KEY)

st.set_page_config(page_title="Frigo Pro AI", layout="centered", page_icon="🥗")

# --- 2. GESTIONE LINGUE ---
languages = {
    "Italiano": {
        "scan": "📸 Scanner", "freezer": "🧊 Freezer", "recipes": "🍲 Ricette", "legal": "⚖️ Legale", "info": "📩 Info",
        "mode": "Modalità:", "receipt": "Scontrino", "barcode": "Codice a Barre",
        "upload_text": "Scatta foto (Solo Alimenti)", "btn_scan": "Analizza Solo Alimenti 🚀",
        "pantry": "🍎 Dispensa", "manual_add": "Aggiunta Rapida Freezer", "btn_freeze": "Metti in Freezer",
        "chef": "🍲 Chef AI", "btn_recipe": "Genera Ricetta con Alimenti", "expiry": "Scadenza", "days": "gg",
        "frozen_label": "Surgelato", "ai_msg": "Filtrando gli alimenti...", 
        "prompt_rules": "Estrai SOLO prodotti alimentari. Ignora detersivi o sacchetti. Formato: NOME | GIORNI_SCADENZA.",
        "clear_pantry": "🗑️ Svuota Tutto"
    },
    "English": {
        "scan": "📸 Scanner", "freezer": "🧊 Freezer", "recipes": "🍲 Recipes", "legal": "⚖️ Legal", "info": "📩 Info",
        "mode": "Mode:", "receipt": "Receipt", "barcode": "Barcode",
        "upload_text": "Take photo (Food Only)", "btn_scan": "Analyze Food Only 🚀",
        "pantry": "🍎 Pantry", "manual_add": "Quick Add Freezer", "btn_freeze": "Add to Freezer",
        "chef": "🍲 AI Chef", "btn_recipe": "Generate Recipe with Pantry", "expiry": "Expiry", "days": "days",
        "frozen_label": "Frozen", "ai_msg": "Filtering food items...", 
        "prompt_rules": "Extract ONLY food products. Ignore detergents or bags. Format: NAME | DAYS_TO_EXPIRY.",
        "clear_pantry": "🗑️ Clear All"
    },
    "Español": {
        "scan": "📸 Scanner", "freezer": "🧊 Congelador", "recipes": "🍲 Recetas", "legal": "⚖️ Legal", "info": "📩 Info",
        "mode": "Modo:", "receipt": "Recibo", "barcode": "Código de Barras",
        "upload_text": "Tomar foto (Solo Alimento)", "btn_scan": "Analizar Alimento 🚀",
        "pantry": "🍎 Despensa", "manual_add": "Añadir al Congelador", "btn_freeze": "Congelar",
        "chef": "🍲 Chef AI", "btn_recipe": "Generar Receta con Despensa", "expiry": "Caducidad", "days": "días",
        "frozen_label": "Congelado", "ai_msg": "Filtrando alimentos...", 
        "prompt_rules": "Extraer SOLO productos alimenticios. Ignorar detergentes o bolsas. Formato: NOMBRE | DIAS_CADUCIDAD.",
        "clear_pantry": "🗑️ Vaciar Todo"
    }
}

st.sidebar.title("Settings")
sel_lang = st.sidebar.selectbox("Language / Lingua", list(languages.keys()))
t = languages[sel_lang]

# --- 3. CSS E FUNZIONE PUBBLICITÀ ---
st.markdown(f"""
    <style>
    .main-header {{ text-align: center; padding: 15px; background: linear-gradient(135deg, #4CAF50, #2E7D32); color: white; border-radius: 0 0 20px 20px; margin-bottom: 15px; }}
    .card {{ background: white; padding: 12px; border-radius: 12px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 8px; border-left: 4px solid #4CAF50; }}
    .product-name {{ color: #1a1a1a !important; font-size: 1rem; font-weight: 600; }}
    .expiry-text {{ color: #555 !important; font-size: 0.85rem; }}
    .stButton>button {{ width: 100%; border-radius: 8px; height: 35px; }}
    /* Stile per il tasto svuota (Rosso) */
    div.stButton > button:first-child:active {{ background-color: #ff4b4b; color: white; }}
    .ad-box {{ text-align:center; margin: 10px 0; padding: 10px; background:#f0f0f0; border:1px dashed #bbb; border-radius:10px; font-size:0.65rem; color:#666; font-family:sans-serif; }}
    </style>
    """, unsafe_allow_html=True)

def render_ad(label):
    st.markdown(f'<div class="ad-box">ADVERTISEMENT - Media.net Slot<br><b>{label}</b></div>', unsafe_allow_html=True)

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

# --- 5. INTERFACCIA A 5 TAB ---
st.markdown('<div class="main-header"><h1>🥗 Frigo Pro AI</h1></div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs([t["scan"], t["freezer"], t["recipes"], t["legal"], t["info"]])

with tab1:
    render_ad("BANNER_TOP_SCANNER")
    tipo_scan = st.radio(t["mode"], [t["receipt"], t["barcode"]], horizontal=True)
    f_img = st.file_uploader(t["upload_text"], type=["jpg", "png", "jpeg"])
    
    if f_img and st.button(t["btn_scan"]):
        img = PIL.Image.open(f_img)
        img.thumbnail((1024, 1024))
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"{t['prompt_rules']} Language: {sel_lang}."
        
        with st.spinner(t["ai_msg"]):
            res = model.generate_content([prompt, img])
            for riga in res.text.strip().split('\n'):
                if "|" in riga:
                    parti = riga.split("|")
                    nome = parti[0].strip().replace("-", "").replace(":", "")
                    scad = "".join(filter(str.isdigit, parti[1])) if len(parti)>1 else "7"
                    st.session_state.dispensa.append({"nome": nome, "scad": scad if scad else "7"})
            salva(); st.rerun()

with tab2:
    st.subheader(f"❄️ {t['manual_add']}")
    nuovo = st.text_input(f"{t['pantry']} name:", key="manual_f")
    if st.button(t["btn_freeze"]):
        if nuovo:
            st.session_state.congelati.append({"nome": nuovo, "scad": "❄️"})
            salva(); st.rerun()
    render_ad("BANNER_MID_FREEZER")

with tab3:
    st.subheader(t["chef"])
    render_ad("RECIPE_TOP_AD")
    if st.session_state.dispensa:
        prodotti = ", ".join([p['nome'] for p in st.session_state.dispensa])
        if st.button(t["btn_recipe"]):
            model = genai.GenerativeModel('gemini-2.5-flash')
            res = model.generate_content(f"Crea una ricetta brevissima in {sel_lang} usando: {prodotti}.")
            st.write(res.text)
    else:
        st.write("Dispensa vuota / Pantry empty.")

with tab4:
    st.markdown("### Privacy & Cookies")
    st.write(f"Dati elaborati da Google Gemini. App gratuita sostenuta da Media.net. Lingua: {sel_lang}")
    render_ad("LEGAL_FOOTER_AD")

with tab5:
    st.subheader("📩 Chi Siamo & Contatti")
    st.markdown("**Frigo Pro AI** - Technology for zero food waste.\nEmail: support@frigopro.ai")
    with st.form("contact"):
        n = st.text_input("Name")
        m = st.text_area("Message")
        if st.form_submit_button("Send"):
            st.success("Sent!")
    render_ad("INFO_PAGE_AD")

# --- 6. VISUALIZZAZIONE DISPENSE ---
st.divider()
col1, col2 = st.columns(2)

with col1:
    st.markdown(f"### {t['pantry']}")
    
    # PULSANTE SVUOTA TUTTO (Dispensa)
    if st.session_state.dispensa:
        if st.button(t["clear_pantry"], key="clear_d"):
            st.session_state.dispensa = []
            salva()
            st.rerun()

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
    
    # PULSANTE SVUOTA TUTTO (Freezer)
    if st.session_state.congelati:
        if st.button(t["clear_pantry"], key="clear_c"):
            st.session_state.congelati = []
            salva()
            st.rerun()

    for i, v in enumerate(list(st.session_state.congelati)):
        st.markdown(f'<div class="card" style="border-left-color: #2196F3;"><div class="product-name">{v["nome"]}</div><div class="expiry-text">{v["scad"]} ({t["frozen_label"]})</div></div>', unsafe_allow_html=True)
        if st.button("🗑️", key=f"s_{i}"):
            st.session_state.congelati.pop(i); salva(); st.rerun()

render_ad("STICKY_FOOTER_AD")
