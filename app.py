import streamlit as st
import google.generativeai as genai
import PIL.Image
import json
import os
import streamlit.components.v1 as components

# --- 1. CONFIGURAZIONE CHIAVE SICURA (DA STREAMLIT SECRETS) ---
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
    
    .cookie-banner {
        background: #1a1a1a; color: white; padding: 15px;
        text-align: center; font-size: 0.85rem; border-radius: 12px;
        margin-bottom: 20px; border: 1px solid #4CAF50;
    }
    
    .ad-box {
        background: #ffffff; border: 1px dashed #4CAF50; border-radius: 15px;
        padding: 15px; text-align: center; margin: 15px 0; min-height: 100px;
    }
    .stButton>button { width: 100%; border-radius: 10px; }
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

if 'privacy_accepted' not in st.session_state:
    st.session_state.privacy_accepted = False

# --- 4. GESTIONE DATABASE (PANTRIES PERMANENTI) ---
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

# --- 5. INTERFACCIA PRINCIPALE ---
st.markdown('<div class="main-header"><h1>🥗 Frigo Pro AI</h1><p style="color:white !important;">Gestione Smart & Monetizzazione</p></div>', unsafe_allow_html=True)

if not st.session_state.privacy_accepted:
    st.markdown('<div class="cookie-banner">🍪 Utilizziamo cookie tecnici e pubblicitari per offrirti un servizio gratuito.</div>', unsafe_allow_html=True)
    if st.button("Accetto i termini e proseguo"):
        st.session_state.privacy_accepted = True
        st.rerun()

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
            img.thumbnail((1024, 1024))
            
            with st.spinner("L'IA sta elaborando i dati..."):
                try:
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    prompt="""Analizza lo scontrino/foto. Scrivi una riga per ogni prodotto seguendo ESATTAMENTE questo schema:
                    Nome | Categoria | NumeroGiorni
                    Esempio:
                    Yogurt | Latticini | 10
                    Pollo | Carne | 3
                    NON scrivere nient'altro. Solo Nome | Categoria | Numero. 
                    Se non sai la scadenza, inventa un numero logico (es. 5 per carne, 30 per pasta)."""
                    res = model.generate_content([prompt, img])
                    
                    for riga in res.text.strip().split('\n'):
                        if "|" in riga:
                            p = [x.strip() for x in riga.split("|")]
                            if len(p) >= 3:
                                st.session_state.dispensa.append({"nome": p[0], "cat": p[1], "scad": p[2]})
                    salva_dati()
                    st.success("Prodotti aggiunti!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")

with tab2:
    st.subheader("❄️ Archivio Surgelati")
    display_ad("Freezer Mid")
    nuovo_surg = st.text_input("Nome prodotto surgelato:")
    if st.button("Salva nel Freezer"):
        if nuovo_surg:
            st.session_state.congelati.append({"nome": nuovo_surg, "cat": "Surgelati", "scad": "180"})
            salva_dati()
            st.rerun()

with tab3:
    st.subheader("🤖 Chef AI")
    display_ad("Recipe Ads")
    st.write("Le tue ricette personalizzate basate sulla dispensa appariranno qui.")
    if st.button("Genera Idea"):
        st.info("Funzione in arrivo nel prossimo aggiornamento!")

with tab4:
    st.subheader("Note Legali e Privacy")
    st.markdown("""
    **Privacy Policy**
    Questa app è gratuita grazie alla pubblicità. I tuoi dati (foto) vengono elaborati da Google Gemini per l'estrazione dei testi. 
    Nessuna foto viene memorizzata permanentemente sui nostri server. 
    I dati della dispensa risiedono sul tuo browser.
    
    **Contatti:** info@frigopro.ai (Esempio)
    """)

# --- 6. VISUALIZZAZIONE DISPENSE (FINALE COMPLETA) ---
st.divider()
col_f, col_s = st.columns(2)

with col_f:
    st.markdown("### 🍎 Dispensa")
    # Usiamo una copia della lista per evitare errori durante l'eliminazione
    for i, v in enumerate(list(st.session_state.dispensa)):
        st.markdown(f'<div class="card"><b>{v["nome"]}</b><br><small>{v["scad"]} gg</small></div>', unsafe_allow_html=True)
        if st.button(f"🗑️", key=f"del_f_{i}"):
            st.session_state.dispensa.pop(i)
            salva_dati()
            st.rerun()

with col_s:
    st.markdown("### 🧊 Freezer")
    for i, v in enumerate(list(st.session_state.congelati)):
        st.markdown(f'<div class="card" style="border-left-color:#2196F3;"><b>{v["nome"]}</b><br><small>Surgelato</small></div>', unsafe_allow_html=True)
        if st.button(f"🗑️", key=f"del_s_{i}"):
            st.session_state.congelati.pop(i)
            salva_dati()
            st.rerun()

# Spazio pubblicitario finale fisso
st.write("---")
display_ad("Bottom Sticky")


