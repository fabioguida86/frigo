import streamlit as st
import google.generativeai as genai
import PIL.Image
import json
import os
import streamlit.components.v1 as components

# --- 1. CONFIGURAZIONE CHIAVE SICURA ---
try:
    MY_MASTER_KEY = st.secrets["GEMINI_KEY"]
except KeyError:
    MY_MASTER_KEY = ""

if MY_MASTER_KEY:
    genai.configure(api_key=MY_MASTER_KEY)

# --- 2. CONFIGURAZIONE PAGINA E STYLE ---
st.set_page_config(page_title="Frigo Pro AI 2.5", layout="centered", page_icon="🥗")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; background-color: #f8f9fa; }
    
    .main-header {
        text-align: center; padding: 25px;
        background: linear-gradient(135deg, #4CAF50, #2E7D32);
        color: white !important; border-radius: 0 0 30px 30px;
        margin-bottom: 20px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    .card {
        background: white !important; padding: 18px; border-radius: 18px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05); margin-bottom: 12px;
        border-left: 6px solid #4CAF50; color: #1a1a1a !important;
    }
    
    .ad-box {
        background: #ffffff; border: 1px dashed #4CAF50; border-radius: 15px;
        padding: 15px; text-align: center; margin: 15px 0; min-height: 100px;
    }
    .stButton>button { width: 100%; border-radius: 10px; margin-top: 5px; }
    </style>
    """, unsafe_allow_html=True)

# --- 3. GESTIONE DATABASE ---
DATABASE_FILE = "dispensa_v3.json"

if "dispensa" not in st.session_state:
    st.session_state.dispensa = []
    st.session_state.congelati = []
    
    if os.path.exists(DATABASE_FILE):
        try:
            with open(DATABASE_FILE, "r") as f:
                data = json.load(f)
                st.session_state.dispensa = data.get("d", [])
                st.session_state.congelati = data.get("c", [])
        except:
            pass

def salva_dati():
    with open(DATABASE_FILE, "w") as f:
        json.dump({
            "d": st.session_state.dispensa, 
            "c": st.session_state.congelati
        }, f)

# --- 4. INTERFACCIA ---
st.markdown('<div class="main-header"><h1>🥗 Frigo Pro AI</h1></div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["📸 Scanner", "🧊 Freezer", "🍲 Ricette", "⚖️ Legale"])

with tab1:
    st.subheader("Aggiungi Prodotti Freschi")
    f_scontrino = st.file_uploader("Carica foto", type=["jpg", "png", "jpeg"])
    
    if f_scontrino and st.button("Analizza con Gemini 🚀"):
        img = PIL.Image.open(f_scontrino)
        img.thumbnail((1024, 1024))
        
        prompt = """
        Analizza lo scontrino. Scrivi una riga per ogni prodotto così:
        Nome | Categoria | GiorniScadenza (solo numero)
        
        Esempio:
        Pasta | Secco | 365
        Latte | Freschi | 5
        """
        
        with st.spinner("L'IA sta leggendo..."):
            try:
                model = genai.GenerativeModel('gemini-2.5-flash')
                res = model.generate_content([prompt, img])
                
                for riga in res.text.strip().split('\n'):
                    if "|" in riga:
                        p = [x.strip() for x in riga.split("|")]
                        if len(p) >= 3:
                            # Pulizia dati: rimuoviamo simboli e prendiamo solo numeri per la scadenza
                            nome_pulito = p[0].replace(":", "").replace("-", "").strip()
                            giorni = "".join(filter(str.isdigit, p[2]))
                            if not giorni: giorni = "7"
                            
                            st.session_state.dispensa.append({
                                "nome": nome_pulito, 
                                "cat": p[1], 
                                "scad": giorni
                            })
                salva_dati()
                st.rerun()
            except Exception as e:
                st.error(f"Errore: {e}")

with tab2:
    st.subheader("❄️ Archivio Surgelati")
    nuovo_surg = st.text_input("Aggiungi manualmente:")
    if st.button("Salva nel Freezer"):
        if nuovo_surg:
            st.session_state.congelati.append({"nome": nuovo_surg, "cat": "Surgelati", "scad": "180"})
            salva_dati(); st.rerun()

# --- 5. VISUALIZZAZIONE E SPOSTAMENTO ---
st.divider()
col_f, col_s = st.columns(2)

with col_f:
    st.markdown("### 🍎 Dispensa")
    for i, v in enumerate(list(st.session_state.dispensa)):
        with st.container():
            st.markdown(f'<div class="card"><b>{v["nome"]}</b><br><small>Scadenza: {v["scad"]} gg</small></div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🗑️", key=f"del_f_{i}"):
                    st.session_state.dispensa.pop(i)
                    salva_dati(); st.rerun()
            with c2:
                # PULSANTE PER SPOSTARE NEL FREEZER
                if st.button("🧊", key=f"move_s_{i}"):
                    prodotto = st.session_state.dispensa.pop(i)
                    st.session_state.congelati.append(prodotto)
                    salva_dati(); st.rerun()

with col_s:
    st.markdown("### 🧊 Freezer")
    for i, v in enumerate(list(st.session_state.congelati)):
        with st.container():
            st.markdown(f'<div class="card" style="border-left-color:#2196F3;"><b>{v["nome"]}</b></div>', unsafe_allow_html=True)
            if st.button("🗑️", key=f"del_s_{i}"):
                st.session_state.congelati.pop(i)
                salva_dati(); st.rerun()
