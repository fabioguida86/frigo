import streamlit as st
import google.generativeai as genai
import PIL.Image
import json
import os

# --- 1. CONFIGURAZIONE CHIAVE E PAGINA ---
try:
    MY_MASTER_KEY = st.secrets["GEMINI_KEY"]
except KeyError:
    MY_MASTER_KEY = ""

if MY_MASTER_KEY:
    genai.configure(api_key=MY_MASTER_KEY)

st.set_page_config(page_title="Frigo Pro AI", layout="centered", page_icon="🥗")

# --- 2. CSS CUSTOM (Nomi Neri e Card Pulite) ---
st.markdown("""
    <style>
    .main-header {
        text-align: center; padding: 20px;
        background: linear-gradient(135deg, #4CAF50, #2E7D32);
        color: white; border-radius: 0 0 25px 25px; margin-bottom: 20px;
    }
    .card {
        background: white; padding: 15px; border-radius: 15px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 10px;
        border-left: 5px solid #4CAF50;
    }
    .product-name { color: #1a1a1a; font-size: 1.1rem; font-weight: 600; margin-bottom: 5px; }
    .expiry-text { color: #555; font-size: 0.9rem; }
    .stButton>button { width: 100%; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. DATABASE ---
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

# --- 4. INTERFACCIA ---
st.markdown('<div class="main-header"><h1>🥗 Frigo Pro AI</h1></div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["📸 Scanner", "🧊 Freezer", "🍲 Ricette", "⚖️ Legale"])

with tab1:
    f_scontrino = st.file_uploader("Carica foto spesa", type=["jpg", "png", "jpeg"])
    if f_scontrino and st.button("Analizza Spesa 🚀"):
        img = PIL.Image.open(f_scontrino)
        img.thumbnail((1024, 1024))
        model = genai.GenerativeModel('gemini-2.5-flash')
        # Prompt ultra-preciso per evitare inversioni
        prompt = "Analizza lo scontrino. Scrivi ogni prodotto su una riga così: NOME | GIORNI_SCADENZA. Non scrivere altro."
        
        with st.spinner("Analisi in corso..."):
            res = model.generate_content([prompt, img])
            for riga in res.text.strip().split('\n'):
                if "|" in riga:
                    parti = riga.split("|")
                    nome = parti[0].strip().replace("-", "").replace(":", "")
                    scad = "".join(filter(str.isdigit, parti[1])) if len(parti)>1 else "7"
                    if not scad: scad = "7"
                    st.session_state.dispensa.append({"nome": nome, "scad": scad})
            salva()
            st.rerun()

with tab2:
    st.subheader("❄️ Archivio Freezer")
    nuovo = st.text_input("Aggiungi a mano nel freezer:")
    if st.button("Congela"):
        if nuovo:
            st.session_state.congelati.append({"nome": nuovo, "scad": "180"})
            salva(); st.rerun()

with tab4:
    st.markdown("### Privacy & Pubblicità\nApp gratuita con annunci. I dati sono elaborati da Google Gemini.")

# --- 5. VISUALIZZAZIONE CORRETTA (Sotto i Tab) ---
st.divider()
col1, col2 = st.columns(2)

with col1:
    st.subheader("🍎 Dispensa")
    for i, v in enumerate(list(st.session_state.dispensa)):
        st.markdown(f"""
            <div class="card">
                <div class="product-name">{v['nome']}</div>
                <div class="expiry-text">Scadenza stimata: <b>{v['scad']} gg</b></div>
            </div>
        """, unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🗑️", key=f"d_{i}"):
                st.session_state.dispensa.pop(i); salva(); st.rerun()
        with c2:
            if st.button("🧊", key=f"m_{i}"):
                item = st.session_state.dispensa.pop(i)
                st.session_state.congelati.append(item); salva(); st.rerun()

with col2:
    st.subheader("🧊 Freezer")
    for i, v in enumerate(list(st.session_state.congelati)):
        st.markdown(f"""
            <div class="card" style="border-left-color: #2196F3;">
                <div class="product-name">{v['nome']}</div>
                <div class="expiry-text">Lunga conservazione</div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("🗑️", key=f"s_{i}"):
            st.session_state.congelati.pop(i); salva(); st.rerun()
