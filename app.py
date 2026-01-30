import streamlit as st
import google.generativeai as genai
import PIL.Image
import json
import os
import streamlit.components.v1 as components

# --- 1. CONFIGURAZIONE CHIAVE SICURA (DA STREAMLIT SECRETS) ---
try:
    # Cerca la chiave salvata nella "cassaforte" di Streamlit Cloud
    MY_MASTER_KEY = st.secrets["GEMINI_KEY"]
except KeyError:
    # Se non la trova (test locale), usa una stringa vuota per non far crashare l'avvio
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
    
    .cookie-banner {
        background: #1a1a1a; color: white; padding: 15px;
        text-align: center; font-size: 0.85rem; border-radius: 12px;
        margin-bottom: 20px; border: 1px solid #4CAF50;
    }
    
    .ad-box {
        background: #ffffff; border: 1px dashed #4CAF50; border-radius: 15px;
        padding: 15px; text-align: center; margin: 15px 0; min-height: 100px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. FUNZIONI PUBBLICITÀ E CONSENSO ---
def display_ad(label):
    st.markdown(f"""
    <div class="ad-box">
        <small style="color:#aaa; text-transform:uppercase;">Annuncio Sponsorizzato - {label}</small>
        <div style="margin-top:10px; color:#555; font-weight:600;">
            🛒 Vuoi risparmiare sulla spesa? <br>
            <span style="color:#4CAF50; font-size:0.8rem;">Scopri le offerte dei nostri partner</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

# Gestione semplice del consenso (senza Iubenda a pagamento)
if 'privacy_accepted' not in st.session_state:
    st.session_state.privacy_accepted = False

# --- 4. GESTIONE DATABASE (PANTRIES PERMANENTI) ---
DATABASE_FILE = "dispensa_v3.json"

if "dispensa" not in st.session_state:
    # Inizializziamo le liste: Dispensa (Fresco) e Congelati (Surgelati)
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

# --- 5. INTERFACCIA PRINCIPALE ---
st.markdown('<div class="main-header"><h1>🥗 Frigo Pro AI</h1><p style="color:white !important;">Gestione Smart & Monetizzazione</p></div>', unsafe_allow_html=True)

# Banner Cookie manuale
if not st.session_state.privacy_accepted:
    st.markdown('<div class="cookie-banner">🍪 Utilizziamo cookie tecnici e pubblicitari per offrirti un servizio gratuito.</div>', unsafe_allow_html=True)
    if st.button("Accetto i termini e proseguo"):
        st.session_state.privacy_accepted = True
        st.rerun()

# Tabs
tab1, tab2, tab3, tab4 = st.tabs(["📸 Scanner", "🧊 Surgelati", "🍲 Ricette", "⚖️ Legale"])

with tab1:
    display_ad("Scanner Top")
    st.subheader("Aggiungi Prodotti Freschi")
    f_scontrino = st.file_uploader("Carica foto scontrino o prodotto", type=["jpg", "png", "jpeg"])
    
    if f_scontrino and st.button("Analizza con Gemini 2.5 Flash 🚀"):
        if not MY_MASTER_KEY:
            st.error("Configura la chiave GEMINI_KEY nei Secrets di Streamlit!")
        else:
            img = PIL.Image.open(f_scontrino)
            img.thumbnail((1024, 1024)) # Ottimizzazione per evitare timeout
            
            with st.spinner("L'IA sta elaborando i dati..."):
                try:
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    prompt = "Analizza l'immagine ed estrai una lista di prodotti alimentari. Per ogni prodotto scrivi una riga con questo formato esatto: Nome Prodotto | Categoria | ScadenzaGiorni (stima un numero)"
                    res = model.generate_content([prompt, img])
                    
                    for riga in res.text.strip().split('\n'):
                        if "|" in riga:
                            p = [x.strip() for x in riga.split("|")]
                            if len(p) >= 3:
                                st.session_state.dispensa.append({"nome": p[0], "cat": p[1], "scad": p[2]})
                    salva_dati()
                    st.success("Prodotti aggiunti con successo!")
                    st.rerun()
                except Exception as e:
