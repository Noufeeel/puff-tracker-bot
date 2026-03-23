from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
import urllib.parse
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ================================================================
# CONFIG
# ================================================================
TOKEN = os.environ.get("TELEGRAM_TOKEN")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}"

VENDEURS = ["Belk", "Nayel", "Nono"]
PRIX_VENTE = 10
ALERTE_FAIBLE = 3
ALERTE_STOCK_TOTAL = 20
HEURE_RESUME = 0  # 00h00

# IDs Telegram des 3 utilisateurs — à remplir après premier /start
# Laisse vide, le bot les enregistre automatiquement
CHAT_IDS_FILE = "/tmp/chat_ids.json"

# ================================================================
# GOOGLE SHEETS
# ================================================================
def get_sheets():
    creds_dict = json.loads(os.environ.get("GOOGLE_CREDS"))
    creds = Credentials.from_service_account_info(creds_dict, scopes=[
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive"
    ])
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def get_ws(name):
    return get_sheets().worksheet(name)

def get_journal():
    return get_ws("JOURNAL").get_all_values()

def append_journal(row):
    get_ws("JOURNAL").append_row(row)

def delete_journal_row(row_idx):
    get_ws("JOURNAL").delete_rows(row_idx)

def get_cromes():
    return get_ws("CROMES").get_all_values()

def append_crome(row):
    get_ws("CROMES").append_row(row)

def delete_crome_row(row_idx):
    get_ws("CROMES").delete_rows(row_idx)

def update_journal_statut(row_idx, statut):
    get_ws("JOURNAL").update_cell(row_idx, 6, statut)

def get_config():
    try:
        data = get_ws("CONFIG").get_all_values()
        cfg = {}
        for row in data[1:]:
            if len(row) >= 2:
                cfg[row[0]] = row[1]
        return cfg
    except:
        return {}

def set_config(key, value):
    ws = get_ws("CONFIG")
    data = ws.get_all_values()
    for i, row in enumerate(data):
        if row and row[0] == key:
            ws.update_cell(i+1, 2, value)
            return
    ws.append_row([key, value])

def get_flavors():
    cfg = get_config()
    flavors_str = cfg.get("FLAVORS", "")
    if flavors_str:
        return [f.strip() for f in flavors_str.split("|") if f.strip()]
    return [
        "tropical fruit", "kiwi passion", "blue cherry explosion",
        "white peach razz", "cherry berry", "strawberry banana",
        "peach ice", "cherry peach limonade", "peach mangue pineapple",
        "Lady Killa"
    ]

def get_stock_config():
    cfg = get_config()
    return {
        "cartons": int(cfg.get("CARTONS", 10)),
        "puff_par_gout": int(cfg.get("PUFF_PAR_GOUT", 10)),
        "prix_vente": int(cfg.get("PRIX_VENTE", 10)),
        "cout_achat": int(cfg.get("COUT_ACHAT", 53)),
    }

# ================================================================
# CHAT IDS (notifications)
# ================================================================
def load_chat_ids():
    try:
        with open(CHAT_IDS_FILE, "r") as f:
            return json.load(f)
    except:
        return []

def save_chat_id(chat_id):
    ids = load_chat_ids()
    if chat_id not in ids:
        ids.append(chat_id)
        with open(CHAT_IDS_FILE, "w") as f:
            json.dump(ids, f)

def notify_all(text, exclude_chat_id=None):
    ids = load_chat_ids()
    for cid in ids:
        if cid != exclude_chat_id:
            send_message(cid, text)

def notify_everyone(text):
    for cid in load_chat_ids():
        send_message(cid, text)

# ================================================================
# SESSION
# ================================================================
def get_session(chat_id):
    try:
        with open(f"/tmp/s_{chat_id}.json", "r") as f:
            return json.load(f)
    except:
        return {}

def set_session(chat_id, data):
    with open(f"/tmp/s_{chat_id}.json", "w") as f:
        json.dump(data, f)

def clear_session(chat_id):
    try:
        os.remove(f"/tmp/s_{chat_id}.json")
    except:
        pass

# ================================================================
# STOCK HELPERS
# ================================================================
def get_stock_restant(flavor):
    data = get_journal()
    cfg = get_stock_config()
    count = sum(1 for row in data[1:] if len(row) > 2 and row[2] == flavor)
    return cfg["puff_par_gout"] - count

def get_all_stock():
    flavors = get_flavors()
    return {f: get_stock_restant(f) for f in flavors}

def get_stats():
    data = get_journal()
    cfg = get_stock_config()
    total_stock = cfg["cartons"] * cfg["puff_par_gout"]
    vendues = ca = crome_total = paylib = liquide = reductions = arrangements = 0
    ventes_par_vendeur = {v: 0 for v in VENDEURS}

    for row in data[1:]:
        if len(row) < 7:
            continue
        prix = float(row[3]) if row[3] else 0
        payment = row[4] if len(row) > 4 else ""
        statut = row[5] if len(row) > 5 else ""
        cat = row[6] if len(row) > 6 else ""
        vendeur = row[8] if len(row) > 8 else ""

        if cat == "Vente":
            vendues += 1
        if statut == "Paye":
            ca += prix
        if statut == "En attente":
            crome_total += prix
        if payment == "Paylib" and statut == "Paye":
            paylib += prix
        if payment == "Liquide" and statut == "Paye":
            liquide += prix
        if cat == "Reduction":
            reductions += 1
        if cat == "Arrangement":
            arrangements += 1
        if vendeur in ventes_par_vendeur and cat == "Vente":
            ventes_par_vendeur[vendeur] += 1

    cout_total = cfg["cartons"] * cfg["cout_achat"]
    restantes = total_stock - vendues - reductions - arrangements
    benefice = ca - cout_total
    objectif = total_stock * cfg["prix_vente"]
    progress = round((ca / objectif) * 100) if objectif > 0 else 0
    bars = round(progress / 10)
    bar_str = "▓" * bars + "░" * (10 - bars)

    return {
        "total_stock": total_stock,
        "vendues": vendues,
        "restantes": restantes,
        "ca": ca,
        "objectif": objectif,
        "benefice": benefice,
        "progress": progress,
        "bar_str": bar_str,
        "paylib": paylib,
        "liquide": liquide,
        "crome_total": crome_total,
        "reductions": reductions,
        "arrangements": arrangements,
        "ventes_par_vendeur": ventes_par_vendeur,
        "cout_total": cout_total,
    }

# ================================================================
# TELEGRAM API
# ================================================================
def tg_post(method, data):
    url = f"{TELEGRAM_URL}/{method}"
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"TG error {method}: {e}")

def send_message(chat_id, text):
    tg_post("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"})

def send_keyboard(chat_id, text, buttons):
    tg_post("sendMessage", {
        "chat_id": chat_id, "text": text, "parse_mode": "Markdown",
        "reply_markup": {"inline_keyboard": buttons}
    })

def edit_message(chat_id, msg_id, text, buttons=None):
    data = {"chat_id": chat_id, "message_id": msg_id, "text": text, "parse_mode": "Markdown"}
    if buttons:
        data["reply_markup"] = {"inline_keyboard": buttons}
    tg_post("editMessageText", data)

def answer_callback(callback_id, text=""):
    tg_post("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

def send_document(chat_id, filename, content, caption=""):
    boundary = "----FormBoundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f"Content-Type: text/plain\r\n\r\n{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{TELEGRAM_URL}/sendDocument",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"Send doc error: {e}")

# ================================================================
# MENUS PRINCIPAUX
# ================================================================
def send_welcome(chat_id, nom=""):
    greeting = f"👋 Salut *{nom}* !" if nom else "👋 *Puff Tracker*"
    
    # Stats rapides du jour
    data = get_journal()
    today = datetime.now().strftime("%d/%m/%Y")
    ventes_today = sum(1 for row in data[1:] if len(row) > 6 and row[0] == today and row[6] == "Vente")
    
    send_keyboard(chat_id,
        f"{greeting}\n\n"
        f"📅 Ventes aujourd'hui : *{ventes_today}*\n\n"
        f"➕ /vente — Nouvelle transaction\n"
        f"📊 /stats — Résumé complet\n"
        f"🍬 /gouts — Stock par goût\n"
        f"⏳ /paye — Encaisser un crome\n"
        f"🔄 /annuler — Annuler une vente\n"
        f"📦 /newstock — Nouveau stock\n"
        f"❓ /aide — Ce message",
        [
            [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
            [{"text": "📊 Stats", "callback_data": "menu:stats"}, {"text": "🍬 Goûts", "callback_data": "menu:gouts"}],
            [{"text": "⏳ Cromes", "callback_data": "menu:paye"}, {"text": "🔄 Annuler vente", "callback_data": "menu:annuler"}],
            [{"text": "📦 Nouveau stock", "callback_data": "menu:newstock"}]
        ]
    )

def send_stats(chat_id):
    s = get_stats()
    vpv = s["ventes_par_vendeur"]
    top = sorted(vpv.items(), key=lambda x: x[1], reverse=True)
    top_str = " | ".join([f"{n}: {v}" for n, v in top])

    send_keyboard(chat_id,
        f"📊 *RÉSUMÉ PUFF TRACKER*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 Restantes : *{s['restantes']}/{s['total_stock']}*\n"
        f"✅ Vendues : *{s['vendues']}*\n\n"
        f"💶 CA encaissé : *{s['ca']} EUR*\n"
        f"🎯 Objectif : *{s['objectif']} EUR*\n"
        f"{s['bar_str']} *{s['progress']}%*\n"
        f"💰 Bénéfice : *{s['benefice']} EUR*\n\n"
        f"💳 Paylib : *{s['paylib']} EUR*\n"
        f"💵 Liquide : *{s['liquide']} EUR*\n"
        f"⏳ Cromes : *{s['crome_total']} EUR*\n\n"
        f"🎁 Réductions : *{s['reductions']}*\n"
        f"🔧 Arrangements : *{s['arrangements']}*\n\n"
        f"👥 *Ventes par vendeur :*\n{top_str}",
        [
            [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
            [{"text": "🍬 Goûts", "callback_data": "menu:gouts"}, {"text": "⏳ Cromes", "callback_data": "menu:paye"}],
            [{"text": "🏠 Menu", "callback_data": "menu:home"}]
        ]
    )

def send_gouts(chat_id):
    stock = get_all_stock()
    msg = "🍬 *GOÛTS DISPONIBLES*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for f, r in stock.items():
        icon = "❌" if r <= 0 else "⚠️" if r <= ALERTE_FAIBLE else "✅"
        msg += f"{icon} {f} : *{r}*\n"

    send_keyboard(chat_id, msg, [
        [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
        [{"text": "📊 Stats", "callback_data": "menu:stats"}, {"text": "⏳ Cromes", "callback_data": "menu:paye"}],
        [{"text": "🏠 Menu", "callback_data": "menu:home"}]
    ])

# ================================================================
# VENTE
# ================================================================
def ask_flavor(chat_id):
    stock = get_all_stock()
    rows = []
    items = list(stock.items())
    for i in range(0, len(items), 2):
        row = []
        for j in range(2):
            if i+j < len(items):
                f, r = items[i+j]
                label = f"❌ {f} — 0" if r <= 0 else f"{'⚠️' if r <= ALERTE_FAIBLE else '✅'} {f} — {r}"
                row.append({"text": label, "callback_data": f"flavor:{f}"})
        rows.append(row)
    rows.append([{"text": "❌ Annuler", "callback_data": "cancel"}])
    send_keyboard(chat_id, "🍬 *Quel goût ?*", rows)

def ask_payment(chat_id):
    send_keyboard(chat_id, "💰 *Mode de paiement ?*", [
        [{"text": "💵 Liquide", "callback_data": "pay:Liquide"}, {"text": "💳 Paylib", "callback_data": "pay:Paylib"}],
        [{"text": "⏳ Crome", "callback_data": "pay:Crome"}],
        [{"text": "🎁 Offert — Réduction", "callback_data": "pay:Offert"}, {"text": "🔧 Arrangement", "callback_data": "pay:Arrangement"}],
        [{"text": "❌ Annuler", "callback_data": "cancel"}]
    ])

def ask_vendeur(chat_id):
    buttons = [[{"text": v, "callback_data": f"vendeur:{v}"}] for v in VENDEURS]
    buttons.append([{"text": "❌ Annuler", "callback_data": "cancel"}])
    send_keyboard(chat_id, "👤 *C'est qui ?*", buttons)

def show_confirm(chat_id, session):
    prenom_client = f"\n👤 Client : *{session.get('prenom_client')}*" if session.get("prenom_client") else ""
    msg = (
        f"📝 *Récap :*\n\n"
        f"🍬 {session.get('flavor')}\n"
        f"💰 {session.get('payment')}\n"
        f"👤 Vendeur : *{session.get('vendeur')}*"
        f"{prenom_client}\n"
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
    flavor = session["flavor"]
    prix = session["prix"]
    payment = session["payment"]
    statut = session["statut"]
    cat = session["categorie"]
    vendeur = session.get("vendeur", "")
    prenom_client = session.get("prenom_client", "")

    append_journal([date, heure, flavor, prix, payment, statut, cat, prenom_client, vendeur])

    if cat == "Crome":
        append_crome([prenom_client, flavor, prix, date, payment, vendeur])

    restantes = get_stock_restant(flavor)
    clear_session(chat_id)

    # Notification aux autres
    notif_map = {
        "Vente": f"🛒 *{vendeur}* a vendu *{flavor}* — {prix}€ ({payment})",
        "Crome": f"⏳ *{vendeur}* a créé un crome pour *{prenom_client}* — {flavor} ({prix}€)",
        "Reduction": f"🎁 *{vendeur}* a offert *{flavor}* (réduction)",
        "Arrangement": f"🔧 *{vendeur}* a fait un arrangement — *{flavor}*",
    }
    notify_all(notif_map.get(cat, f"📝 Nouvelle transaction par {vendeur}"), exclude_chat_id=chat_id)

    # Alerte stock
    if restantes == 0:
        notify_everyone(f"❌ *{flavor}* est épuisé !")
    elif restantes <= ALERTE_FAIBLE:
        notify_everyone(f"⚠️ *{flavor}* — Plus que *{restantes}* restants !")

    # Alerte stock total
    s = get_stats()
    if s["restantes"] <= ALERTE_STOCK_TOTAL:
        notify_everyone(f"📦 Attention ! Plus que *{s['restantes']}* puff en stock au total !")

    send_keyboard(chat_id,
        f"✅ *Enregistré !*\n\n"
        f"🍬 {flavor}\n"
        f"👤 {vendeur}"
        f"{f' → {prenom_client}' if prenom_client else ''}\n"
        f"💶 {prix} EUR — {statut}\n\n"
        f"📦 *{flavor}* restantes : *{restantes}*",
        [
            [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
            [{"text": "📊 Stats", "callback_data": "menu:stats"}, {"text": "🍬 Goûts", "callback_data": "menu:gouts"}],
            [{"text": "🏠 Menu", "callback_data": "menu:home"}]
        ]
    )

# ================================================================
# CROMES
# ================================================================
def show_cromes(chat_id):
    data = get_cromes()
    if len(data) <= 1:
        send_keyboard(chat_id, "✅ Aucun crome en attente !", [
            [{"text": "🏠 Menu", "callback_data": "menu:home"}]
        ])
        return

    msg = "⏳ *CROMES EN ATTENTE*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    buttons = []
    for i, row in enumerate(data[1:], 1):
        if len(row) >= 4:
            prenom, flavor, montant, date = row[0], row[1], row[2], row[3]
            createur = row[5] if len(row) > 5 else "?"
            msg += f"👤 *{prenom}* — {flavor} — {montant}€\n📅 {date} | par {createur}\n\n"
            buttons.append([{"text": f"✅ {prenom} a payé", "callback_data": f"paye:{i+1}"},
                           {"text": f"🗑️ Supprimer", "callback_data": f"del_crome:{i+1}"}])

    buttons.append([{"text": "🏠 Menu", "callback_data": "menu:home"}])
    send_keyboard(chat_id, msg, buttons)

def payer_crome(chat_id, msg_id, row_idx):
    data = get_cromes()
    if row_idx > len(data):
        edit_message(chat_id, msg_id, "❌ Crome introuvable.")
        return
    row = data[row_idx - 1]
    prenom, flavor, montant = row[0], row[1], row[2]

    # Update journal
    jdata = get_journal()
    ws = get_ws("JOURNAL")
    for i, jrow in enumerate(jdata[1:], 2):
        if len(jrow) >= 8 and jrow[7] == prenom and jrow[2] == flavor and jrow[6] == "Crome":
            ws.update_cell(i, 6, "Paye")
            break

    delete_crome_row(row_idx)
    notify_all(f"💰 Crome encaissé ! *{prenom}* a payé *{flavor}* — {montant}€", exclude_chat_id=chat_id)

    edit_message(chat_id, msg_id,
        f"✅ *{prenom}* a payé !\n\n🍬 {flavor} — {montant}€\n💰 Marqué comme payé.",
        [[{"text": "⏳ Voir cromes", "callback_data": "menu:paye"}, {"text": "🏠 Menu", "callback_data": "menu:home"}]]
    )

# ================================================================
# ANNULER VENTE
# ================================================================
def show_annuler(chat_id):
    data = get_journal()
    if len(data) <= 1:
        send_message(chat_id, "❌ Aucune transaction à annuler.")
        return

    last = data[1:][-5:]  # 5 dernières
    last.reverse()
    msg = "🔄 *ANNULER UNE VENTE*\nChoisis la transaction à annuler :\n\n"
    buttons = []
    for i, row in enumerate(last):
        if len(row) >= 7:
            real_idx = len(data) - i
            label = f"{row[0]} {row[1]} — {row[2]} — {row[4]} — {row[8] if len(row) > 8 else '?'}"
            msg += f"{i+1}. {label}\n"
            buttons.append([{"text": f"🗑️ {label}", "callback_data": f"annuler:{real_idx}"}])

    buttons.append([{"text": "❌ Fermer", "callback_data": "cancel"}])
    send_keyboard(chat_id, msg, buttons)

def confirmer_annulation(chat_id, msg_id, row_idx):
    data = get_journal()
    if row_idx > len(data):
        edit_message(chat_id, msg_id, "❌ Transaction introuvable.")
        return
    row = data[row_idx - 1]
    flavor = row[2] if len(row) > 2 else "?"
    vendeur = row[8] if len(row) > 8 else "?"

    delete_journal_row(row_idx)
    notify_all(f"🔄 *{vendeur}* a annulé une vente — *{flavor}*", exclude_chat_id=chat_id)

    edit_message(chat_id, msg_id,
        f"✅ Transaction annulée !\n🍬 {flavor} — remis en stock.",
        [[{"text": "🏠 Menu", "callback_data": "menu:home"}]]
    )

# ================================================================
# NOUVEAU STOCK
# ================================================================
def ask_newstock_confirm(chat_id):
    send_keyboard(chat_id,
        "⚠️ *NOUVEAU STOCK*\n\n"
        "Tu vas réinitialiser le stock actuel.\n"
        "Un export de l'ancien stock sera envoyé avant.\n\n"
        "Tu es sûr ?",
        [
            [{"text": "✅ Oui, nouveau stock", "callback_data": "newstock:confirm"}],
            [{"text": "❌ Annuler", "callback_data": "cancel"}]
        ]
    )

def export_old_stock(chat_id):
    s = get_stats()
    stock = get_all_stock()
    data = get_journal()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    lines = [
        f"=== EXPORT STOCK — {now} ===\n",
        f"Stock total : {s['total_stock']} puff",
        f"Vendues : {s['vendues']}",
        f"Restantes : {s['restantes']}",
        f"CA encaissé : {s['ca']} EUR",
        f"Bénéfice : {s['benefice']} EUR",
        f"Paylib : {s['paylib']} EUR",
        f"Liquide : {s['liquide']} EUR",
        f"Cromes en attente : {s['crome_total']} EUR",
        f"Réductions : {s['reductions']}",
        f"Arrangements : {s['arrangements']}",
        "\n=== VENTES PAR VENDEUR ===",
    ]
    for v, nb in s["ventes_par_vendeur"].items():
        lines.append(f"{v} : {nb} ventes")

    lines.append("\n=== STOCK PAR GOÛT ===")
    for f, r in stock.items():
        lines.append(f"{f} : {r} restantes")

    lines.append("\n=== TOUTES LES TRANSACTIONS ===")
    for row in data[1:]:
        if len(row) >= 7:
            lines.append(" | ".join(str(x) for x in row))

    content = "\n".join(lines)
    filename = f"stock_export_{datetime.now().strftime('%d%m%Y_%H%M')}.txt"

    for cid in load_chat_ids():
        send_document(cid, filename, content, caption=f"📤 Export ancien stock — {now}")

def reset_stock(chat_id, new_flavors, cartons, puff_par_gout):
    # Sauvegarde config
    set_config("FLAVORS", "|".join(new_flavors))
    set_config("CARTONS", str(cartons))
    set_config("PUFF_PAR_GOUT", str(puff_par_gout))

    # Vide le journal
    ws = get_ws("JOURNAL")
    ws.clear()
    ws.append_row(["Date", "Heure", "Gout", "Prix (EUR)", "Paiement", "Statut", "Categorie", "Prenom Crome", "Vendeur"])

    # Vide les cromes
    wsc = get_ws("CROMES")
    wsc.clear()
    wsc.append_row(["Prenom", "Gout", "Montant (EUR)", "Date", "Paiement", "Vendeur"])

def start_newstock_flow(chat_id):
    session = {"step": "newstock_cartons"}
    set_session(chat_id, session)
    send_message(chat_id, "📦 *Combien de cartons as-tu pris ?*\n(Tape un nombre)")

# ================================================================
# RÉSUMÉ JOURNALIER
# ================================================================
def send_resume_journalier():
    data = get_journal()
    today = datetime.now().strftime("%d/%m/%Y")
    s = get_stats()

    ventes_today = [row for row in data[1:] if len(row) > 0 and row[0] == today]
    ca_today = sum(float(row[3]) for row in ventes_today if len(row) > 5 and row[5] == "Paye")
    nb_today = sum(1 for row in ventes_today if len(row) > 6 and row[6] == "Vente")

    cromes_data = get_cromes()
    nb_cromes = len(cromes_data) - 1

    # Top vendeur du jour
    vpv_today = {v: 0 for v in VENDEURS}
    for row in ventes_today:
        if len(row) > 8 and row[8] in vpv_today and row[6] == "Vente":
            vpv_today[row[8]] += 1
    top_today = max(vpv_today, key=vpv_today.get)
    top_nb = vpv_today[top_today]

    msg = (
        f"🌙 *RÉSUMÉ DU JOUR — {today}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ Ventes aujourd'hui : *{nb_today}*\n"
        f"💶 CA aujourd'hui : *{ca_today} EUR*\n\n"
        f"📊 CA total : *{s['ca']} EUR*\n"
        f"{s['bar_str']} *{s['progress']}%*\n"
        f"💰 Bénéfice : *{s['benefice']} EUR*\n\n"
        f"⏳ Cromes en attente : *{nb_cromes}*\n"
        f"📦 Stock restant : *{s['restantes']}*\n\n"
    )

    if top_nb > 0:
        msg += f"🏆 Top vendeur du jour : *{top_today}* ({top_nb} ventes)\n\n"

    # Goûts faibles
    stock = get_all_stock()
    faibles = [(f, r) for f, r in stock.items() if 0 < r <= ALERTE_FAIBLE]
    if faibles:
        msg += "⚠️ *Goûts à renouveler :*\n"
        for f, r in faibles:
            msg += f"  • {f} : {r} restants\n"

    notify_everyone(msg)

# ================================================================
# HANDLE UPDATE
# ================================================================
def handle_message(chat_id, text):
    save_chat_id(chat_id)
    session = get_session(chat_id)
    step = session.get("step", "")

    # Flows texte
    if step == "waiting_prenom_client":
        session["prenom_client"] = text
        session["step"] = "confirm"
        set_session(chat_id, session)
        show_confirm(chat_id, session)
        return

    if step == "newstock_cartons":
        try:
            session["newstock_cartons"] = int(text)
            session["step"] = "newstock_puff"
            set_session(chat_id, session)
            send_message(chat_id, "🍬 *Combien de puff par goût ?*\n(Tape un nombre)")
        except:
            send_message(chat_id, "❌ Tape un nombre valide.")
        return

    if step == "newstock_puff":
        try:
            session["newstock_puff"] = int(text)
            session["step"] = "newstock_flavors"
            set_session(chat_id, session)
            send_message(chat_id,
                "📝 *Liste tes goûts*\n\n"
                "Envoie-les séparés par des virgules :\n"
                "_Ex: tropical fruit, kiwi passion, peach ice_"
            )
        except:
            send_message(chat_id, "❌ Tape un nombre valide.")
        return

    if step == "newstock_flavors":
        flavors = [f.strip() for f in text.split(",") if f.strip()]
        if not flavors:
            send_message(chat_id, "❌ Liste invalide. Sépare les goûts par des virgules.")
            return

        cartons = session.get("newstock_cartons", 10)
        puff_par_gout = session.get("newstock_puff", 10)
        vendeur = session.get("vendeur_newstock", "?")

        # Export ancien stock
        export_old_stock(chat_id)

        # Reset
        reset_stock(chat_id, flavors, cartons, puff_par_gout)
        clear_session(chat_id)

        notify_everyone(
            f"📦 *Nouveau stock lancé par {vendeur} !*\n\n"
            f"🛒 {cartons} cartons | {puff_par_gout} puff/goût\n"
            f"🍬 {len(flavors)} goûts disponibles\n"
            f"📊 Stock total : {cartons * puff_par_gout} puff"
        )

        send_keyboard(chat_id,
            f"✅ *Nouveau stock lancé !*\n\n"
            f"📦 {cartons} cartons × {puff_par_gout} puff = *{cartons * puff_par_gout} puff*\n"
            f"🍬 {len(flavors)} goûts enregistrés",
            [[{"text": "🏠 Menu", "callback_data": "menu:home"}]]
        )
        return

    # Commandes
    cmds = {
        "/start": lambda: send_welcome(chat_id),
        "/aide": lambda: send_welcome(chat_id),
        "/vente": lambda: (clear_session(chat_id), ask_flavor(chat_id)),
        "/stats": lambda: send_stats(chat_id),
        "/gouts": lambda: send_gouts(chat_id),
        "/paye": lambda: show_cromes(chat_id),
        "/annuler": lambda: show_annuler(chat_id),
        "/newstock": lambda: ask_newstock_confirm(chat_id),
    }
    fn = cmds.get(text)
    if fn:
        fn()
    else:
        send_welcome(chat_id)

def handle_callback(chat_id, data, msg_id):
    save_chat_id(chat_id)

    if data == "cancel":
        clear_session(chat_id)
        edit_message(chat_id, msg_id, "❌ Annulé.")
        return

    # Menu shortcuts
    menu_map = {
        "menu:home": lambda: send_welcome(chat_id),
        "menu:vente": lambda: (clear_session(chat_id), ask_flavor(chat_id)),
        "menu:stats": lambda: send_stats(chat_id),
        "menu:gouts": lambda: send_gouts(chat_id),
        "menu:paye": lambda: show_cromes(chat_id),
        "menu:annuler": lambda: show_annuler(chat_id),
        "menu:newstock": lambda: ask_newstock_confirm(chat_id),
    }
    if data in menu_map:
        menu_map[data]()
        return

    # Payer crome
    if data.startswith("paye:"):
        payer_crome(chat_id, msg_id, int(data.split(":")[1]))
        return

    # Supprimer crome
    if data.startswith("del_crome:"):
        idx = int(data.split(":")[1])
        data_c = get_cromes()
        if idx <= len(data_c):
            row = data_c[idx-1]
            delete_crome_row(idx)
            edit_message(chat_id, msg_id,
                f"🗑️ Crome de *{row[0]}* supprimé.",
                [[{"text": "⏳ Cromes", "callback_data": "menu:paye"}, {"text": "🏠 Menu", "callback_data": "menu:home"}]]
            )
        return

    # Annuler vente
    if data.startswith("annuler:"):
        confirmer_annulation(chat_id, msg_id, int(data.split(":")[1]))
        return

    # Nouveau stock confirm
    if data == "newstock:confirm":
        session = {"step": "newstock_vendeur"}
        set_session(chat_id, session)
        buttons = [[{"text": v, "callback_data": f"newstock_vendeur:{v}"}] for v in VENDEURS]
        edit_message(chat_id, msg_id, "👤 *C'est qui qui lance le nouveau stock ?*", buttons)
        return

    if data.startswith("newstock_vendeur:"):
        vendeur = data.split(":")[1]
        session = get_session(chat_id)
        session["vendeur_newstock"] = vendeur
        session["step"] = "newstock_cartons"
        set_session(chat_id, session)
        edit_message(chat_id, msg_id, f"👤 *{vendeur}*\n\n📦 Combien de cartons ?")
        send_message(chat_id, "Tape le nombre de cartons :")
        return

    # Confirm transaction
    if data == "confirm:oui":
        session = get_session(chat_id)
        save_transaction(chat_id, session)
        return
    if data == "confirm:non":
        clear_session(chat_id)
        edit_message(chat_id, msg_id, "❌ Annulé.")
        return

    session = get_session(chat_id)

    # Flavor
    if data.startswith("flavor:"):
        flavor = data.replace("flavor:", "")
        restantes = get_stock_restant(flavor)
        if restantes <= 0:
            answer_callback(msg_id, f"❌ {flavor} est épuisé !")
            send_message(chat_id, f"❌ *{flavor}* est épuisé ! Choisis un autre goût.")
            return
        session["flavor"] = flavor
        session["step"] = "payment"
        set_session(chat_id, session)
        edit_message(chat_id, msg_id, f"🍬 Goût : *{flavor}*")
        ask_payment(chat_id)

    # Payment
    elif data.startswith("pay:"):
        payment = data.replace("pay:", "")
        if payment == "Offert":
            session.update({"payment": "-", "statut": "Offert", "categorie": "Reduction", "prix": 0, "step": "vendeur"})
        elif payment == "Arrangement":
            session.update({"payment": "-", "statut": "Arrangement", "categorie": "Arrangement", "prix": 0, "step": "vendeur"})
        elif payment == "Crome":
            session.update({"payment": "Crome", "statut": "En attente", "categorie": "Crome", "prix": PRIX_VENTE, "step": "prenom_client"})
        else:
            session.update({"payment": payment, "statut": "Paye", "categorie": "Vente", "prix": PRIX_VENTE, "step": "vendeur"})

        set_session(chat_id, session)
        edit_message(chat_id, msg_id, f"💰 Paiement : *{payment}*")

        if session["step"] == "prenom_client":
            send_message(chat_id, "👤 Tape le *prénom du client* (crome) :")
            session["step"] = "waiting_prenom_client"
            set_session(chat_id, session)
        else:
            ask_vendeur(chat_id)

    # Vendeur
    elif data.startswith("vendeur:"):
        vendeur = data.replace("vendeur:", "")
        session["vendeur"] = vendeur
        session["step"] = "confirm"
        set_session(chat_id, session)
        edit_message(chat_id, msg_id, f"👤 Vendeur : *{vendeur}*")
        show_confirm(chat_id, session)

# ================================================================
# VERCEL HANDLER
# ================================================================
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            update = json.loads(body)

            # Résumé journalier (appelé par cron Vercel)
            if self.path == "/api/cron":
                send_resume_journalier()
            elif "message" in update:
                msg = update["message"]
                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")
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
        # Cron job pour résumé journalier
        if self.path == "/api/cron":
            try:
                send_resume_journalier()
            except Exception as e:
                print(f"Cron error: {e}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Puff Tracker v3 actif!")
