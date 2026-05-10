import os
import re
import json
import requests
from flask import Flask, request
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime

app = Flask(__name__)

TOKEN       = os.environ.get("TOKEN")
SHEET_ID    = os.environ.get("SPREADSHEET_ID")
CREDS_JSON  = os.environ.get("GOOGLE_CREDS")

CATEGORIES = {
    "Food":          ["food","meal","eat","lunch","dinner","breakfast","restaurant","cafe","coffee","tea","drink","snack","burger","pizza","nasi","mee","roti","mamak","hawker","takeaway","delivery","mcd","kfc","subway","dominos","ayam","ikan","makan"],
    "Groceries":     ["grocery","groceries","supermarket","market","pasar","vegetable","vege","fruit","meat","chicken","fish","egg","rice","tesco","aeon","giant","mydin","econsave","speedmart","lotus","bms"],
    "Transport":     ["cab","taxi","grab","gojek","bus","train","lrt","mrt","ktm","toll","parking","petrol","fuel","flight","airasia","malindo","ferry","uber","commuter","monorail","metro"],
    "Shopping":      ["shop","shopping","clothes","shirt","pants","shoes","sneakers","bag","gadget","laptop","phone","iphone","samsung","lazada","shopee","amazon","mall","online","fashion"],
    "Bills":         ["bill","electricity","tnb","water","internet","wifi","unifi","maxis","celcom","digi","astro","insurance","netflix","spotify","youtube","reload","topup","postpaid"],
    "Housing":       ["rent","condo","apartment","flat","maintenance","repair","renovation","furniture","ikea","laundry","dobi","cleaning","plumber"],
    "Health":        ["clinic","hospital","pharmacy","medicine","doctor","dentist","optical","gym","supplement","vitamin","guardian","watson","scan"],
    "Entertainment": ["movie","cinema","tgv","gsc","gaming","game","concert","karaoke","bowling","genting","sunway","ticket"],
    "Travel":        ["hotel","resort","airbnb","holiday","vacation","trip","overseas","hostel","chalet","tour","visa"],
    "Education":     ["school","tuition","course","book","university","college","exam","udemy","training","workshop"]
}

EMOJI = {
    "Food":"🍔","Groceries":"🛒","Transport":"🚌","Shopping":"🛍️",
    "Bills":"📋","Housing":"🏠","Health":"💊","Entertainment":"🎬",
    "Travel":"✈️","Education":"📚","General":"📦"
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
    item   = re.sub(r'\d+(?:\.\d+)?', '', text, count=1).strip()
    item   = re.sub(r'\s+', ' ', item).strip() or text.strip()
    return item, amount, detect_category(text)

def get_sheet():
    creds_dict = json.loads(CREDS_JSON)
    print("Using email:", creds_dict.get("client_email"))
    print("Sheet ID:", SHEET_ID)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).get_worksheet(0)

def send_msg(chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10
    )

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data    = request.json
        message = data.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        text    = message.get("text", "").strip()

        if not chat_id or not text:
            return "ok", 200

        sheet = get_sheet()

        if text == "/day":
            send_range(chat_id, sheet, "day")
        elif text == "/month":
            send_range(chat_id, sheet, "month")
        elif text == "/year":
            send_range(chat_id, sheet, "year")
        elif text == "/list":
            send_list(chat_id, sheet)
        elif text.startswith("/"):
            send_msg(chat_id, "⚠️ Type expense:\n• cab 10\n• market 50\n• lunch 12\n\nCommands: /day /month /year /list")
        else:
            item, amount, category = parse_expense(text)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.append_row([now, item, amount, category])
            print("SAVED:", item, amount, category)
            send_msg(chat_id,
                f"✅ Saved!\n\n"
                f"📝 {item}\n"
                f"💰 RM{amount}\n"
                f"📂 {EMOJI.get(category,'📦')} {category}"
            )

    except Exception as ex:
        print("ERROR:", ex)
        import traceback
        traceback.print_exc()

    return "ok", 200

def send_range(chat_id, sheet, period):
    rows  = sheet.get_all_values()
    now   = datetime.now()
    msg   = f"🧾 {period.upper()} Expenses:\n\n"
    total = 0
    count = 0
    cats  = {}
    for row in rows:
        if not row[0]:
            continue
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
            amt    = float(row[2]) if row[2] else 0
            total += amt
            cat    = row[3]
            msg   += f"• {row[1]} — RM{amt} ({cat})\n"
            cats[cat] = cats.get(cat, 0) + amt
    if count == 0:
        msg = f"📭 No expenses for {period}."
    else:
        msg += f"\n💰 Total: RM{total:.2f}\n\n📊 By Category:\n"
        for c, v in cats.items():
            msg += f"  {EMOJI.get(c,'📦')} {c}: RM{v:.2f}\n"
    send_msg(chat_id, msg)

def send_list(chat_id, sheet):
    rows  = sheet.get_all_values()
    valid = [r for r in rows if r[0]]
    if not valid:
        send_msg(chat_id, "📭 No expenses yet.")
        return
    msg   = "🧾 Last 10 Expenses:\n\n"
    start = max(0, len(valid) - 10)
    for row in valid[start:]:
        try:
            d        = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            date_str = f"{d.day}/{d.month}"
        except:
            date_str = row[0]
        msg += f"• [{date_str}] {EMOJI.get(row[3],'📦')} {row[1]} — RM{row[2]} ({row[3]})\n"
    send_msg(chat_id, msg)

@app.route("/")
def home():
    return "Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)