import streamlit as st
import google.generativeai as genai
import PIL.Image
import re
import json
import os

# --- CONFIGURAZIONE CHIAVE MASTER (FISSA) ---
MY_MASTER_KEY = "AIzaSyAdhh9EJ6uj0CCeefFpuq7rfsu7qHzuCyE"

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Frigo Pro AI 2.5", layout="centered", page_icon="🥗")

# --- STILE CSS AVANZATO (CONTRASTO MASSIMO PER MOBILE) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; background-color: #f0f2f6; }
    .main-header {
        text-align: center; padding: 20px;
        background: linear-gradient(135deg, #4CAF50, #2E7D32);
        color: white !important; border-radius: 0 0 30px 30px;
        margin-bottom: 25px; box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    .card {
        background: white !important; padding: 20px; border-radius: 20px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.1); margin-bottom: 10px;
        border-left: 6px solid #4CAF50; color: #1a1a1a !important;
    }
    .card b, .card span { color: #1a1a1a !important; }
    .stButton>button { 
        width: 100%; border-radius: 12px; height: 45px; font-weight: 600; 
        background-color: #ffffff; color: #1a1a1a; border: 1px solid #ddd;
    }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

st.markdown('<div class="main-header"><h1>🥗 Frigo AI 2.5</h1><p style="color:white !important;">Modello Gemini 2.5 Flash Attivo</p></div>', unsafe_allow_html=True)

# --- LOGICA DATI ---
DATABASE_FILE = "dispensa_v3.json"

def salva_carica_dati(mode="carica"):
    if mode == "salva":
        dati = {"d": st.session_state.dispensa, "c": st.session_state.congelati, "l": st.session_state.lista_spesa}
        with open(DATABASE_FILE, "w") as f: json.dump(dati, f)
    else:
        if os.path.exists(DATABASE_FILE):
            with open(DATABASE_FILE, "r") as f:
                d = json.load(f)
                st.session_state.dispensa = d.get("d", [])
                st.session_state.congelati = d.get("c", [])
                st.session_state.lista_spesa = d.get("l", [])

if "dispensa" not in st.session_state:
    st.session_state.dispensa, st.session_state.congelati, st.session_state.lista_spesa = [], [], []
    salva_carica_dati("carica")

genai.configure(api_key=MY_MASTER_KEY)

def get_icon(cat):
    cat = str(cat).lower()
    mapping = {"latticini": "🥛", "carne": "🥩", "pesce": "🐟", "verdura": "🥦", "frutta": "🍎", "bevande": "🥤", "dolci": "🍰", "uova": "🥚", "pane": "🥖"}
    for k, v in mapping.items():
        if k in cat: return v
    return "📦"

def pulisci_n(t):
    n = re.findall(r'\d+', str(t))
    valore = int(n[0]) if n else 7
    return valore if valore > 0 else 7

# --- TABS ---
tab1, tab2, tab3 = st.tabs(["📸 Scansione", "🍲 Cucina", "🛒 Spesa"])

with tab1:
    st.subheader("Inserimento Prodotti")
    
    # OPZIONE 1: SCONTRINO
    with st.expander("📄 Scansiona Scontrino"):
        f_scontrino = st.file_uploader("Carica foto scontrino", type=["jpg", "png", "jpeg"])
        if f_scontrino and st.button("Analizza Scontrino 🚀"):
            img = PIL.Image.open(f_scontrino)
            with st.spinner("Analisi in corso con Gemini 2.5..."):
                model = genai.GenerativeModel('gemini-2.5-flash')
                prompt = "Analizza lo scontrino. Estrai SOLO alimenti. FORMATO: Nome | Qtà | Categoria | GiorniScadenza"
                res = model.generate_content([prompt, img])
                for riga in res.text.strip().split('\n'):
                    if "|" in riga:
                        p = [x.strip().replace("*","") for x in riga.split("|")]
                        if len(p) >= 4:
                            st.session_state.dispensa.append({"nome":p[0], "qta":p[1], "cat":p[2], "scad":p[3]})
                salva_carica_dati("salva")
                st.rerun()

    # OPZIONE 2: BARCODE / PRODOTTO SINGOLO
    with st.expander("🔍 Scansiona Barcode o Prodotto", expanded=True):
        f_camera = st.camera_input("Inquadra il codice a barre o la confezione")
        if f_camera:
            img_cam = PIL.Image.open(f_camera)
            with st.spinner("Identificazione prodotto..."):
                try:
                    model = genai.GenerativeModel('gemini-2.5-flash')
                    # Istruiamo l'IA a leggere il barcode dall'immagine o a riconoscere l'oggetto
                    prompt_cam = "Identifica l'alimento in foto (leggi il barcode o riconosci la confezione). FORMATO: Nome | 1 | Categoria | GiorniScadenza. Se non è cibo rispondi: ERRORE"
                    res = model.generate_content([prompt_cam, img_cam])
                    
                    if "|" in res.text and "ERRORE" not in res.text:
                        parti = [x.strip().replace("*","") for x in res.text.split("|")]
                        if len(parti) >= 4:
                            st.success(f"Trovato: {parti[0]}")
                            if st.button(f"Aggiungi {parti[0]} alla dispensa"):
                                st.session_state.dispensa.append({"nome":parti[0], "qta":parti[1], "cat":parti[2], "scad":parti[3]})
                                salva_carica_dati("salva")
                                st.rerun()
                    else:
                        st.error("Prodotto non riconosciuto. Riprova inquadrando meglio.")
                except Exception as e:
                    st.error(f"Errore: {e}")

with tab2:
    if st.button("🤖 Ricetta con Gemini 2.5"):
        model = genai.GenerativeModel('gemini-2.5-flash')
        ing = ", ".join([p['nome'] for p in st.session_state.dispensa])
        if ing:
            res = model.generate_content(f"Crea una ricetta rapida con: {ing}.")
            st.info(res.text)
        else: st.warning("La dispensa è vuota!")

with tab3:
    nuovo = st.text_input("Aggiungi alla lista spesa:")
    if st.button("Inserisci in lista"):
        if nuovo:
            st.session_state.lista_spesa.append(nuovo); salva_carica_dati("salva"); st.rerun()
    for i, x in enumerate(st.session_state.lista_spesa):
        st.markdown(f"• {x}")

# --- VISUALIZZAZIONE DISPENSA ---
st.markdown("### 🍎 Dispensa Attiva")
if not st.session_state.dispensa:
    st.write("La tua dispensa è vuota. Scansiona qualcosa!")
    
for i, v in enumerate(st.session_state.dispensa):
    g = pulisci_n(v['scad'])
    icona = get_icon(v['cat'])
    
    st.markdown(f"""
    <div class="card">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <span style="font-size: 1.1rem; font-weight: 600;">{icona} {v['nome']}</span>
            <span style="background: {'#ffebee' if g < 3 else '#e8f5e9'}; color: #1a1a1a; padding: 5px 10px; border-radius: 10px; font-weight: bold; border: 1px solid #ccc;">
                {g} gg
            </span>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    c1, c2 = st.columns(2)
    if c1.button("❄️ Freezer", key=f"f_{i}"):
        p = st.session_state.dispensa.pop(i)
        p['scad'] = "30"
        st.session_state.congelati.append(p)
        salva_carica_dati("salva"); st.rerun()
    if c2.button("🗑️ Finito", key=f"d_{i}"):
        st.session_state.dispensa.pop(i); salva_carica_dati("salva"); st.rerun()
