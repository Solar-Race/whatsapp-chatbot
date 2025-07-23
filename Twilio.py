from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from openai import OpenAI
import os, base64
import json
from datetime import datetime
from dotenv import load_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Setup Google sheets auth
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
google_creds_dict = json.loads(os.getenv("GOOGLE_CREDS_JSON"))
creds = ServiceAccountCredentials.from_json_keyfile_dict(google_creds_dict, scope)
client = gspread.authorize(creds)

# Open the sheet
sheet = client.open("WhatsApp Logs").worksheet("Messages")

def log_message(name, phone, message):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([timestamp, name, phone, message])

load_dotenv()

app = Flask(__name__)

# Initialize OpenAI client with API key
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 💬 In-memorry Chat history (Can be improved with a database later)
history = {}

# Setup GPT-4 message context
SYSTEM_MESSAGE = {
    "role": "system",
    "content": (
        "You are the helpful AI assistant for Solar-Race S.r.l., a company that is located in Morbegno and installs solar panels in Lombardia. Answer questions clearly, provide solar-related help, guide users to request a quote or schedule a consultation with us on a specific date, and ensure the conversation is friendly and professional. Always communicate in the language of the user, if you don't know the language, ask the user to specify it. If the user asks for a quote, ask for the name, surname, email and phone number. if the user lives within the province of Sondrio, schedule a face to face consultation for the next day, otherwise schedule an online video meeting, phone call or email consultation. If the usuer enquires about our product, we work with solaredge, huawei, kostal, solis and many more products including EV-chargers. Here are the information of our company, website: https://wwww.solar-race.eu, email: info@solar-race.eu, telephone:+39 331 218 4036, and address: Via G. Garibaldi, 4, 23017. Always end the conversation with a friendly message/greetings."
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
        history_file = f"chat_history_{datetime.now().date()}.json"
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