import os
import re
import json
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import csv
import io
from flask import Flask, request, send_file
from google.oauth2.service_account import Credentials
import gspread
from datetime import datetime

app = Flask(__name__)

TOKEN      = os.environ.get("TOKEN")
SHEET_ID   = os.environ.get("SPREADSHEET_ID")
CREDS_JSON = os.environ.get("GOOGLE_CREDS")
MAIL_FROM  = os.environ.get("MAIL_FROM")   # your gmail
MAIL_PASS  = os.environ.get("MAIL_PASS")   # gmail app password
MAIL_TO    = os.environ.get("MAIL_TO")     # recipient email

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

# ─── CATEGORY DETECTION ───────────────────────────────────────────────────────

def detect_category(text):
    t = text.lower()
    for cat, words in CATEGORIES.items():
        for w in words:
            if w in t:
                return cat
    return "General"

# ─── PARSE EXPENSE ────────────────────────────────────────────────────────────

def parse_expense(text):
    nums   = re.findall(r'\d+(?:\.\d+)?', text)
    amount = float(nums[-1]) if nums else 0
    item   = re.sub(r'\d+(?:\.\d+)?', '', text, count=1).strip()
    item   = re.sub(r'\s+', ' ', item).strip() or text.strip()
    return item, amount, detect_category(text)

# ─── SHEET ────────────────────────────────────────────────────────────────────

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
    rows = sheet.get_all_values()
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

# ─── TELEGRAM HELPERS ─────────────────────────────────────────────────────────

def send_msg(chat_id, text):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=10
    )

def send_photo(chat_id, url):
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

# ─── CHART ────────────────────────────────────────────────────────────────────

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
            "labels": [f"{labels[i]}\nRM{values[i]}" for i in range(len(labels))],
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

    send_photo(chat_id, url)

# ─── TABLE / CSV ──────────────────────────────────────────────────────────────

def send_table(chat_id, sheet, period="all"):
    rows = get_all_rows(sheet)
    now  = datetime.now()
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

    # Send text table
    total = 0
    msg   = f"📊 {period.upper()} Expenses:\n\n"
    msg  += f"{'Date':<12} {'Item':<15} {'RM':>7} {'Category'}\n"
    msg  += "─" * 45 + "\n"
    for row in filtered:
        d      = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        date_s = f"{d.day}/{d.month}"
        item   = row[1][:14]
        amt    = float(row[2]) if row[2] else 0
        cat    = row[3][:10]
        total += amt
        msg   += f"{date_s:<12} {item:<15} {amt:>7.2f} {cat}\n"
    msg += "─" * 45 + "\n"
    msg += f"{'TOTAL':<28} {total:>7.2f}\n"

    send_msg(chat_id, f"```\n{msg}```")

    # Send CSV file for download
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Item", "Amount", "Category"])
    for row in filtered:
        writer.writerow([row[0], row[1], row[2], row[3]])
    writer.writerow([])
    writer.writerow(["", "TOTAL", total, ""])

    csv_bytes = output.getvalue().encode("utf-8")
    filename  = f"expenses_{period}_{now.strftime('%Y%m%d')}.csv"

    send_document(chat_id, filename, csv_bytes, f"📥 Download {period} expenses")

# ─── SUMMARY ──────────────────────────────────────────────────────────────────

def send_range(chat_id, sheet, period):
    rows = get_all_rows(sheet)
    now  = datetime.now()
    msg  = f"🧾 {period.upper()} Expenses:\n\n"
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

# ─── LIST ─────────────────────────────────────────────────────────────────────

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

# ─── EMAIL REPORT ─────────────────────────────────────────────────────────────

def send_email_report(sheet, period="day"):
    try:
        rows = get_all_rows(sheet)
        now  = datetime.now()
        filtered = []
        total    = 0
        cats     = {}

        for row in rows:
            d = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
            match = False
            if period == "day":   match = d.date() == now.date()
            if period == "month": match = d.year == now.year and d.month == now.month
            if period == "year":  match = d.year == now.year
            if match:
                filtered.append(row)
                amt = float(row[2]) if row[2] else 0
                total += amt
                cat   = row[3]
                cats[cat] = cats.get(cat, 0) + amt

        if not filtered:
            print("No expenses to email")
            return

        # Build HTML email
        date_str = now.strftime("%d %B %Y")
        html  = f"""
        <html><body>
        <h2>📊 Daily Expense Report — {date_str}</h2>
        <p><strong>Total: RM{total:.2f}</strong></p>
        <h3>By Category:</h3>
        <ul>
        """
        for c, v in cats.items():
            html += f"<li>{EMOJI.get(c,'📦')} {c}: RM{v:.2f}</li>"
        html += "</ul><h3>All Expenses:</h3>"
        html += "<table border='1' cellpadding='6' cellspacing='0'>"
        html += "<tr><th>Date</th><th>Item</th><th>Amount</th><th>Category</th></tr>"
        for row in filtered:
            html += f"<tr><td>{row[0]}</td><td>{row[1]}</td><td>RM{row[2]}</td><td>{row[3]}</td></tr>"
        html += f"</table><br><p><strong>Total: RM{total:.2f}</strong></p>"
        html += "</body></html>"

        # Build CSV attachment
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Date", "Item", "Amount", "Category"])
        for row in filtered:
            writer.writerow([row[0], row[1], row[2], row[3]])
        writer.writerow([])
        writer.writerow(["", "TOTAL", total, ""])
        csv_content = output.getvalue().encode("utf-8")

        # Send email
        msg = MIMEMultipart("mixed")
        msg["From"]    = MAIL_FROM
        msg["To"]      = MAIL_TO
        msg["Subject"] = f"💰 Expense Report — {date_str} — RM{total:.2f}"

        msg.attach(MIMEText(html, "html"))

        part = MIMEBase("application", "octet-stream")
        part.set_payload(csv_content)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition",
                        f"attachment; filename=expenses_{now.strftime('%Y%m%d')}.csv")
        msg.attach(part)

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(MAIL_FROM, MAIL_PASS)
        server.sendmail(MAIL_FROM, MAIL_TO, msg.as_string())
        server.quit()

        print(f"Email sent to {MAIL_TO}")

    except Exception as ex:
        print("Email error:", ex)
        import traceback
        traceback.print_exc()

# ─── WEBHOOK ──────────────────────────────────────────────────────────────────

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

        # ── COMMANDS ──
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

        elif text == "/emailreport":
            send_email_report(sheet, "day")
            send_msg(chat_id, "📧 Daily report sent to email!")

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
                "📋 Table + Download:\n"
                "/tableday — today CSV\n"
                "/tablemonth — month CSV\n"
                "/tableyear — year CSV\n\n"
                "📧 Email:\n"
                "/emailreport — send now\n\n"
                "💾 Save expense:\n"
                "Just type anything!\n"
                "Examples:\n"
                "• grab 12\n"
                "• lunch nasi lemak 8.50\n"
                "• market 150\n"
                "• netflix subscription 17"
            )

        elif text.startswith("/"):
            send_msg(chat_id, "❓ Unknown command. Type /help")

        else:
            # ── SAVE EXPENSE ──
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

# ─── AUTO EMAIL at end of day ──────────────────────────────────────────────────

@app.route("/sendreport", methods=["GET"])
def sendreport():
    try:
        sheet = get_sheet()
        send_email_report(sheet, "day")
        return "Report sent", 200
    except Exception as ex:
        return str(ex), 500

@app.route("/")
def home():
    return "Bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)