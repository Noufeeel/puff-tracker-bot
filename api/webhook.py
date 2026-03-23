from http.server import BaseHTTPRequestHandler
import json
import os
import urllib.request
from datetime import datetime, timedelta

# ================================================================
# CONFIG
# ================================================================
TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_URL = f"https://api.telegram.org/bot{TOKEN}"

VENDEURS = ["Belk", "Nayel", "Nono"]
PRIX_VENTE = 10
ALERTE_FAIBLE = 3
ALERTE_STOCK_TOTAL = 20
PUFF_PAR_GOUT = 10
SESSION_TIMEOUT = 600  # 10 minutes

# ================================================================
# STOCKAGE EN MEMOIRE
# ================================================================
_sessions = {}
_chat_ids = []
_last_activity = {}

# Données du stock
_data = {
    "transactions": [],   # liste de dicts
    "cromes": [],         # liste de dicts
    "flavors": [
        "tropical fruit", "kiwi passion", "blue cherry explosion",
        "white peach razz", "cherry berry", "strawberry banana",
        "peach ice", "cherry peach limonade", "peach mangue pineapple",
        "Lady Killa"
    ],
    "stock_config": {
        "cartons": 10,
        "cout_achat": 530,
        "prix_vente": 10,
    },
    "transaction_counter": 0,
}

# ================================================================
# SESSIONS
# ================================================================
def get_session(chat_id):
    now = datetime.now().timestamp()
    s = _sessions.get(str(chat_id), {})
    last = _last_activity.get(str(chat_id), now)
    if now - last > SESSION_TIMEOUT and s:
        clear_session(chat_id)
        return {}
    return s

def set_session(chat_id, data):
    _sessions[str(chat_id)] = data
    _last_activity[str(chat_id)] = datetime.now().timestamp()

def clear_session(chat_id):
    _sessions.pop(str(chat_id), None)
    _last_activity.pop(str(chat_id), None)

# ================================================================
# CHAT IDS
# ================================================================
def save_chat_id(chat_id):
    if chat_id not in _chat_ids:
        _chat_ids.append(chat_id)

def notify_all(text, exclude=None):
    for cid in _chat_ids:
        if cid != exclude:
            send_message(cid, text)

def notify_everyone(text):
    for cid in _chat_ids:
        send_message(cid, text)

# ================================================================
# STOCK HELPERS
# ================================================================
def get_stock_par_gout():
    stock = {f: PUFF_PAR_GOUT for f in _data["flavors"]}
    for t in _data["transactions"]:
        f = t.get("flavor", "")
        if f in stock:
            stock[f] -= t.get("qte", 1)
    return stock

def get_stats():
    total_stock = len(_data["flavors"]) * PUFF_PAR_GOUT
    vendues = ca = crome_total = paylib = liquide = arrangements_total = 0
    ventes_par_vendeur = {v: 0 for v in VENDEURS}
    arrangements_count = 0

    for t in _data["transactions"]:
        qte = t.get("qte", 1)
        prix = t.get("prix", 0)
        cat = t.get("categorie", "")
        payment = t.get("payment", "")
        statut = t.get("statut", "")
        vendeur = t.get("vendeur", "")

        if cat == "Vente":
            vendues += qte
            if vendeur in ventes_par_vendeur:
                ventes_par_vendeur[vendeur] += qte
        if cat == "Arrangement":
            arrangements_count += 1
            arrangements_total += prix
        if statut == "Paye":
            ca += prix
        if statut == "En attente":
            crome_total += prix
        if payment == "Paylib" and statut == "Paye":
            paylib += prix
        if payment == "Liquide" and statut == "Paye":
            liquide += prix

    cout = _data["stock_config"]["cout_achat"]
    prix_v = _data["stock_config"]["prix_vente"]
    objectif = total_stock * prix_v
    restantes = total_stock - vendues
    benefice = ca - cout
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
        "arrangements_count": arrangements_count,
        "arrangements_total": arrangements_total,
        "ventes_par_vendeur": ventes_par_vendeur,
        "cout": cout,
        "nb_cromes": len(_data["cromes"]),
    }

def next_transaction_id():
    _data["transaction_counter"] += 1
    return _data["transaction_counter"]

# ================================================================
# TELEGRAM API
# ================================================================
def tg_post(method, data):
    url = f"{TELEGRAM_URL}/{method}"
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except Exception as e:
        print(f"TG error {method}: {e}")
        return {}

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

def answer_callback(cid, text=""):
    tg_post("answerCallbackQuery", {"callback_query_id": cid, "text": text})

def send_document_text(chat_id, filename, content, caption=""):
    boundary = "----PuffBotBoundary"
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
        f"{TELEGRAM_URL}/sendDocument", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"Send doc error: {e}")

# ================================================================
# BOUTONS NAVIGATION
# ================================================================
def btn_back(step):
    return {"text": "◀️ Retour", "callback_data": f"back:{step}"}

def btn_cancel():
    return {"text": "❌ Annuler", "callback_data": "cancel"}

def btn_menu():
    return {"text": "🏠 Menu", "callback_data": "menu:home"}

# ================================================================
# MENUS
# ================================================================
def send_welcome(chat_id):
    s = get_stats()
    today = datetime.now().strftime("%d/%m/%Y")
    ventes_today = sum(
        t.get("qte", 1) for t in _data["transactions"]
        if t.get("date", "") == today and t.get("categorie") == "Vente"
    )
    send_keyboard(chat_id,
        f"👋 *Puff Tracker*\n\n"
        f"📅 Ventes aujourd'hui : *{ventes_today}*\n"
        f"📦 Stock restant : *{s['restantes']}/{s['total_stock']}*\n"
        f"💶 CA total : *{s['ca']}€*\n\n"
        f"Que veux-tu faire ?",
        [
            [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
            [{"text": "📊 Stats", "callback_data": "menu:stats"}, {"text": "🍬 Goûts", "callback_data": "menu:gouts"}],
            [{"text": "⏳ Cromes", "callback_data": "menu:cromes"}, {"text": "🔄 Annuler vente", "callback_data": "menu:annuler"}],
            [{"text": "📦 Nouveau stock", "callback_data": "menu:newstock"}, {"text": "📋 Récap rapide", "callback_data": "menu:recap"}],
        ]
    )

def send_recap_rapide(chat_id):
    s = get_stats()
    top = max(s["ventes_par_vendeur"], key=s["ventes_par_vendeur"].get)
    send_keyboard(chat_id,
        f"📋 *RÉCAP RAPIDE*\n\n"
        f"📦 *{s['restantes']}/{s['total_stock']}* puff restantes\n"
        f"💶 CA : *{s['ca']}€* / {s['objectif']}€\n"
        f"{s['bar_str']} *{s['progress']}%*\n"
        f"💰 Bénéfice : *{s['benefice']}€*\n"
        f"⏳ Cromes : *{s['crome_total']}€* ({s['nb_cromes']})\n"
        f"🏆 Top : *{top}* ({s['ventes_par_vendeur'][top]} ventes)",
        [[{"text": "📊 Stats complètes", "callback_data": "menu:stats"}, btn_menu()]]
    )

def ask_stats_confirm(chat_id):
    send_keyboard(chat_id,
        "📊 *STATS COMPLÈTES*\n\n"
        "Un fichier avec toutes les données va t'être envoyé.\n\n"
        "Tu confirmes ?",
        [
            [{"text": "✅ Oui, envoyer le fichier", "callback_data": "stats:confirm"}],
            [{"text": "❌ Annuler", "callback_data": "cancel"}]
        ]
    )

def send_stats_file(chat_id):
    s = get_stats()
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    stock = get_stock_par_gout()

    lines = [
        f"=== PUFF TRACKER — EXPORT STATS {now} ===\n",
        f"Stock total : {s['total_stock']} puff",
        f"Puff vendues : {s['vendues']}",
        f"Puff restantes : {s['restantes']}",
        f"",
        f"=== FINANCES ===",
        f"CA encaissé : {s['ca']}€",
        f"Objectif : {s['objectif']}€ ({s['progress']}%)",
        f"Bénéfice actuel : {s['benefice']}€",
        f"Coût stock : {s['cout']}€",
        f"Paylib : {s['paylib']}€",
        f"Liquide : {s['liquide']}€",
        f"Cromes en attente : {s['crome_total']}€",
        f"Arrangements : {s['arrangements_count']} ({s['arrangements_total']}€)",
        f"",
        f"=== VENTES PAR VENDEUR ===",
    ]
    for v, nb in s["ventes_par_vendeur"].items():
        lines.append(f"{v} : {nb} ventes")

    lines.append("")
    lines.append("=== STOCK PAR GOÛT ===")
    for f, r in stock.items():
        lines.append(f"{f} : {r} restantes")

    lines.append("")
    lines.append("=== CROMES EN ATTENTE ===")
    if _data["cromes"]:
        for c in _data["cromes"]:
            lines.append(
                f"#{c['id']} | {c['vendeur']} → {c['client']} | "
                f"{c['qte']} puff {c['flavor']} | {c['prix']}€ | {c['date']}"
            )
    else:
        lines.append("Aucun crome en attente")

    lines.append("")
    lines.append("=== TOUTES LES TRANSACTIONS ===")
    for t in _data["transactions"]:
        lines.append(
            f"#{t['id']} | {t['date']} {t['heure']} | {t['vendeur']} | "
            f"{t.get('qte',1)}x {t['flavor']} | {t['prix']}€ | "
            f"{t['payment']} | {t['statut']} | {t['categorie']}"
            + (f" | client: {t.get('client','')}" if t.get('client') else "")
        )

    content = "\n".join(lines)
    fname = f"puff_stats_{datetime.now().strftime('%d%m%Y_%H%M')}.txt"
    send_document_text(chat_id, fname, content, caption=f"📊 Export stats — {now}")
    send_keyboard(chat_id, "✅ Fichier envoyé !", [[btn_menu()]])

def send_gouts(chat_id):
    stock = get_stock_par_gout()
    msg = "🍬 *GOÛTS DISPONIBLES*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for f, r in stock.items():
        icon = "❌" if r <= 0 else "⚠️" if r <= ALERTE_FAIBLE else "✅"
        msg += f"{icon} {f} : *{r}*\n"
    send_keyboard(chat_id, msg, [
        [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}, btn_menu()]
    ])

# ================================================================
# VENTE — ÉTAPES
# ================================================================
def ask_flavor(chat_id, msg_id=None):
    stock = get_stock_par_gout()
    rows = []
    items = list(stock.items())
    for i in range(0, len(items), 2):
        row = []
        for j in range(2):
            if i + j < len(items):
                f, r = items[i + j]
                label = f"❌ {f} (0)" if r <= 0 else f"{'⚠️' if r <= ALERTE_FAIBLE else '✅'} {f} ({r})"
                row.append({"text": label, "callback_data": f"flavor:{f}"})
        rows.append(row)
    rows.append([btn_cancel()])
    text = "🍬 *Quel goût ?*"
    if msg_id:
        edit_message(chat_id, msg_id, text, rows)
    else:
        send_keyboard(chat_id, text, rows)

def ask_payment(chat_id, msg_id=None):
    buttons = [
        [{"text": "💵 Liquide", "callback_data": "pay:Liquide"}, {"text": "💳 Paylib", "callback_data": "pay:Paylib"}],
        [{"text": "⏳ Crome", "callback_data": "pay:Crome"}, {"text": "🔧 Arrangement", "callback_data": "pay:Arrangement"}],
        [btn_back("flavor"), btn_cancel()]
    ]
    text = "💰 *Mode de paiement ?*"
    if msg_id:
        edit_message(chat_id, msg_id, text, buttons)
    else:
        send_keyboard(chat_id, text, buttons)

def ask_vendeur(chat_id, back_step="payment", msg_id=None):
    buttons = [[{"text": v, "callback_data": f"vendeur:{v}"}] for v in VENDEURS]
    buttons.append([btn_back(back_step), btn_cancel()])
    text = "👤 *C'est qui ?*"
    if msg_id:
        edit_message(chat_id, msg_id, text, buttons)
    else:
        send_keyboard(chat_id, text, buttons)

def show_confirm_vente(chat_id, session):
    s = session
    lines = [
        "📝 *Récap de la vente :*\n",
        f"🍬 Goût : *{s.get('flavor')}*",
        f"💰 Paiement : *{s.get('payment')}*",
        f"👤 Vendeur : *{s.get('vendeur')}*",
    ]
    if s.get("client"):
        lines.append(f"👥 Client : *{s.get('client')}*")
    if s.get("qte", 1) > 1:
        lines.append(f"🔢 Quantité : *{s.get('qte')}*")
    lines.append(f"💶 Prix : *{s.get('prix')}€*")
    if s.get("categorie") == "Arrangement":
        lines.append(f"🔧 Arrangement : *{s.get('qte')} puff à {s.get('prix')}€*")
    lines.append("\n✅ Confirmer ?")

    send_keyboard(chat_id, "\n".join(lines), [
        [{"text": "✅ Confirmer", "callback_data": "confirm:oui"}, {"text": "❌ Non", "callback_data": "confirm:non"}],
        [btn_back("vendeur"), btn_cancel()]
    ])

def save_vente(chat_id, session):
    now = datetime.now()
    tid = next_transaction_id()
    t = {
        "id": tid,
        "date": now.strftime("%d/%m/%Y"),
        "heure": now.strftime("%H:%M"),
        "flavor": session["flavor"],
        "qte": session.get("qte", 1),
        "prix": session["prix"],
        "payment": session["payment"],
        "statut": session["statut"],
        "categorie": session["categorie"],
        "vendeur": session.get("vendeur", "?"),
        "client": session.get("client", ""),
    }
    _data["transactions"].append(t)

    # Crome → ajoute dans cromes
    if session["categorie"] == "Crome":
        _data["cromes"].append({
            "id": tid,
            "date": now.strftime("%d/%m/%Y"),
            "vendeur": session.get("vendeur", "?"),
            "client": session.get("client", "?"),
            "flavor": session["flavor"],
            "qte": session.get("qte", 1),
            "prix": session["prix"],
            "payment": session["payment"],
        })

    restantes = get_stock_par_gout().get(session["flavor"], 0)
    clear_session(chat_id)

    # Notification
    cat = session["categorie"]
    if cat == "Vente":
        notif = f"🛒 *{session['vendeur']}* a vendu *{session['flavor']}* — {session['prix']}€ ({session['payment']})"
    elif cat == "Crome":
        notif = f"⏳ *{session['vendeur']}* a vendu {session.get('qte',1)} puff à *{session.get('client')}* — {session['flavor']} ({session['prix']}€)"
    elif cat == "Arrangement":
        notif = f"🔧 *{session['vendeur']}* a fait un arrangement — {session.get('qte',1)} puff à {session['prix']}€"
    else:
        notif = f"📝 Transaction par {session['vendeur']}"

    notify_all(notif, exclude=chat_id)

    # Alertes stock
    if restantes == 0:
        notify_everyone(f"❌ *{session['flavor']}* est épuisé !")
    elif restantes <= ALERTE_FAIBLE:
        notify_everyone(f"⚠️ *{session['flavor']}* — plus que *{restantes}* restants !")

    s = get_stats()
    if s["restantes"] <= ALERTE_STOCK_TOTAL:
        notify_everyone(f"📦 Attention ! Plus que *{s['restantes']}* puff au total !")

    send_keyboard(chat_id,
        f"✅ *Transaction #{tid} enregistrée !*\n\n"
        f"🍬 {session['flavor']}"
        f"{f' × {session.get(\"qte\",1)}' if session.get('qte',1) > 1 else ''}\n"
        f"👤 {session.get('vendeur')}"
        f"{f' → {session.get(\"client\")}' if session.get('client') else ''}\n"
        f"💶 {session['prix']}€ — {session['statut']}\n\n"
        f"📦 *{session['flavor']}* restantes : *{restantes}*",
        [
            [{"text": "➕ Nouvelle vente", "callback_data": "menu:vente"}],
            [{"text": "📋 Récap", "callback_data": "menu:recap"}, btn_menu()]
        ]
    )

# ================================================================
# CROMES
# ================================================================
def show_cromes(chat_id):
    if not _data["cromes"]:
        send_keyboard(chat_id, "✅ *Aucun crome en attente !*", [[btn_menu()]])
        return

    msg = "⏳ *CROMES EN ATTENTE*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    buttons = []
    for c in _data["cromes"]:
        msg += (
            f"*#{c['id']}* — *{c['vendeur']}* a vendu *{c['qte']} puff* à *{c['client']}*\n"
            f"🍬 {c['flavor']} | 💶 {c['prix']}€ | 📅 {c['date']}\n\n"
        )
        buttons.append([
            {"text": f"✅ #{c['id']} {c['client']} a payé", "callback_data": f"crome_paye:{c['id']}"},
            {"text": f"🗑️ Supprimer #{c['id']}", "callback_data": f"crome_del:{c['id']}"}
        ])
    buttons.append([btn_menu()])
    send_keyboard(chat_id, msg, buttons)

def encaisser_crome(chat_id, msg_id, crome_id):
    crome = next((c for c in _data["cromes"] if c["id"] == crome_id), None)
    if not crome:
        edit_message(chat_id, msg_id, "❌ Crome introuvable.")
        return
    # Confirmation
    send_keyboard(chat_id,
        f"💰 *Confirmation encaissement*\n\n"
        f"*{crome['client']}* paye {crome['qte']} puff *{crome['flavor']}*\n"
        f"Montant : *{crome['prix']}€*\n\n"
        f"Tu confirmes ?",
        [
            [{"text": "✅ Oui, encaisser", "callback_data": f"crome_confirm:{crome_id}"}],
            [{"text": "❌ Annuler", "callback_data": "menu:cromes"}]
        ]
    )

def confirmer_encaissement(chat_id, msg_id, crome_id):
    crome = next((c for c in _data["cromes"] if c["id"] == crome_id), None)
    if not crome:
        edit_message(chat_id, msg_id, "❌ Crome introuvable.")
        return

    # Met à jour la transaction
    for t in _data["transactions"]:
        if t["id"] == crome_id:
            t["statut"] = "Paye"
            break

    _data["cromes"] = [c for c in _data["cromes"] if c["id"] != crome_id]
    notify_all(
        f"💰 Crome encaissé ! *{crome['client']}* a payé *{crome['qte']} puff* à *{crome['vendeur']}* — {crome['prix']}€",
        exclude=chat_id
    )
    edit_message(chat_id, msg_id,
        f"✅ *{crome['client']}* a payé !\n\n"
        f"🍬 {crome['flavor']} × {crome['qte']} — {crome['prix']}€\n"
        f"Retiré des cromes.",
        [[{"text": "⏳ Voir cromes", "callback_data": "menu:cromes"}, btn_menu()]]
    )

def supprimer_crome(chat_id, msg_id, crome_id):
    crome = next((c for c in _data["cromes"] if c["id"] == crome_id), None)
    if not crome:
        edit_message(chat_id, msg_id, "❌ Crome introuvable.")
        return
    _data["cromes"] = [c for c in _data["cromes"] if c["id"] != crome_id]
    edit_message(chat_id, msg_id,
        f"🗑️ Crome *#{crome_id}* supprimé.",
        [[{"text": "⏳ Voir cromes", "callback_data": "menu:cromes"}, btn_menu()]]
    )

# ================================================================
# ANNULER VENTE
# ================================================================
def show_annuler(chat_id):
    if not _data["transactions"]:
        send_keyboard(chat_id, "❌ Aucune transaction à annuler.", [[btn_menu()]])
        return

    last20 = _data["transactions"][-20:][::-1]
    msg = "🔄 *ANNULER UNE VENTE*\nChoisis la transaction :\n\n"
    buttons = []
    for t in last20:
        label = f"#{t['id']} {t['date']} — {t['vendeur']} — {t.get('qte',1)}x {t['flavor']} — {t['prix']}€"
        msg += f"{label}\n"
        buttons.append([{"text": f"🗑️ #{t['id']} {t['flavor']} ({t['vendeur']})", "callback_data": f"annuler:{t['id']}"}])
    buttons.append([btn_cancel()])
    send_keyboard(chat_id, msg, buttons)

def confirmer_annulation(chat_id, msg_id, tid):
    t = next((x for x in _data["transactions"] if x["id"] == tid), None)
    if not t:
        edit_message(chat_id, msg_id, "❌ Transaction introuvable.")
        return
    _data["transactions"] = [x for x in _data["transactions"] if x["id"] != tid]
    # Retire aussi le crome si c'en était un
    _data["cromes"] = [c for c in _data["cromes"] if c["id"] != tid]
    notify_all(f"🔄 *{t['vendeur']}* a annulé la transaction *#{tid}* — {t['flavor']}", exclude=chat_id)
    edit_message(chat_id, msg_id,
        f"✅ Transaction *#{tid}* annulée !\n🍬 {t['flavor']} remis en stock.",
        [[btn_menu()]]
    )

# ================================================================
# NOUVEAU STOCK
# ================================================================
def ask_newstock_confirm(chat_id):
    send_keyboard(chat_id,
        "⚠️ *NOUVEAU STOCK*\n\n"
        "Tu vas réinitialiser le stock actuel.\n"
        "Un export sera envoyé à tous avant la réinitialisation.\n\n"
        "Tu es sûr ?",
        [
            [{"text": "✅ Oui, nouveau stock", "callback_data": "newstock:confirm"}],
            [btn_cancel()]
        ]
    )

def export_and_reset(chat_id, session):
    # Export vers tous
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    s = get_stats()
    stock = get_stock_par_gout()
    vendeur = session.get("vendeur_newstock", "?")
    cartons = session.get("newstock_cartons", 0)
    cout = session.get("newstock_cout", 0)
    new_flavors = session.get("newstock_flavors", [])

    lines = [
        f"=== EXPORT ANCIEN STOCK — {now} ===",
        f"Lancé par : {vendeur}",
        f"",
        f"Stock total : {s['total_stock']} puff",
        f"Vendues : {s['vendues']}",
        f"Restantes : {s['restantes']}",
        f"CA encaissé : {s['ca']}€",
        f"Bénéfice : {s['benefice']}€",
        f"Paylib : {s['paylib']}€",
        f"Liquide : {s['liquide']}€",
        f"Cromes non encaissés : {s['crome_total']}€",
        f"",
        f"=== VENTES PAR VENDEUR ===",
    ]
    for v, nb in s["ventes_par_vendeur"].items():
        lines.append(f"{v} : {nb} ventes")

    lines.append("")
    lines.append("=== STOCK PAR GOÛT ===")
    for f, r in stock.items():
        lines.append(f"{f} : {r} restantes")

    lines.append("")
    lines.append("=== TRANSACTIONS ===")
    for t in _data["transactions"]:
        lines.append(
            f"#{t['id']} | {t['date']} {t['heure']} | {t['vendeur']} | "
            f"{t.get('qte',1)}x {t['flavor']} | {t['prix']}€ | {t['statut']}"
        )

    content = "\n".join(lines)
    fname = f"ancien_stock_{datetime.now().strftime('%d%m%Y_%H%M')}.txt"

    for cid in _chat_ids:
        send_document_text(cid, fname, content, caption=f"📤 Export ancien stock avant réinitialisation — {now}")

    # Reset
    _data["transactions"].clear()
    _data["cromes"].clear()
    _data["transaction_counter"] = 0
    _data["flavors"] = new_flavors
    _data["stock_config"]["cartons"] = cartons
    _data["stock_config"]["cout_achat"] = cout
    total = len(new_flavors) * PUFF_PAR_GOUT

    clear_session(chat_id)

    notify_everyone(
        f"📦 *Nouveau stock lancé par {vendeur} !*\n\n"
        f"🛒 {cartons} cartons | coût : {cout}€\n"
        f"🍬 {len(new_flavors)} goûts | {total} puff\n"
        f"🎯 Objectif : {total * PRIX_VENTE}€"
    )

    send_keyboard(chat_id,
        f"✅ *Nouveau stock lancé !*\n\n"
        f"👤 Par : *{vendeur}*\n"
        f"📦 {cartons} cartons\n"
        f"💶 Coût : *{cout}€*\n"
        f"🍬 {len(new_flavors)} goûts × {PUFF_PAR_GOUT} puff\n"
        f"📊 Stock total : *{total} puff*\n"
        f"🎯 Objectif CA : *{total * PRIX_VENTE}€*",
        [[btn_menu()]]
    )

# ================================================================
# RESUME JOURNALIER
# ================================================================
def send_resume_journalier():
    s = get_stats()
    today = datetime.now().strftime("%d/%m/%Y")
    ventes_today = [
        t for t in _data["transactions"]
        if t.get("date") == today and t.get("categorie") == "Vente"
    ]
    ca_today = sum(t["prix"] for t in ventes_today if t.get("statut") == "Paye")
    nb_today = sum(t.get("qte", 1) for t in ventes_today)

    vpv_today = {v: 0 for v in VENDEURS}
    for t in ventes_today:
        if t.get("vendeur") in vpv_today:
            vpv_today[t["vendeur"]] += t.get("qte", 1)

    top = max(vpv_today, key=vpv_today.get)
    top_nb = vpv_today[top]

    msg = (
        f"🌙 *RÉSUMÉ DU JOUR — {today}*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ Ventes aujourd'hui : *{nb_today}*\n"
        f"💶 CA aujourd'hui : *{ca_today}€*\n\n"
        f"📊 CA total : *{s['ca']}€* / {s['objectif']}€\n"
        f"{s['bar_str']} *{s['progress']}%*\n"
        f"💰 Bénéfice : *{s['benefice']}€*\n\n"
        f"⏳ Cromes en attente : *{s['nb_cromes']}* ({s['crome_total']}€)\n"
        f"📦 Stock restant : *{s['restantes']}*\n"
    )

    if top_nb > 0:
        msg += f"\n🏆 Top vendeur du jour : *{top}* ({top_nb} ventes)\n"

    stock = get_stock_par_gout()
    faibles = [(f, r) for f, r in stock.items() if 0 < r <= ALERTE_FAIBLE]
    if faibles:
        msg += "\n⚠️ *Goûts à surveiller :*\n"
        for f, r in faibles:
            msg += f"  • {f} : {r} restants\n"

    notify_everyone(msg)

    # Alerte cromes anciens (3j+)
    limit = (datetime.now() - timedelta(days=3)).strftime("%d/%m/%Y")
    for c in _data["cromes"]:
        try:
            cdate = datetime.strptime(c["date"], "%d/%m/%Y")
            if cdate < datetime.now() - timedelta(days=3):
                notify_everyone(
                    f"⏰ *Rappel crome* : *{c['client']}* doit encore *{c['prix']}€* "
                    f"à {c['vendeur']} ({c['flavor']}) depuis le {c['date']}"
                )
        except:
            pass

# ================================================================
# HANDLE MESSAGE
# ================================================================
def handle_message(chat_id, text):
    try:
        save_chat_id(chat_id)
        session = get_session(chat_id)
        step = session.get("step", "")

        # Saisies texte
        if step == "waiting_client":
            session["client"] = text
            session["step"] = "waiting_qte"
            set_session(chat_id, session)
            send_keyboard(chat_id,
                f"👥 Client : *{text}*\n\n🔢 Combien de puff ?",
                [[btn_back("payment"), btn_cancel()]]
            )
            return

        if step == "waiting_qte_crome":
            try:
                qte = int(text)
                session["qte"] = qte
                session["prix"] = qte * PRIX_VENTE
                session["step"] = "vendeur"
                set_session(chat_id, session)
                ask_vendeur(chat_id, back_step="qte_crome")
            except:
                send_message(chat_id, "❌ Tape un nombre valide.")
            return

        if step == "waiting_qte_arrangement":
            try:
                qte = int(text)
                session["qte"] = qte
                session["step"] = "waiting_prix_arrangement"
                set_session(chat_id, session)
                send_keyboard(chat_id,
                    f"🔢 *{qte} puff*\n\n💶 Quel est le prix de l'arrangement ?",
                    [[btn_back("payment"), btn_cancel()]]
                )
            except:
                send_message(chat_id, "❌ Tape un nombre valide.")
            return

        if step == "waiting_prix_arrangement":
            try:
                prix = float(text)
                session["prix"] = prix
                session["statut"] = "Paye"
                session["step"] = "vendeur"
                set_session(chat_id, session)
                ask_vendeur(chat_id, back_step="prix_arrangement")
            except:
                send_message(chat_id, "❌ Tape un prix valide.")
            return

        if step == "newstock_cartons":
            try:
                session["newstock_cartons"] = int(text)
                session["step"] = "newstock_cout"
                set_session(chat_id, session)
                send_keyboard(chat_id,
                    f"📦 *{text} cartons*\n\n💶 Combien t'a coûté ce stock au total (€) ?",
                    [[btn_back("newstock_cartons"), btn_cancel()]]
                )
            except:
                send_message(chat_id, "❌ Tape un nombre valide.")
            return

        if step == "newstock_cout":
            try:
                session["newstock_cout"] = float(text)
                session["step"] = "newstock_flavors"
                set_session(chat_id, session)
                send_keyboard(chat_id,
                    f"💶 *Coût : {text}€*\n\n"
                    f"🍬 Liste tes goûts séparés par des virgules :\n"
                    f"_Ex: tropical fruit, kiwi passion, peach ice_",
                    [[btn_back("newstock_cout"), btn_cancel()]]
                )
            except:
                send_message(chat_id, "❌ Tape un montant valide.")
            return

        if step == "newstock_flavors":
            flavors = [f.strip() for f in text.split(",") if f.strip()]
            if not flavors:
                send_message(chat_id, "❌ Liste invalide. Sépare les goûts par des virgules.")
                return
            session["newstock_flavors"] = flavors
            session["step"] = "newstock_confirm"
            set_session(chat_id, session)
            cartons = session.get("newstock_cartons", 0)
            cout = session.get("newstock_cout", 0)
            total = len(flavors) * PUFF_PAR_GOUT
            send_keyboard(chat_id,
                f"📋 *Récap du nouveau stock :*\n\n"
                f"👤 Par : *{session.get('vendeur_newstock')}*\n"
                f"📦 Cartons : *{cartons}*\n"
                f"💶 Coût : *{cout}€*\n"
                f"🍬 Goûts : *{len(flavors)}* × {PUFF_PAR_GOUT} puff\n"
                f"📊 Total : *{total} puff*\n"
                f"🎯 Objectif : *{total * PRIX_VENTE}€*\n\n"
                f"✅ Confirmer le nouveau stock ?",
                [
                    [{"text": "✅ Oui, lancer !", "callback_data": "newstock:launch"}],
                    [btn_back("newstock_flavors"), btn_cancel()]
                ]
            )
            return

        # Commandes
        cmds = {
            "/start":    lambda: send_welcome(chat_id),
            "/aide":     lambda: send_welcome(chat_id),
            "/vente":    lambda: (clear_session(chat_id), ask_flavor(chat_id)),
            "/stats":    lambda: ask_stats_confirm(chat_id),
            "/gouts":    lambda: send_gouts(chat_id),
            "/cromes":   lambda: show_cromes(chat_id),
            "/annuler":  lambda: show_annuler(chat_id),
            "/newstock": lambda: ask_newstock_confirm(chat_id),
            "/recap":    lambda: send_recap_rapide(chat_id),
        }
        fn = cmds.get(text)
        if fn:
            fn()
        else:
            send_welcome(chat_id)
    except Exception as e:
        print(f"handle_message error: {e}")
        send_message(chat_id, f"❌ Erreur inattendue : {e}")

# ================================================================
# HANDLE CALLBACK
# ================================================================
def handle_callback(chat_id, data, msg_id):
    try:
        save_chat_id(chat_id)
        session = get_session(chat_id)

        # Annuler global
        if data == "cancel":
            clear_session(chat_id)
            edit_message(chat_id, msg_id, "❌ Annulé.", [[btn_menu()]])
            return

        # Retour arrière
        if data.startswith("back:"):
            step = data.split(":", 1)[1]
            if step == "flavor":
                ask_flavor(chat_id, msg_id)
            elif step == "payment":
                edit_message(chat_id, msg_id, f"🍬 Goût : *{session.get('flavor')}*")
                ask_payment(chat_id)
            elif step == "vendeur":
                ask_vendeur(chat_id, msg_id=msg_id)
            elif step in ("qte_crome", "prix_arrangement", "newstock_cartons",
                          "newstock_cout", "newstock_flavors"):
                send_message(chat_id, "◀️ Retour à l'étape précédente.")
            return

        # Menu shortcuts
        menu_map = {
            "menu:home":    lambda: send_welcome(chat_id),
            "menu:vente":   lambda: (clear_session(chat_id), ask_flavor(chat_id)),
            "menu:stats":   lambda: ask_stats_confirm(chat_id),
            "menu:gouts":   lambda: send_gouts(chat_id),
            "menu:cromes":  lambda: show_cromes(chat_id),
            "menu:annuler": lambda: show_annuler(chat_id),
            "menu:newstock":lambda: ask_newstock_confirm(chat_id),
            "menu:recap":   lambda: send_recap_rapide(chat_id),
        }
        if data in menu_map:
            menu_map[data]()
            return

        # Stats
        if data == "stats:confirm":
            edit_message(chat_id, msg_id, "📊 Génération du fichier...")
            send_stats_file(chat_id)
            return

        # Cromes
        if data.startswith("crome_paye:"):
            encaisser_crome(chat_id, msg_id, int(data.split(":")[1]))
            return
        if data.startswith("crome_confirm:"):
            confirmer_encaissement(chat_id, msg_id, int(data.split(":")[1]))
            return
        if data.startswith("crome_del:"):
            supprimer_crome(chat_id, msg_id, int(data.split(":")[1]))
            return

        # Annulation
        if data.startswith("annuler:"):
            confirmer_annulation(chat_id, msg_id, int(data.split(":")[1]))
            return

        # Nouveau stock
        if data == "newstock:confirm":
            session = {"step": "newstock_vendeur"}
            set_session(chat_id, session)
            buttons = [[{"text": v, "callback_data": f"newstock_vendeur:{v}"}] for v in VENDEURS]
            buttons.append([btn_cancel()])
            edit_message(chat_id, msg_id, "👤 *C'est qui qui lance le nouveau stock ?*", buttons)
            return

        if data.startswith("newstock_vendeur:"):
            vendeur = data.split(":")[1]
            session["vendeur_newstock"] = vendeur
            session["step"] = "newstock_cartons"
            set_session(chat_id, session)
            edit_message(chat_id, msg_id,
                f"👤 *{vendeur}*\n\n📦 Combien de cartons as-tu pris ?"
            )
            send_message(chat_id, "Tape le nombre de cartons :")
            return

        if data == "newstock:launch":
            export_and_reset(chat_id, session)
            return

        # Confirmation vente
        if data == "confirm:oui":
            save_vente(chat_id, session)
            return
        if data == "confirm:non":
            clear_session(chat_id)
            edit_message(chat_id, msg_id, "❌ Annulé.", [[btn_menu()]])
            return

        # Flavor
        if data.startswith("flavor:"):
            flavor = data.replace("flavor:", "")
            stock = get_stock_par_gout()
            if stock.get(flavor, 0) <= 0:
                answer_callback(msg_id, f"❌ {flavor} est épuisé !")
                send_message(chat_id, f"❌ *{flavor}* est épuisé ! Choisis un autre goût.")
                return
            session["flavor"] = flavor
            session["step"] = "payment"
            set_session(chat_id, session)
            edit_message(chat_id, msg_id, f"🍬 Goût : *{flavor}*")
            ask_payment(chat_id)
            return

        # Payment
        if data.startswith("pay:"):
            payment = data.replace("pay:", "")
            session["payment"] = payment

            if payment == "Crome":
                session["categorie"] = "Crome"
                session["statut"] = "En attente"
                session["step"] = "waiting_client"
                set_session(chat_id, session)
                edit_message(chat_id, msg_id, "💰 Paiement : *Crome*")
                send_keyboard(chat_id,
                    "👥 *Prénom du client ?*\n(Tape le prénom)",
                    [[btn_back("payment"), btn_cancel()]]
                )
            elif payment == "Arrangement":
                session["categorie"] = "Arrangement"
                session["statut"] = "Arrangement"
                session["step"] = "waiting_qte_arrangement"
                set_session(chat_id, session)
                edit_message(chat_id, msg_id, "💰 Paiement : *Arrangement*")
                send_keyboard(chat_id,
                    "🔧 *Arrangement*\n\n🔢 Combien de puff ?",
                    [[btn_back("payment"), btn_cancel()]]
                )
            else:
                session["categorie"] = "Vente"
                session["statut"] = "Paye"
                session["qte"] = 1
                session["prix"] = PRIX_VENTE
                session["step"] = "vendeur"
                set_session(chat_id, session)
                edit_message(chat_id, msg_id, f"💰 Paiement : *{payment}*")
                ask_vendeur(chat_id, back_step="payment")
            return

        # Vendeur
        if data.startswith("vendeur:"):
            vendeur = data.replace("vendeur:", "")
            session["vendeur"] = vendeur
            session["step"] = "confirm"
            set_session(chat_id, session)
            edit_message(chat_id, msg_id, f"👤 Vendeur : *{vendeur}*")
            show_confirm_vente(chat_id, session)
            return

    except Exception as e:
        print(f"handle_callback error: {e}")
        send_message(chat_id, f"❌ Erreur : {e}")

# ================================================================
# VERCEL HANDLER
# ================================================================
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            if self.path == "/api/cron":
                send_resume_journalier()
            else:
                update = json.loads(body)
                if "message" in update:
                    msg = update["message"]
                    handle_message(msg["chat"]["id"], msg.get("text", ""))
                elif "callback_query" in update:
                    cq = update["callback_query"]
                    answer_callback(cq["id"])
                    handle_callback(
                        cq["message"]["chat"]["id"],
                        cq["data"],
                        cq["message"]["message_id"]
                    )
        except Exception as e:
            print(f"Handler error: {e}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        if self.path == "/api/cron":
            try:
                send_resume_journalier()
            except Exception as e:
                print(f"Cron error: {e}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Puff Tracker v4 actif!")
