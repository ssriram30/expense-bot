import os
import re
import requests
from flask import Flask, request
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime

app = Flask(__name__)

TOKEN        = os.environ.get("8761935489:AAEr-AWRPipxFqG8KKkQJOj54PytuHh9-Q4")
SPREADSHEET  = os.environ.get("1J4EMfawS-1MLbTsKwKEDtZh02AxL24K2sVvaYnM_77g")

CATEGORIES = {
    "Food":          ["food","meal","eat","lunch","dinner","breakfast","restaurant","cafe","coffee","tea","drink","snack","burger","pizza","nasi","mee","roti","mamak","hawker","takeaway","delivery","mcd","kfc"],
    "Groceries":     ["grocery","groceries","supermarket","market","pasar","vegetable","fruit","meat","chicken","fish","egg","rice","tesco","aeon","giant","mydin","econsave","speedmart","lotus"],
    "Transport":     ["cab","taxi","grab","gojek","bus","train","lrt","mrt","ktm","toll","parking","petrol","fuel","flight","airasia","ferry","uber","commuter"],
    "Shopping":      ["shop","shopping","clothes","shoes","gadget","laptop","phone","lazada","shopee","amazon","mall","online"],
    "Bills":         ["bill","electricity","tnb","water","internet","wifi","unifi","maxis","celcom","digi","astro","insurance","netflix","spotify"],
    "Housing":       ["rent","condo","apartment","maintenance","repair","renovation","furniture","ikea","laundry"],
    "Health":        ["clinic","hospital","pharmacy","medicine","doctor","dentist","gym","supplement","guardian","watson"],
    "Entertainment": ["movie","cinema","tgv","gsc","gaming","concert","karaoke","bowling","genting"],
    "Travel":        ["hotel","resort","airbnb","holiday","vacation","trip","overseas","hostel"],
    "Education":     ["school","tuition","course","book","university","exam","udemy"]
}

def detect_category(text):
    t = text.lower()
    for cat, words in CATEGORIES.items():
        for w in words:
            if w in t:
                return cat
    return "General"

def parse_expense(text):
    nums   = re.findall(r'\d+(?:\.\d+)?', text)
    amount = float(nums[-1]) if nums else 0
    item   = re.sub(r'\d+(?:\.\d+)?', '', text).strip()
    item   = re.sub(r'\s+', ' ', item).strip() or text
    return item, amount, detect_category(text)

def get_sheet():
    import json
    creds_json = os.environ.get("GOOGLE_CREDS")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=["https://spreadsheets.google.com/feeds",
                "https://www.googleapis.com/auth/drive"]
    )
    gc    = gspread.authorize(creds)
    sh    = gc.open_by_key(SPREADSHEET)
    return sh.get_worksheet(0)

def send_message(chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text}
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    data    = request.json
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    text    = message.get("text", "").strip()

    if not chat_id or not text:
        return "ok", 200

    sheet = get_sheet()

    if text == "/list":
        rows = sheet.get_all_values()
        if len(rows) < 2:
            send_message(chat_id, "No expenses yet.")
            return "ok", 200
        msg   = "Last 10 Expenses:\n\n"
        start = max(1, len(rows) - 10)
        for row in rows[start:]:
            msg += f"• {row[1]} — RM{row[2]} ({row[3]})\n"
        send_message(chat_id, msg)
        return "ok", 200

    if text == "/day":
        send_range(chat_id, sheet, "day")
        return "ok", 200

    if text == "/month":
        send_range(chat_id, sheet, "month")
        return "ok", 200

    if text == "/year":
        send_range(chat_id, sheet, "year")
        return "ok", 200

    if text.startswith("/"):
        send_message(chat_id, "Type expense: cab 10, market 50")
        return "ok", 200

    item, amount, category = parse_expense(text)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sheet.append_row([now, item, amount, category])

    send_message(chat_id,
        f"✅ Saved!\n\n"
        f"📝 {item}\n"
        f"💰 RM{amount}\n"
        f"📂 {category}"
    )

    return "ok", 200

def send_range(chat_id, sheet, period):
    rows  = sheet.get_all_values()
    now   = datetime.now()
    msg   = f"{period.upper()} Expenses:\n\n"
    total = 0
    count = 0
    for row in rows[1:]:
        try:
            d = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        except:
            continue
        match = False
        if period == "day":   match = d.date() == now.date()
        if period == "month": match = d.year == now.year and d.month == now.month
        if period == "year":  match = d.year == now.year
        if match:
            count += 1
            total += float(row[2])
            msg   += f"• {row[1]} — RM{row[2]} ({row[3]})\n"
    if count == 0:
        msg = f"No expenses for {period}."
    else:
        msg += f"\nTotal: RM{total:.2f}"
    send_message(chat_id, msg)

@app.route("/")
def home():
    return "Bot running", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))