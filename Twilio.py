from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os, base64, glob
import json
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
import gspread
from gspread.exceptions import WorksheetNotFound
from oauth2client.service_account import ServiceAccountCredentials

# Setup Google sheets auth
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
b64_creds = os.getenv("GOOGLE_CREDS_JSON")
decoded = base64.b64decode(b64_creds).decode("utf-8")
google_creds_dict = json.loads(decoded)
creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds_dict, scope)
client = gspread.authorize(creds)

# Open the sheet

spreadsheet = client.open("WhatsApp Logs")
try:
    sheet = spreadsheet.worksheet("Messages")
except WorksheetNotFound:
    sheet =spreadsheet.add_worksheet(title="Messages", rows="100", cols="10")
def log_message(name, phone, message):
    timezone = pytz.timezone("Europe/Rome")
    timestamp = datetime.now(timezone).strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([timestamp, name, phone, message])

load_dotenv()

app = Flask(__name__)

#In-memory store (for demo purposes only)
user_consents = {}


# Initialize OpenAI client with API key
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 💬 In-memorry Chat history (Can be improved with a database later)
history = {}

# Setup GPT-4 message context
SYSTEM_MESSAGE = {
    "role": "system",
    "content": (
        "You are the helpful assistant for Solar-Race Technical Team, a company that is located in Morbegno and installs solar panels in Lombardia. Answer questions clearly, provide solar-related and technical help and support on products such as solaredge, huawei, kostal, solis and other solar products including EV-chargers. if you can not resolve the issue or problem guide users to request a consultation with us on a specific date, and request for their details for ease of contact. Ensure the conversation is friendly and professional, and always communicate using the language of the user"
    )
}


@app.route("/")
def home():
    return "WhatsApp Bot is running! Send messages to the /whatsapp webhook."


@app.route("/whatsapp", methods=["POST"])
def whatsapp_bot():
    incoming_msg = request.form.get("Body", "").strip()
    sender_number = request.form.get("From", "").strip()
    print(f"Message from {sender_number}: {incoming_msg}")
    name = "User"

    # Handle consent revocation
    if incoming_msg == "stop":
        user_consents.pop(sender_number, None)
        reply_text = (
            "✅ Hai revocato il consenso. I tuoi dati sono stati eliminati. Se vuoi continuare la conversazione in futuro, dovrai dare nuovamente il consenso."
        )
        # Optionally log to Google Sheets
        timezone = pytz.timezone("Europe/Rome")
        sheet.append_row([datetime.now(timezone).strftime("%Y-%m-%d %H:%M:%S"), name, sender_number, "Consent Revoked"])
        twilio_response = MessagingResponse()
        twilio_response.message(reply_text)
        return str(twilio_response)

# Check for consent
    if sender_number not in user_consents:
        if incoming_msg in ["yes","Yes",  "I agree", "consent","ho d'acordo","si"]:
            user_consents[sender_number] = True
            reply_text = (
                "✅ Grazie per il consenso! Ora possiamo iniziare. Come posso aiutarti oggi?")
        else:
            reply_text = (
                "🔐 *Informativa Privacy (GDPR)*\n\n"
                "Solar-Race raccoglie e conserva temporaneamente:\n"
                "- Numero di telefono\n"
                "- Messaggi inviati\n"
                "- Data/Ora delle conversazioni\n\n"
                "Questi dati sono usati solo per fornire supporto e richieste di preventivo. "
                "Puoi revocare il consenso in qualsiasi momento inviando *STOP*.\n"
                "Puoi anche richiedere l'esportazione o la cancellazione dei tuoi dati.\n\n"
                "📄 Leggi la nostra informativa completa: https://www.solar-race.eu/privacy\n\n"
                "👉 Rispondi con *yes* per acconsentire."
                "------------------------------------------\n"
                "ENGLISH\n"
                "🔐 *Privacy Notice (GDPR)*\n\n"
                "Solar-Race temporarily collects and stores:\n"
                "- Phone number\n"
                "- Sent messages\n"
                "- Date/Time of conversations\n\n"
                "This data is used solely to provide support and respond to quote requests. "
                "You can revoke your consent at any time by sending *STOP*.\n"
                "You can also request to export or delete your data.\n\n"
                "📄 Read our full privacy policy: https://www.solar-race.eu/privacy\n\n"
                "👉 Reply with *yes* to give your consent."
            )
        twilio_response = MessagingResponse()
        twilio_response.message(reply_text)
        return str(twilio_response)

    # 🗃️ Export chat history on demand
    if incoming_msg == "esporta":
        timezone = pytz.timezone("Europe/Rome")
        history_file = f"chat_history_{datetime.now(timezone).date()}.json"
        if os.path.exists(history_file):
            with open(history_file, "r") as file:
                chat_log = json.load(file)
            user_log = [log for log in chat_log if log["sender"] == sender_number]
            export_text = json.dumps(user_log, indent=2) if user_log else "Nessun dato trovato."
        else:
            export_text = "Nessun dato disponibile."

        twilio_response = MessagingResponse()
        twilio_response.message(f"📄 Ecco i tuoi dati registrati:\n\n{export_text[:1500]}")  # Truncated to fit SMS
        return str(twilio_response)

    # 🧹 Delete all user data
    if incoming_msg == "cancella":
        history[sender_number] = []
        user_consents.pop(sender_number, None)
        reply_text = "🗑️ I tuoi dati sono stati cancellati. Se vuoi continuare, dovrai dare nuovamente il consenso."
        twilio_response = MessagingResponse()
        twilio_response.message(reply_text)
        return str(twilio_response)

    # 💬 This ensure chat_log is always assigned
    chat_history = history.setdefault(sender_number, [])
    chat_history.append({"role": "user", "content": incoming_msg})

    messages = [SYSTEM_MESSAGE] + chat_history

    log_message(name, sender_number,incoming_msg)

    try:
        chat_response = client.chat.completions.create(
            model="gpt-4",
            messages=messages,
            temperature=0.7,
            max_tokens=500
        )

        reply_text = chat_response.choices[0].message.content
        if reply_text is None:
            reply_text = ""
        reply_text = reply_text.strip()
        print (f" AI Response to {sender_number}: {reply_text}")

        # 💬 Add bot reply to chat history
        chat_history.append({"role": "assistant", "content": reply_text})

    except Exception as e:
        print("Error with GPT:", e)
        reply_text = "Mi dispiace, si è verificato un errore. Riprova più tardi."

    # 📝 Save to chat history (JSON file)
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "sender": sender_number,
        "user_message": incoming_msg,
        "bot_reply": reply_text
    }
    try:
        timezone = pytz.timezone("Europe/Rome")
        history_file = f"chat_history_{datetime.now(timezone).date()}.json"
        if os.path.exists(history_file):
            with open(history_file, "r") as file:
                chat_log = json.load(file)
        else:
            chat_log = []
        chat_log.append(log_entry)

        with open(history_file, "w") as file:
            json.dump(chat_log, file, indent=4)
    except Exception as e:
        print("⚠️ Error saving chat history:", e)

    # Respond via Twilio
    twilio_response = MessagingResponse()
    twilio_response.message(reply_text)
    return str(twilio_response)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

def cleanup_old_logs():
    timezone = pytz.timezone("Europe/Rome")
    cutoff = datetime.now(timezone) - timedelta(days=30)
    for file in glob.glob("chat_history_*.json"):
        file_date_str = file.replace("chat_history_", "").replace(".json", "")
        try:
            file_date = datetime.strptime(file_date_str, "%Y-%m-%d")
            if file_date < cutoff:
                os.remove(file)
                print(f"🗑️ Deleted old log: {file}")
        except ValueError:
            print(f"⚠️ Skipped invalid file name: {file}")
            continue