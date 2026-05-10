import os
import re
import json
import requests
import csv
import io
from flask import Flask, request
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime

app = Flask(__name__)

TOKEN      = os.environ.get("TOKEN")
SHEET_ID   = os.environ.get("SPREADSHEET_ID")
CREDS_JSON = os.environ.get("GOOGLE_CREDS")

CATEGORIES = {
    "Food":          ["food","meal","eat","lunch","dinner","breakfast","restaurant","cafe","coffee","tea","drink","snack","burger","pizza","nasi","mee","roti","mamak","hawker","takeaway","delivery","mcd","kfc","subway","dominos","ayam","ikan","makan","brunch"],
    "Groceries":     ["grocery","groceries","supermarket","market","pasar","vegetable","vege","fruit","meat","chicken","fish","egg","rice","tesco","aeon","giant","mydin","econsave","speedmart","lotus","bms","wetmarket"],
    "Transport":     ["cab","taxi","grab","gojek","bus","train","lrt","mrt","ktm","toll","parking","petrol","fuel","flight","airasia","malindo","ferry","uber","commuter","monorail","metro","auto","rickshaw","tng"],
    "Shopping":      ["shop","shopping","clothes","shirt","pants","shoes","sneakers","bag","gadget","laptop","phone","iphone","samsung","lazada","shopee","amazon","mall","online","fashion","watch","earphone"],
    "Bills":         ["bill","electricity","tnb","water","internet","wifi","unifi","maxis","celcom","digi","astro","insurance","netflix","spotify","youtube","reload","topup","postpaid","subscription","takaful"],
    "Housing":       ["rent","condo","apartment","flat","maintenance","repair","renovation","furniture","ikea","laundry","dobi","cleaning","plumber","electrician"],
    "Health":        ["clinic","hospital","pharmacy","medicine","doctor","dentist","optical","gym","supplement","vitamin","guardian","watson","scan","specialist"],
    "Entertainment": ["movie","cinema","tgv","gsc","gaming","game","concert","karaoke","bowling","genting","sunway","ticket","steam"],
    "Travel":        ["hotel","resort","airbnb","holiday","vacation","trip","overseas","hostel","chalet","tour","visa","passport"],
    "Education":     ["school","tuition","course","book","university","college","exam","udemy","training","workshop","seminar"]
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
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=[
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive"
        ]
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(SHEET_ID).get_worksheet(0)

def get_all_rows(sheet):
    rows  = sheet.get_all_values()
    valid = []
    for row in rows:
        if not row[0]:
            continue
        try:
            datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            valid.append(row)
        except:
            continue
    return valid

def send_msg(chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10
    )

def send_photo_url(chat_id, url):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
        json={"chat_id": chat_id, "photo": url},
        timeout=15
    )

def send_document(chat_id, filename, content, caption=""):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendDocument",
        data={"chat_id": chat_id, "caption": caption},
        files={"document": (filename, content, "text/csv")},
        timeout=15
    )

def send_chart(chat_id, sheet, period="all"):
    rows = get_all_rows(sheet)
    now  = datetime.now()
    cats = {}

    for row in rows:
        d = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        match = True
        if period == "day":   match = d.date() == now.date()
        if period == "month": match = d.year == now.year and d.month == now.month
        if period == "year":  match = d.year == now.year
        if not match:
            continue
        cat = row[3]
        amt = float(row[2]) if row[2] else 0
        cats[cat] = cats.get(cat, 0) + amt

    if not cats:
        send_msg(chat_id, f"📭 No data for chart ({period}).")
        return

    labels = list(cats.keys())
    values = [round(cats[k], 2) for k in labels]
    total  = sum(values)

    chart_config = {
        "type": "pie",
        "data": {
            "labels": [f"{labels[i]} RM{values[i]}" for i in range(len(labels))],
            "datasets": [{"data": values, "backgroundColor": [
                "#FF6384","#36A2EB","#FFCE56","#4BC0C0",
                "#9966FF","#FF9F40","#FF6384","#C9CBCF",
                "#7BC8A4","#E8C3B9"
            ]}]
        },
        "options": {
            "title": {
                "display": True,
                "text": f"Expenses ({period.upper()}) — Total: RM{total:.2f}",
                "fontSize": 16
            },
            "legend": {"position": "right"}
        }
    }

    url = "https://quickchart.io/chart?width=700&height=400&c=" + \
          requests.utils.quote(json.dumps(chart_config))

    send_photo_url(chat_id, url)

def send_table(chat_id, sheet, period="all"):
    rows     = get_all_rows(sheet)
    now      = datetime.now()
    filtered = []

    for row in rows:
        d = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        match = True
        if period == "day":   match = d.date() == now.date()
        if period == "month": match = d.year == now.year and d.month == now.month
        if period == "year":  match = d.year == now.year
        if match:
            filtered.append(row)

    if not filtered:
        send_msg(chat_id, f"📭 No expenses for {period}.")
        return

    total = 0
    msg   = f"📊 {period.upper()} Expenses:\n\n"
    for row in filtered:
        d      = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        amt    = float(row[2]) if row[2] else 0
        total += amt
        msg   += f"• {d.day}/{d.month} {row[1]} — RM{amt:.2f} ({row[3]})\n"
    msg += f"\n💰 Total: RM{total:.2f}"
    send_msg(chat_id, msg)

    # CSV download
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Item", "Amount", "Category"])
    for row in filtered:
        writer.writerow([row[0], row[1], row[2], row[3]])
    writer.writerow([])
    writer.writerow(["", "TOTAL", f"{total:.2f}", ""])

    csv_bytes = output.getvalue().encode("utf-8")
    filename  = f"expenses_{period}_{now.strftime('%Y%m%d')}.csv"
    send_document(chat_id, filename, csv_bytes, f"📥 {period.upper()} expenses CSV")

def send_range(chat_id, sheet, period):
    rows  = get_all_rows(sheet)
    now   = datetime.now()
    msg   = f"🧾 {period.upper()} Expenses:\n\n"
    total = 0
    count = 0
    cats  = {}

    for row in rows:
        d = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
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
        send_msg(chat_id, f"📭 No expenses for {period}.")
        return

    msg += f"\n💰 Total: RM{total:.2f}\n\n📊 By Category:\n"
    for c, v in cats.items():
        msg += f"  {EMOJI.get(c,'📦')} {c}: RM{v:.2f}\n"
    send_msg(chat_id, msg)

def send_list(chat_id, sheet):
    rows = get_all_rows(sheet)
    if not rows:
        send_msg(chat_id, "📭 No expenses yet.")
        return
    msg   = "🧾 Last 10 Expenses:\n\n"
    start = max(0, len(rows) - 10)
    for row in rows[start:]:
        d        = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        date_str = f"{d.day}/{d.month}"
        msg += f"• [{date_str}] {EMOJI.get(row[3],'📦')} {row[1]} — RM{row[2]} ({row[3]})\n"
    send_msg(chat_id, msg)

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
        elif text == "/chart":
            send_chart(chat_id, sheet, "all")
        elif text == "/chartday":
            send_chart(chat_id, sheet, "day")
        elif text == "/chartmonth":
            send_chart(chat_id, sheet, "month")
        elif text == "/chartyear":
            send_chart(chat_id, sheet, "year")
        elif text == "/tableday":
            send_table(chat_id, sheet, "day")
        elif text == "/tablemonth":
            send_table(chat_id, sheet, "month")
        elif text == "/tableyear":
            send_table(chat_id, sheet, "year")
        elif text == "/help":
            send_msg(chat_id,
                "💡 Commands:\n\n"
                "📊 Summary:\n"
                "/day — today\n"
                "/month — this month\n"
                "/year — this year\n"
                "/list — last 10\n\n"
                "📈 Charts:\n"
                "/chart — all time\n"
                "/chartday — today\n"
                "/chartmonth — this month\n"
                "/chartyear — this year\n\n"
                "📋 Table + CSV:\n"
                "/tableday — today\n"
                "/tablemonth — this month\n"
                "/tableyear — this year\n\n"
                "💾 Save expense:\n"
                "Just type anything!\n"
                "Examples:\n"
                "• grab 12\n"
                "• lunch nasi lemak 8.50\n"
                "• market 150\n"
                "• netflix 17"
            )
        elif text.startswith("/"):
            send_msg(chat_id, "❓ Unknown command. Type /help")
        else:
            item, amount, category = parse_expense(text)
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            sheet.append_row([now, item, amount, category])
            print(f"SAVED: {item} RM{amount} {category}")
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

@app.route("/")
def home():
    return "Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)