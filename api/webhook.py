from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}"

FLAVORS = [
    "tropical fruit", "kiwi passion", "blue cherry explosion",
    "white peach razz", "cherry berry", "strawberry banana",
    "peach ice", "cherry peach limonade", "peach mangue pineapple",
    "Lady Killa"
]

PRIX_VENTE = 10
STOCK_INITIAL = 10

# ── Google Sheets ──────────────────────────────────────────────
def get_sheets():
    creds_json = os.environ.get("GOOGLE_CREDS")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])
    client = gspread.authorize(creds)
    sh = client.open_by_key(SPREADSHEET_ID)
    return sh

def get_journal_data():
    sh = get_sheets()
    ws = sh.worksheet("JOURNAL")
    return ws.get_all_values()

def append_journal(row):
    sh = get_sheets()
    ws = sh.worksheet("JOURNAL")
    ws.append_row(row)

def append_crome(row):
    sh = get_sheets()
    ws = sh.worksheet("CROMES")
    ws.append_row(row)

def get_cromes():
    sh = get_sheets()
    ws = sh.worksheet("CROMES")
    return ws.get_all_values()

def delete_crome(row_idx):
    sh = get_sheets()
    ws = sh.worksheet("CROMES")
    ws.delete_rows(row_idx)

def update_journal_crome(prenom, flavor):
    sh = get_sheets()
    ws = sh.worksheet("JOURNAL")
    data = ws.get_all_values()
    for i, row in enumerate(data[1:], 2):
        if len(row) >= 8 and row[7] == prenom and row[2] == flavor and row[6] == "Crome":
            ws.update_cell(i, 6, "Paye")
            break

# ── Session (fichier temporaire /tmp) ─────────────────────────
def get_session(chat_id):
    path = f"/tmp/session_{chat_id}.json"
    try:
        with open(path, "r") as f:
            return json.load(f)
    except:
        return {}

def set_session(chat_id, data):
    path = f"/tmp/session_{chat_id}.json"
    with open(path, "w") as f:
        json.dump(data, f)

def clear_session(chat_id):
    path = f"/tmp/session_{chat_id}.json"
    try:
        os.remove(path)
    except:
        pass

# ── Telegram API ───────────────────────────────────────────────
def tg_post(method, data):
    url = f"{TELEGRAM_URL}/{method}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"TG error: {e}")

def send_message(chat_id, text):
    tg_post("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

def send_keyboard(chat_id, text, buttons):
    tg_post("sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": buttons}
    })

def edit_message(chat_id, msg_id, text):
    tg_post("editMessageText", {
        "chat_id": chat_id, "message_id": msg_id,
        "text": text, "parse_mode": "Markdown"
    })

def answer_callback(callback_id):
    tg_post("answerCallbackQuery", {"callback_query_id": callback_id})

# ── Bot logic ──────────────────────────────────────────────────
def send_welcome(chat_id):
    send_keyboard(chat_id,
        "👋 *Puff Tracker*\n\n"
        "➕ /vente — Nouvelle transaction\n"
        "📊 /stats — Résumé complet\n"
        "🍬 /gouts — Stock par goût\n"
        "⏳ /paye — Encaisser un crome\n"
        "❓ /aide — Ce message",
        [
            [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
            [{"text": "📊 Stats", "callback_data": "menu:stats"}, {"text": "🍬 Goûts", "callback_data": "menu:gouts"}],
            [{"text": "⏳ Cromes", "callback_data": "menu:paye"}]
        ]
    )

def ask_flavor(chat_id):
    rows = []
    for i in range(0, len(FLAVORS), 2):
        row = [{"text": FLAVORS[i], "callback_data": f"flavor:{FLAVORS[i]}"}]
        if i+1 < len(FLAVORS):
            row.append({"text": FLAVORS[i+1], "callback_data": f"flavor:{FLAVORS[i+1]}"})
        rows.append(row)
    rows.append([{"text": "❌ Annuler", "callback_data": "cancel"}])
    send_keyboard(chat_id, "🍬 *Quel goût ?*", rows)

def ask_payment(chat_id):
    send_keyboard(chat_id, "💰 *Paiement ?*", [
        [{"text": "💵 Liquide", "callback_data": "pay:Liquide"}, {"text": "💳 Paylib", "callback_data": "pay:Paylib"}],
        [{"text": "❌ Annuler", "callback_data": "cancel"}]
    ])

def ask_status(chat_id):
    send_keyboard(chat_id, "📋 *Statut ?*", [
        [{"text": "✅ Payé", "callback_data": "status:Paye"}],
        [{"text": "⏳ En attente — Crome", "callback_data": "status:En attente"}],
        [{"text": "🎁 Offert — Réduction", "callback_data": "status:Offert"}],
        [{"text": "🔧 Arrangement — Cassée", "callback_data": "status:Arrangement"}],
        [{"text": "❌ Annuler", "callback_data": "cancel"}]
    ])

def show_confirm(chat_id, session):
    prenom_line = f"👤 {session.get('prenom')}\n" if session.get("prenom") else ""
    msg = (
        f"📝 *Récap :*\n\n"
        f"🍬 {session.get('flavor')}\n"
        f"💰 {session.get('payment')}\n"
        f"📋 {session.get('status')}\n"
        f"{prenom_line}"
        f"💶 {session.get('prix')} EUR\n\n"
        f"✅ Confirmer ?"
    )
    send_keyboard(chat_id, msg, [
        [{"text": "✅ Oui", "callback_data": "confirm:oui"}, {"text": "❌ Non", "callback_data": "confirm:non"}]
    ])

def save_transaction(chat_id, session):
    now = datetime.now()
    date = now.strftime("%d/%m/%Y")
    heure = now.strftime("%H:%M")
    row = [date, heure, session["flavor"], session["prix"],
           session["payment"], session["status"], session["categorie"],
           session.get("prenom", "")]
    append_journal(row)

    if session["categorie"] == "Crome":
        append_crome([session.get("prenom",""), session["flavor"], session["prix"], date, session["payment"]])

    restantes = get_restantes(session["flavor"])
    clear_session(chat_id)

    send_keyboard(chat_id,
        f"✅ *Enregistré !*\n\n"
        f"🍬 {session['flavor']}\n"
        f"{'👤 ' + session.get('prenom','') + chr(10) if session.get('prenom') else ''}"
        f"💶 {session['prix']} EUR — {session['status']}\n\n"
        f"📦 Restantes *{session['flavor']}* : *{restantes}/{STOCK_INITIAL}*",
        [
            [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
            [{"text": "📊 Stats", "callback_data": "menu:stats"}, {"text": "🍬 Goûts", "callback_data": "menu:gouts"}]
        ]
    )

def get_restantes(flavor):
    data = get_journal_data()
    count = sum(1 for row in data[1:] if len(row) > 2 and row[2] == flavor)
    return STOCK_INITIAL - count

def send_stats(chat_id):
    data = get_journal_data()
    vendues = ca = crome = paylib = liquide = reductions = arrangements = 0
    for row in data[1:]:
        if len(row) < 7: continue
        prix = float(row[3]) if row[3] else 0
        payment, statut, cat = row[4], row[5], row[6]
        if cat == "Vente": vendues += 1
        if statut == "Paye": ca += prix
        if statut == "En attente": crome += prix
        if payment == "Paylib" and statut == "Paye": paylib += prix
        if payment == "Liquide" and statut == "Paye": liquide += prix
        if cat == "Reduction": reductions += 1
        if cat == "Arrangement": arrangements += 1

    restantes = 100 - vendues - reductions - arrangements
    benefice = ca - 530
    progress = round((ca / 1000) * 100) if ca > 0 else 0

    send_keyboard(chat_id,
        f"📊 *RESUME PUFF TRACKER*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Puff restantes : *{restantes}/100*\n"
        f"✅ Puff vendues : *{vendues}*\n\n"
        f"💶 CA encaissé : *{ca} EUR*\n"
        f"🎯 Objectif : *1000 EUR* ({progress}%)\n"
        f"💰 Bénéfice : *{benefice} EUR*\n\n"
        f"💳 Paylib : *{paylib} EUR*\n"
        f"💵 Liquide : *{liquide} EUR*\n"
        f"⏳ Cromes : *{crome} EUR*\n\n"
        f"🎁 Réductions : *{reductions}*\n"
        f"🔧 Arrangements : *{arrangements}*",
        [
            [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
            [{"text": "🍬 Goûts", "callback_data": "menu:gouts"}, {"text": "⏳ Cromes", "callback_data": "menu:paye"}]
        ]
    )

def send_gouts(chat_id):
    data = get_journal_data()
    counts = {f: 0 for f in FLAVORS}
    for row in data[1:]:
        if len(row) > 2 and row[2] in counts:
            counts[row[2]] += 1

    msg = "🍬 *GOÛTS DISPONIBLES*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for f in FLAVORS:
        r = STOCK_INITIAL - counts[f]
        icon = "❌" if r <= 0 else "⚠️" if r <= 3 else "✅"
        msg += f"{icon} {f} : *{r}/{STOCK_INITIAL}*\n"

    send_keyboard(chat_id, msg, [
        [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
        [{"text": "📊 Stats", "callback_data": "menu:stats"}, {"text": "⏳ Cromes", "callback_data": "menu:paye"}]
    ])

def show_cromes(chat_id):
    data = get_cromes()
    if len(data) <= 1:
        send_message(chat_id, "✅ Aucun crome en attente !")
        return
    buttons = []
    for i, row in enumerate(data[1:], 1):
        if len(row) >= 3:
            buttons.append([{"text": f"👤 {row[0]} — {row[1]} ({row[2]}€)", "callback_data": f"paye:{i+1}"}])
    buttons.append([{"text": "❌ Fermer", "callback_data": "cancel"}])
    send_keyboard(chat_id, "⏳ *Cromes en attente — qui a payé ?*", buttons)

def payer_crome(chat_id, msg_id, row_idx):
    data = get_cromes()
    if row_idx >= len(data):
        edit_message(chat_id, msg_id, "❌ Crome introuvable.")
        return
    row = data[row_idx - 1]
    prenom, flavor, montant = row[0], row[1], row[2]
    update_journal_crome(prenom, flavor)
    delete_crome(row_idx)
    edit_message(chat_id, msg_id,
        f"✅ *{prenom}* a payé !\n\n"
        f"🍬 {flavor} — {montant} EUR\n"
        f"💰 Retiré des cromes et marqué Payé."
    )

# ── Handle update ──────────────────────────────────────────────
def handle_message(chat_id, text):
    session = get_session(chat_id)
    if session.get("step") == "waiting_prenom":
        session["prenom"] = text
        session["step"] = "confirm"
        set_session(chat_id, session)
        show_confirm(chat_id, session)
        return

    commands = {
        "/start": send_welcome, "/aide": send_welcome,
        "/vente": lambda c: (clear_session(c), ask_flavor(c)),
        "/stats": send_stats, "/gouts": send_gouts, "/paye": show_cromes
    }
    fn = commands.get(text)
    if fn:
        fn(chat_id)
    else:
        send_welcome(chat_id)

def handle_callback(chat_id, data, msg_id):
    if data == "cancel":
        clear_session(chat_id)
        edit_message(chat_id, msg_id, "❌ Annulé.")
        return
    if data == "menu:vente": clear_session(chat_id); ask_flavor(chat_id); return
    if data == "menu:stats": send_stats(chat_id); return
    if data == "menu:gouts": send_gouts(chat_id); return
    if data == "menu:paye": show_cromes(chat_id); return
    if data.startswith("paye:"):
        payer_crome(chat_id, msg_id, int(data.split(":")[1]))
        return
    if data == "confirm:oui":
        session = get_session(chat_id)
        save_transaction(chat_id, session)
        return
    if data == "confirm:non":
        clear_session(chat_id)
        edit_message(chat_id, msg_id, "❌ Annulé.")
        return

    session = get_session(chat_id)
    if data.startswith("flavor:"):
        session["flavor"] = data.replace("flavor:", "")
        session["step"] = "payment"
        set_session(chat_id, session)
        edit_message(chat_id, msg_id, f"🍬 Goût : *{session['flavor']}*")
        ask_payment(chat_id)
    elif data.startswith("pay:"):
        session["payment"] = data.replace("pay:", "")
        session["step"] = "status"
        set_session(chat_id, session)
        edit_message(chat_id, msg_id, f"💰 Paiement : *{session['payment']}*")
        ask_status(chat_id)
    elif data.startswith("status:"):
        status = data.replace("status:", "")
        session["status"] = status
        if status == "Offert":
            session.update({"categorie": "Reduction", "prix": 0, "payment": "-", "step": "confirm"})
        elif status == "Arrangement":
            session.update({"categorie": "Arrangement", "prix": 0, "payment": "-", "step": "confirm"})
        elif status == "En attente":
            session.update({"categorie": "Crome", "prix": PRIX_VENTE, "step": "waiting_prenom"})
            set_session(chat_id, session)
            edit_message(chat_id, msg_id, "📋 Statut : *En attente (Crome)*")
            send_message(chat_id, "👤 Tape le *prénom* de la personne :")
            return
        else:
            session.update({"categorie": "Vente", "prix": PRIX_VENTE, "step": "confirm"})
        set_session(chat_id, session)
        show_confirm(chat_id, session)

# ── Vercel handler ─────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)
        try:
            update = json.loads(body)
            if "message" in update:
                chat_id = update["message"]["chat"]["id"]
                text = update["message"].get("text", "")
                handle_message(chat_id, text)
            elif "callback_query" in update:
                cq = update["callback_query"]
                chat_id = cq["message"]["chat"]["id"]
                msg_id = cq["message"]["message_id"]
                answer_callback(cq["id"])
                handle_callback(chat_id, cq["data"], msg_id)
        except Exception as e:
            print(f"Error: {e}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Puff Tracker Bot actif!")
