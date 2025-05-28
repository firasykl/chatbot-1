import streamlit as st
import pandas as pd
import pymysql
import requests
from fpdf import FPDF
import re
from langdetect import detect
import unicodedata

# --- Fonction IA avec langue auto ---
def detecter_langue(prompt):
    prompt = prompt.lower()
    mots_fr = ["bonjour", "prix", "vin", "bouteille", "merci", "rosé", "blanc", "rouge"]
    mots_en = ["hello", "price", "wine", "bottle", "thanks", "red", "white", "rose"]

    if len(prompt.strip()) < 5:
        return st.session_state.langue_client

    try:
        langue = detect(prompt)
    except:
        langue = st.session_state.langue_client

    if any(m in prompt for m in mots_en):
        return "en"
    if any(m in prompt for m in mots_fr):
        return "fr"

    return langue

def normalize(text):
    if not isinstance(text, str):
        return ""
    text = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode("utf-8")
    return re.sub(r"[^\w\s]", "", text.lower())

# --- Recherche ultra robuste sur Designation + Reference ---
def chercher_vins_dans_question(prompt, stock_df):
    prompt_clean = normalize(prompt)
    matches = []
    for _, row in stock_df.iterrows():
        designation_clean = normalize(str(row.get("Designation", "")))
        reference_clean = normalize(str(row.get("Reference", "")))
        if designation_clean in prompt_clean or reference_clean in prompt_clean:
            matches.append(row)
    return pd.DataFrame(matches)

def glm4_chat(prompt, extrait_stock=None):
    url = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": "f7d25ae6093e4e40805ba358c305b24e.D7LI3gn3m8UtedTQ"
    }

    detected_lang = detecter_langue(prompt)
    st.session_state.langue_client = detected_lang

    if detected_lang == "en":
        system_prompt = (
            "You are a virtual sommelier assistant who speaks perfect English.\n"
            "You help customers with information about wines: price (always with tax included), stock, characteristics, origin, and food pairings.\n"
            "Only use the provided wine list. Never invent other wines.\n"
            "Even if a wine is out of stock, you must still give its price if known.\n"
            "You can also answer questions about taste, grape varieties, or food pairings using general knowledge from the internet.\n"
            "Always answer clearly and naturally. Never talk about databases, wholesalers, or technical terms.\n"
            "If the user just says hi, reply politely without recommending a wine."
        )
    else:
        system_prompt = (
            "Tu es un assistant sommelier virtuel qui parle un français impeccable sans fautes d’orthographe.\n"
            "Tu réponds aux clients qui cherchent des informations sur des vins : prix (toujours TTC), stock, caractéristiques, région, accords mets/vins.\n"
            "Tu t'appuies uniquement sur la liste de vins fournie. Ne propose jamais de vin non listé.\n"
            "Même si un vin n'est plus en stock, donne quand même son prix TTC si tu le connais.\n"
            "Tu peux aussi répondre aux questions sur les caractéristiques d’un vin (goûts, cépages, accords...) en t’appuyant sur des informations générales disponibles sur internet.\n"
            "Tu dois rester simple, humain et direct. Ne parle jamais de base de données, de TVA, de grossiste ou de notions techniques.\n"
            "Si quelqu’un dit juste bonjour, réponds poliment sans recommander de vin."
        )

    messages = [{"role": "system", "content": system_prompt}]

    if extrait_stock:
        msg_content = (
            f"Voici une liste de vins disponibles ou connus :\n{extrait_stock}\n\nMerci de l'utiliser comme base pour toutes les recommandations suivantes."
            if detected_lang == "fr"
            else f"Here is a list of available or known wines:\n{extrait_stock}\n\nPlease use it as the base for all recommendations."
        )
        messages.append({"role": "user", "content": msg_content})

    for msg in st.session_state.messages:
        messages.append({"role": msg["role"], "content": msg["content"]})

    payload = {"model": "glm-4", "messages": messages}

    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        if "choices" in data:
            return data["choices"][0]["message"]["content"]
        return "❌ Réponse inattendue de l'IA."
    except Exception as e:
        return f"❌ Exception API GLM4 : {e}"

# --- Génération extrait complet ---
def generer_extrait_stock_filtre(df_filtre):
    if df_filtre.empty:
        return None
    df_filtre["Millesime"] = pd.to_numeric(df_filtre["Millesime"], errors='coerce')
    df_filtre["PrixVenteTTC"] = pd.to_numeric(df_filtre["PrixVenteTTC"], errors='coerce').fillna(0.0)

    if "Note" in df_filtre.columns:
        df_filtre["Note"] = pd.to_numeric(df_filtre["Note"], errors='coerce').fillna(3)
    else:
        df_filtre["Note"] = 3

    if "Quantite" in df_filtre.columns:
        df_filtre["Quantite"] = pd.to_numeric(df_filtre["Quantite"], errors='coerce').fillna(0)
    else:
        df_filtre["Quantite"] = 0

    df_filtre = df_filtre.dropna(subset=["PrixVenteTTC", "Millesime"])
    extrait = []
    for _, vin in df_filtre.iterrows():
        prix = round(float(vin['PrixVenteTTC']), 2)
        ligne = f"{vin['Designation']} - {prix}€ TTC ({vin['FamilleTag']}, {vin['Region']}, {int(vin['Millesime'])})"
        if vin.get("Note"):
            ligne += f", Note {vin['Note']}/5"
        if vin.get("Bio"):
            ligne += ", Bio"
        if pd.notna(vin.get("Medaille")):
            ligne += f", Médaille {vin['Medaille']}"
        ligne += f", Stock {int(vin['Quantite'])} bouteilles"
        extrait.append(ligne)
    return "\n".join(extrait)

# --- PDF ---
def save_pdf(text, filename="reponse.pdf"):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    for line in text.split("\n"):
        pdf.multi_cell(0, 10, line)
    pdf.output(filename)

# --- Connexion MySQL ---
try:
    conn = pymysql.connect(
        host='213.165.86.117',
        port=3306,
        user='oussama',
        password='Oussama210*',
        database='test_worldwine_dev',
        cursorclass=pymysql.cursors.DictCursor
    )
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM article;")
        rows = cursor.fetchall()
    stock_df = pd.DataFrame(rows)
except Exception as e:
    st.error(f"Erreur lors de la connexion à la base de données : {e}")
    st.stop()

# --- Interface Streamlit ---
st.title("🍷 WorldWineBot - Assistant Sommelier IA")

if "messages" not in st.session_state:
    st.session_state.messages = []
if "langue_client" not in st.session_state:
    st.session_state.langue_client = "fr"

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if prompt := st.chat_input("Pose ta question sur nos vins..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    vins_detectes = chercher_vins_dans_question(prompt, stock_df)
    if not vins_detectes.empty:
        extrait_stock = generer_extrait_stock_filtre(vins_detectes)
    else:
        extrait_stock = generer_extrait_stock_filtre(stock_df)

    with st.chat_message("assistant"):
        with st.spinner("WorldWineBot réfléchit..."):
            ia_response = glm4_chat(prompt, extrait_stock=extrait_stock)
            st.session_state.messages.append({"role": "assistant", "content": ia_response})
            st.markdown(f"**WorldWineBot :**\n{ia_response}")

if st.button("📄 Télécharger cette réponse en PDF"):
    if st.session_state.messages:
        last_msg = st.session_state.messages[-1]
        if last_msg["role"] == "assistant":
            save_pdf(last_msg["content"])
            st.success("✅ PDF réponse généré.")

if st.button("📜 Télécharger toute la conversation en PDF"):
    full_chat = ""
    for m in st.session_state.messages:
        role = "Client" if m["role"] == "user" else "WorldWineBot"
        full_chat += f"{role} : {m['content']}\n\n"
    save_pdf(full_chat, filename="conversation.pdf")
    st.success("✅ Conversation complète enregistrée en PDF.")
