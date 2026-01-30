import streamlit as st
import google.generativeai as genai
import PIL.Image
import json
import os

# --- 1. CONFIGURAZIONE ---
try:
    MY_MASTER_KEY = st.secrets["GEMINI_KEY"]
except KeyError:
    MY_MASTER_KEY = ""

if MY_MASTER_KEY:
    genai.configure(api_key=MY_MASTER_KEY)

st.set_page_config(page_title="Frigo Pro AI", layout="centered", page_icon="🥗")

# --- 2. CSS CUSTOM ---
st.markdown("""
    <style>
    .main-header {
        text-align: center; padding: 15px;
        background: linear-gradient(135deg, #4CAF50, #2E7D32);
        color: white; border-radius: 0 0 20px 20px; margin-bottom: 15px;
    }
    .card {
        background: white; padding: 12px; border-radius: 12px;
        box-shadow: 0 2px 5px rgba(0,0,0,0.1); margin-bottom: 8px;
        border-left: 4px solid #4CAF50;
    }
    .product-name { color: #1a1a1a !important; font-size: 1rem; font-weight: 600; }
    .expiry-text { color: #555 !important; font-size: 0.85rem; }
    .stButton>button { width: 100%; border-radius: 8px; height: 35px; }
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
    tipo_scan = st.radio("Cosa vuoi scansionare?", ["Scontrino", "Codice a Barre"], horizontal=True)
    # L'uploader su mobile attiva l'opzione Fotocamera
    f_img = st.file_uploader("Scatta una foto al prodotto o scontrino", type=["jpg", "png", "jpeg"])
    
    if f_img and st.button("Analizza Immagine 🚀"):
        img = PIL.Image.open(f_img)
        img.thumbnail((1024, 1024))
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        prompt = "Analizza l'immagine. Scrivi ogni prodotto su una riga separata così: NOME | GIORNI_SCADENZA_NUMERO"
        if tipo_scan == "Codice a Barre":
            prompt = "Identifica il prodotto da questo codice a barre o confezione. Rispondi solo: NOME | GIORNI_SCADENZA_NUMERO"
        
        with st.spinner("L'IA sta leggendo..."):
            res = model.generate_content([prompt, img])
            for riga in res.text.strip().split('\n'):
                if "|" in riga:
                    parti = riga.split("|")
                    nome = parti[0].strip()
                    scad = "".join(filter(str.isdigit, parti[1])) if len(parti)>1 else "7"
                    st.session_state.dispensa.append({"nome": nome, "scad": scad if scad else "7"})
            salva(); st.rerun()

with tab2:
    st.subheader("❄️ Aggiunta Rapida Freezer")
    nuovo = st.text_input("Inserisci nome:")
    if st.button("Metti in Freezer"):
        if nuovo:
            st.session_state.congelati.append({"nome": nuovo, "scad": "❄️"})
            salva(); st.rerun()

with tab3:
    st.subheader("🍲 Chef AI")
    if st.session_state.dispensa:
        prodotti = ", ".join([p['nome'] for p in st.session_state.dispensa])
        if st.button("Genera Ricetta con la mia Dispensa"):
            model = genai.GenerativeModel('gemini-2.5-flash')
            res = model.generate_content(f"Crea una ricetta veloce con alcuni di questi ingredienti: {prodotti}. Sii breve.")
            st.write(res.text)
    else:
        st.write("Scansiona prima qualcosa per avere ricette!")

# --- 5. VISUALIZZAZIONE ---
st.divider()
col1, col2 = st.columns(2)

with col1:
    st.markdown("### 🍎 Dispensa")
    for i, v in enumerate(list(st.session_state.dispensa)):
        st.markdown(f'<div class="card"><div class="product-name">{v["nome"]}</div><div class="expiry-text">{v["scad"]} gg</div></div>', unsafe_allow_html=True)
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
    st.markdown("### 🧊 Freezer")
    for i, v in enumerate(list(st.session_state.congelati)):
        st.markdown(f"""
            <div class="card" style="border-left-color: #2196F3;">
                <div class="product-name">{v['nome']}</div>
                <div class="expiry-text">{v['scad']} (Surgelato)</div>
            </div>
        """, unsafe_allow_html=True)
        if st.button("🗑️", key=f"s_{i}"):
            st.session_state.congelati.pop(i); salva(); st.rerun()
