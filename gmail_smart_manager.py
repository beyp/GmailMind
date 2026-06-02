#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════╗
║        Gmail Smart Manager — Premier Tech Edition        ║
║              Développé pour Pascal Bey  v2.1             ║
╚══════════════════════════════════════════════════════════╝
Nouveautés v2.0 :
  - 💳 Module Paiements (PayPal, Klarna, Cofidis, Oney...)
  - 📈 Module Trading  (Kraken, TradingView, Binance...)
  - 🧹 Meilleur filtrage des faux positifs (promos/newsletters)
  - 🏷️  Catégorisation automatique avant scoring d'urgence
"""

# ─────────────────────────────────────────────────────────
# 📦 IMPORTS
# ─────────────────────────────────────────────────────────
import os, re, json, base64, pickle, datetime, webbrowser
from email.utils        import parseaddr
from collections        import defaultdict
from pathlib            import Path

from google.oauth2.credentials      import Credentials
from google_auth_oauthlib.flow      import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery      import build

from rich.console  import Console
from rich.table    import Table
from rich.panel    import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt   import Prompt, Confirm
from rich          import box
from rich.rule     import Rule

console = Console()

# ─────────────────────────────────────────────────────────
# ⚙️  CONFIGURATION
# ─────────────────────────────────────────────────────────
SCOPES           = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://mail.google.com/",
]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE       = "token.pickle"
MAX_MESSAGES     = 500

# ── Catégories ────────────────────────────────────────────
# Expéditeurs / domaines → catégorie forcée
SENDER_CATEGORIES = {
    # 💳 PAIEMENTS
    "paypal"          : "PAYMENT",
    "klarna"          : "PAYMENT",
    "cofidis"         : "PAYMENT",
    "oney"            : "PAYMENT",
    "alma"            : "PAYMENT",
    "floa"            : "PAYMENT",
    "cetelem"         : "PAYMENT",
    "sofinco"         : "PAYMENT",
    "stripe"          : "PAYMENT",
    "lydia"           : "PAYMENT",
    "sumeria"         : "PAYMENT",
    "revolut"         : "PAYMENT",
    "n26"             : "PAYMENT",
    "fortuneo"        : "PAYMENT",
    "boursorama"      : "PAYMENT",
    "laposte"         : "PAYMENT",       # compte La Poste / Banque Postale

    # 📈 TRADING
    "kraken"          : "TRADING",
    "tradingview"     : "TRADING",
    "binance"         : "TRADING",
    "coinbase"        : "TRADING",
    "bitget"          : "TRADING",
    "bybit"           : "TRADING",
    "kucoin"          : "TRADING",
    "interactive brokers": "TRADING",
    "degiro"          : "TRADING",
    "etoro"           : "TRADING",
    "trade republic"  : "TRADING",
    "saxo"            : "TRADING",
    "ig.com"          : "TRADING",
    "bourse direct"   : "TRADING",
    "fortuneo"        : "TRADING",

    # 📦 LIVRAISONS  (déjà géré mais on force la catégorie)
    "colis prive"     : "DELIVERY",
    "colisprive"      : "DELIVERY",
    "ups"             : "DELIVERY",
    "fedex"           : "DELIVERY",
    "dhl"             : "DELIVERY",
    "purolator"       : "DELIVERY",
    "amazon logistics": "DELIVERY",
    "intelcom"        : "DELIVERY",
    "laposte"         : "DELIVERY",      # suivi colis
    "chronopost"      : "DELIVERY",
    "mondial relay"   : "DELIVERY",
    "gls"             : "DELIVERY",

    # 🗑️  PROMO / NEWSLETTER → exclus des urgents
    "leroy merlin"    : "PROMO",
    "ebuyclub"        : "PROMO",
    "taaft"           : "PROMO",
    "hello watt"      : "PROMO",
    "sosh"            : "PROMO",
    "sfr"             : "PROMO",
    "bouygues"        : "PROMO",
    "orange"          : "PROMO",
    "free"            : "PROMO",
    "fnac"            : "PROMO",
    "cdiscount"       : "PROMO",
    "amazon"          : "PROMO",         # emails promos (pas livraisons)
    "aliexpress"      : "PROMO",
    "groupon"         : "PROMO",
    "vente-privee"    : "PROMO",
    "veepee"          : "PROMO",
    "boulanger"       : "PROMO",
    "darty"           : "PROMO",
    "decathlon"       : "PROMO",
}

# Mots-clés trading critiques (margin call, liquidation…)
TRADING_CRITICAL_KEYWORDS = [
    "margin call", "appel de marge", "liquidation", "margin level",
    "stop out", "force close", "forced liquidation", "position fermée",
    "compte en négatif", "funding rate", "liquidated", "stop loss atteint",
    "take profit", "order filled", "order executed", "trade executed",
    "deposit required", "dépôt requis",
]

# Mots-clés paiement
PAYMENT_KEYWORDS = [
    "échéance", "echeance", "paiement", "payment", "prélèvement", "debit",
    "facture", "invoice", "montant dû", "amount due", "overdue", "en retard",
    "rappel de paiement", "payment reminder", "4x", "3x", "mensualité",
    "instalment", "installment", "crédit", "credit", "remboursement",
    "refund", "solde", "balance", "account statement", "relevé",
]

# Mots-clés urgence RÉELLE (on exclut les mots marketing)
URGENT_KEYWORDS = [
    "urgent", "urgence", "critique", "critical",
    "action requise", "action required", "réponse requise", "response needed",
    "délai", "deadline", "échéance", "overdue", "en retard",
    "bloqué", "blocked", "en attente de", "pending",
    "dès que possible", "asap", "immédiatement",          # sans "immédiat" seul = trop générique
    "please respond", "awaiting your", "time sensitive",
    "votre compte", "your account", "vérification requise",
    "confirmation requise", "verify", "vérifiez",
]

# Indicateurs newsletters/promos → si présents, score urgence réduit
PROMO_INDICATORS = [
    "unsubscribe", "désabonner", "se désabonner",
    "newsletter", "no-reply", "noreply", "do-not-reply",
    "offre exclusive", "bon plan", "bons plans", "promo", "solde",
    "réduction", "discount", "-50%", "-30%", "cashback",
    "découvrir", "voir les offres", "shop now", "achetez",
]

# Patterns tracking colis
TRACKING_PATTERNS = {
    "UPS"         : r"1Z[0-9A-Z]{16}",
    "FedEx"       : r"\d{12}|\d{15}|\d{20}",
    "Canada Post" : r"[A-Z]{2}\d{9}[A-Z]{2}",
    "USPS"        : r"(?:94|93|92|94|95)\d{20}",
    "Amazon"      : r"TBA\d{12}",
}

DELIVERY_KEYWORDS = [
    "livraison", "colis", "expédié", "en transit", "numéro de suivi",
    "shipped", "delivery", "tracking", "package", "out for delivery",
    "delivered", "livré", "en cours de livraison",
]


# ─────────────────────────────────────────────────────────
# 🔐 AUTH
# ─────────────────────────────────────────────────────────
def authenticate_gmail():
    creds = None
    if Path(TOKEN_FILE).exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(CREDENTIALS_FILE).exists():
                console.print(Panel(
                    "[bold red]credentials.json introuvable ![/bold red]\n\n"
                    "1. console.cloud.google.com\n"
                    "2. APIs & Services → Gmail API → Activer\n"
                    "3. Identifiants → OAuth 2.0 (Desktop) → Télécharger\n"
                    "4. Renommer en credentials.json → même dossier que ce script\n"
                    "5. Ajouter votre email dans Utilisateurs Test",
                    title="🔑 Setup requis", border_style="red"))
                raise FileNotFoundError("credentials.json manquant")
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("gmail", "v1", credentials=creds)


# ─────────────────────────────────────────────────────────
# 📬 GMAIL HELPERS
# ─────────────────────────────────────────────────────────
def get_messages(service, max_results=MAX_MESSAGES, label_ids=None, query=""):
    messages, params = [], {"userId": "me", "maxResults": min(max_results, 500)}
    if label_ids: params["labelIds"] = label_ids
    if query:     params["q"] = query
    try:
        r = service.users().messages().list(**params).execute()
        messages.extend(r.get("messages", []))
        while "nextPageToken" in r and len(messages) < max_results:
            r = service.users().messages().list(**params, pageToken=r["nextPageToken"]).execute()
            messages.extend(r.get("messages", []))
    except Exception as e:
        console.print(f"[red]Erreur : {e}[/red]")
    return messages[:max_results]


def get_message_detail(service, msg_id):
    try:
        return service.users().messages().get(userId="me", id=msg_id, format="full").execute()
    except Exception:
        return {}


def decode_body(payload):
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            mt = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")
            if data and mt in ("text/plain", "text/html"):
                raw = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
                body += re.sub(r"<[^>]+>", " ", raw) if mt == "text/html" else raw
            if "parts" in part:
                body += decode_body(part)
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            body += base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
    return body


def parse_message(msg):
    headers    = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    sender     = headers.get("from", "Inconnu")
    name, addr = parseaddr(sender)
    try:
        date = datetime.datetime.fromtimestamp(int(msg.get("internalDate", 0)) / 1000)
    except Exception:
        date = datetime.datetime.now()
    labels = msg.get("labelIds", [])
    return {
        "id"          : msg.get("id", ""),
        "thread_id"   : msg.get("threadId", ""),
        "sender_name" : name or addr,
        "sender_email": addr.lower(),
        "subject"     : headers.get("subject", "(sans objet)"),
        "date"        : date,
        "snippet"     : msg.get("snippet", ""),
        "labels"      : labels,
        "is_unread"   : "UNREAD" in labels,
        "is_inbox"    : "INBOX" in labels,
    }


# ─────────────────────────────────────────────────────────
# 🏷️  CATÉGORISATION
# ─────────────────────────────────────────────────────────
def categorize_message(msg) -> str:
    """
    Retourne la catégorie principale d'un message :
    TRADING | PAYMENT | DELIVERY | URGENT | PROMO | OTHER
    """
    combined = (
        msg["sender_name"] + " " +
        msg["sender_email"] + " " +
        msg["subject"] + " " +
        msg["snippet"]
    ).lower()

    # Priorité : d'abord vérifier via le mapping d'expéditeurs connus
    for key, cat in SENDER_CATEGORIES.items():
        if key in combined:
            return cat

    # Ensuite par mots-clés dans le contenu
    if any(kw in combined for kw in TRADING_CRITICAL_KEYWORDS):
        return "TRADING"
    if any(kw in combined for kw in PAYMENT_KEYWORDS):
        return "PAYMENT"
    if any(kw in combined for kw in DELIVERY_KEYWORDS):
        return "DELIVERY"

    return "OTHER"


# ─────────────────────────────────────────────────────────
# 🔴 MODULE 1 : EMAILS URGENTS (faux positifs filtrés)
# ─────────────────────────────────────────────────────────
def analyze_urgency(msg, body=""):
    score, reasons = 0, []
    text = (msg["subject"] + " " + msg["snippet"] + " " + body).lower()
    category = msg.get("category", "OTHER")

    # 🚫 PROMO → score plafonné à 20 max (juste pour info)
    if category == "PROMO":
        return {"score": 10, "reasons": ["📢 Promotionnel/Newsletter"]}

    # 🚫 Indicateurs promo dans le contenu → malus
    promo_hits = sum(1 for p in PROMO_INDICATORS if p in text)
    if promo_hits >= 2:
        return {"score": 15, "reasons": ["📢 Contenu promotionnel détecté"]}

    # Mots-clés urgence RÉELLE
    found = [kw for kw in URGENT_KEYWORDS if kw in text]
    if found:
        score   += min(len(found) * 12, 40)
        reasons.append(f"Mots-clés : {', '.join(set(found[:3]))}")

    # Non lu
    if msg["is_unread"]:
        score   += 10
        reasons.append("Non lu")

    # Ancienneté
    age = (datetime.datetime.now() - msg["date"]).days
    if age > 7:
        score   += 20
        reasons.append(f"En attente depuis {age}j")
    elif age > 3:
        score   += 10
        reasons.append(f"En attente depuis {age}j")

    # Label IMPORTANT Gmail
    if "IMPORTANT" in msg["labels"]:
        score   += 15
        reasons.append("Gmail : IMPORTANT")

    # Questions directes
    q = text.count("?")
    if q >= 2:
        score += 15; reasons.append(f"{q} questions")
    elif q == 1:
        score += 8;  reasons.append("Question directe")

    return {"score": min(score, 100), "reasons": reasons}


def get_urgent_emails(service, parsed):
    urgent = []
    with Progress(SpinnerColumn(), TextColumn("🔍 Analyse urgences..."), console=console) as p:
        task = p.add_task("", total=len(parsed))
        for msg in parsed:
            if msg.get("category") in ("PAYMENT", "TRADING", "DELIVERY", "PROMO"):
                p.advance(task); continue          # traités dans leurs modules
            body = ""
            if msg["is_unread"] and (datetime.datetime.now() - msg["date"]).days <= 14:
                d = get_message_detail(service, msg["id"])
                if d: body = decode_body(d.get("payload", {}))
            u = analyze_urgency(msg, body)
            if u["score"] >= 35:
                urgent.append({**msg, **u})
            p.advance(task)
    return sorted(urgent, key=lambda x: x["score"], reverse=True)


def display_urgent(emails):
    if not emails:
        console.print(Panel("[green]✅ Aucun email urgent détecté ![/green]", border_style="green"))
        return
    t = Table(title=f"🔴 Emails Urgents ({len(emails)})", box=box.ROUNDED, show_lines=True)
    t.add_column("Score",      width=9,  style="bold red")
    t.add_column("Date",       width=12, style="cyan")
    t.add_column("Expéditeur", width=26, style="magenta", no_wrap=True)
    t.add_column("Sujet",      width=42, style="white")
    t.add_column("Raisons",    width=35, style="yellow")
    for m in emails[:20]:
        c   = "red" if m["score"] >= 70 else "yellow" if m["score"] >= 50 else "white"
        bar = "█" * (m["score"] // 20) + "░" * (5 - m["score"] // 20)
        t.add_row(
            f"[{c}]{m['score']:3d}/100\n{bar}[/{c}]",
            m["date"].strftime("%Y-%m-%d\n%H:%M"),
            (m["sender_name"] or m["sender_email"])[:25],
            m["subject"][:41],
            "\n".join(m["reasons"][:2]),
        )
    console.print(t)


# ─────────────────────────────────────────────────────────
# 💳 MODULE 2 : PAIEMENTS
# ─────────────────────────────────────────────────────────
PAYMENT_STATUS_RULES = [
    # (mots-clés dans texte,          statut affiché,              couleur, priorité)
    (["en retard", "overdue", "impayé", "unpaid"],                "🔴 EN RETARD",      "red",    1),
    (["appel de marge", "margin call"],                           "🔴 MARGIN CALL",    "red",    1),
    (["échéance", "echeance", "due date", "prélèvement prévu"],   "🟠 ÉCHÉANCE PROCHE","yellow", 2),
    (["confirmation", "confirmé", "autorisé", "authorized"],      "✅ CONFIRMÉ",       "green",  4),
    (["remboursement", "refund", "reçu", "received"],             "💚 REMBOURSÉ",      "green",  5),
    (["rappel", "reminder"],                                      "🟡 RAPPEL",         "yellow", 3),
    (["paiement", "payment", "facture", "invoice"],               "📄 INFO PAIEMENT",  "blue",   6),
]

def get_payment_status(text):
    for keywords, label, color, priority in PAYMENT_STATUS_RULES:
        if any(k in text for k in keywords):
            return label, color, priority
    return "📄 Info", "white", 9


def get_payment_emails(parsed):
    payments = [m for m in parsed if m.get("category") == "PAYMENT"]

    enriched = []
    for m in payments:
        text   = (m["subject"] + " " + m["snippet"]).lower()
        status, color, prio = get_payment_status(text)

        # Extraction du montant
        amount_match = re.search(r"(\d+[.,]\d{2})\s*€|€\s*(\d+[.,]\d{2})", m["subject"] + " " + m["snippet"])
        amount = amount_match.group(1) or amount_match.group(2) if amount_match else ""

        # Extraction de la date d'échéance
        date_match = re.search(
            r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{1,2}\s+(?:jan|fév|mar|avr|mai|jun|jul|aoû|sep|oct|nov|déc|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{4})",
            m["subject"] + " " + m["snippet"], re.IGNORECASE
        )
        due_date = date_match.group(0) if date_match else ""

        enriched.append({**m, "pay_status": status, "pay_color": color,
                          "pay_priority": prio, "amount": amount, "due_date": due_date})

    return sorted(enriched, key=lambda x: x["pay_priority"])


def _render_payments_table(payments: list, selected: set):
    """Tableau des paiements avec cases à cocher pour suppression."""
    t = Table(
        title=f"💳 Paiements & Finances ({len(payments)} emails)  —  [cyan]?[/cyan]=aide",
        box=box.ROUNDED, show_lines=True
    )
    t.add_column("#",          width=4,  justify="right", style="bold dim")
    t.add_column("✔",          width=3,  justify="center")
    t.add_column("Statut",     width=20)
    t.add_column("Date",       width=11, style="cyan")
    t.add_column("Expéditeur", width=20, style="magenta", no_wrap=True)
    t.add_column("Sujet",      width=36, style="white")
    t.add_column("Montant",    width=9,  style="bold green", justify="right")
    t.add_column("Échéance",   width=12, style="yellow")

    for i, m in enumerate(payments, 1):
        check = "[bold green]■[/bold green]" if i in selected else "[dim]□[/dim]"
        t.add_row(
            str(i), check,
            f"[{m['pay_color']}]{m['pay_status']}[/{m['pay_color']}]",
            m["date"].strftime("%Y-%m-%d"),
            (m["sender_name"] or m["sender_email"])[:19],
            m["subject"][:35],
            m["amount"] + " €" if m["amount"] else "—",
            m["due_date"] or "—",
        )

    nb_sel = len(selected)
    console.print(t)

    # Résumé statuts
    late     = sum(1 for m in payments if "EN RETARD" in m["pay_status"])
    upcoming = sum(1 for m in payments if "ÉCHÉANCE"  in m["pay_status"])
    reminder = sum(1 for m in payments if "RAPPEL"    in m["pay_status"])
    console.print(
        f"  [red]🔴 En retard : {late}[/red]   "
        f"[yellow]🟠 Échéances : {upcoming}[/yellow]   "
        f"[yellow]🟡 Rappels : {reminder}[/yellow]   "
        f"[dim]|[/dim]   [bold]Sélectionnés : [cyan]{nb_sel}/{len(payments)}[/cyan][/bold]\n"
    )


def _print_module_help(module: str):
    rows = {
        "payments": [
            ("1,3,5  ou  2-8", "Toggle sélection individuelle ou plage"),
            ("a",              "Tout sélectionner"),
            ("n",              "Tout désélectionner"),
            ("s CRITÈRE",      "Sélectionner par statut  ex: s retard  /  s échéance"),
            ("del",            "🗑️  Supprimer les emails sélectionnés"),
            ("arc",            "📁 Archiver les emails sélectionnés"),
            ("q",              "Retour au menu principal"),
            ("?",              "Afficher cette aide"),
        ],
        "trading": [
            ("1,3,5  ou  2-8", "Toggle sélection individuelle ou plage"),
            ("a",              "Tout sélectionner"),
            ("n",              "Tout désélectionner"),
            ("s CRITÈRE",      "Sélectionner par statut  ex: s critique  /  s signal"),
            ("del",            "🗑️  Supprimer les emails sélectionnés"),
            ("arc",            "📁 Archiver les emails sélectionnés"),
            ("q",              "Retour au menu principal"),
            ("?",              "Afficher cette aide"),
        ],
    }
    h = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    h.add_column("Cmd",  style="bold cyan", width=20)
    h.add_column("Effet",style="white",     width=50)
    for cmd, desc in rows.get(module, []):
        h.add_row(cmd, desc)
    console.print(Panel(h, title=f"💡 Aide — Module {module.capitalize()}", border_style="cyan"))


def _execute_mail_action(service, emails: list, indices: set, action: str):
    """Supprime ou archive les emails dont l'index est dans `indices`."""
    targets = [emails[i-1] for i in sorted(indices) if 1 <= i <= len(emails)]
    if not targets:
        console.print("[yellow]⚠️  Aucun email sélectionné.[/yellow]")
        return

    verb  = "supprimés" if action == "DELETE" else "archivés"
    label = f"[red]🗑️  Suppression[/red]" if action == "DELETE" else "[blue]📁 Archivage[/blue]"

    console.print(Panel(
        f"{label} de [bold]{len(targets)}[/bold] email(s) :\n" +
        "\n".join(f"  • {m['subject'][:60]}" for m in targets[:8]) +
        (f"\n  … et {len(targets)-8} autres" if len(targets) > 8 else ""),
        title="⚡ Confirmation", border_style="yellow"
    ))

    if not Confirm.ask("[bold red]Confirmer ?[/bold red]", default=False):
        console.print("[dim]→ Annulé.[/dim]")
        return

    ids = [m["id"] for m in targets]
    for start in range(0, len(ids), 1000):
        batch = ids[start:start+1000]
        if action == "DELETE":
            service.users().messages().batchDelete(userId="me", body={"ids": batch}).execute()
        else:
            service.users().messages().batchModify(
                userId="me", body={"ids": batch, "removeLabelIds": ["INBOX"]}).execute()

    console.print(f"[bold green]✅ {len(ids)} email(s) {verb}.[/bold green]")


def _parse_selection(raw: str, max_idx: int, current: set) -> set:
    """
    Parse une commande de sélection et retourne le nouvel ensemble.
    Supporte : "1"  "1,3,5"  "2-6"
    """
    new_sel = set(current)
    # Plage "2-6"
    range_m = re.match(r"^(\d+)-(\d+)$", raw)
    if range_m:
        a, b = int(range_m.group(1)), int(range_m.group(2))
        for idx in range(min(a, b), max(a, b) + 1):
            if 1 <= idx <= max_idx:
                if idx in new_sel: new_sel.discard(idx)
                else:              new_sel.add(idx)
        return new_sel
    # Liste "1,3,5"
    if re.match(r"^[\d,\s]+$", raw):
        for token in re.split(r"[,\s]+", raw):
            if token.isdigit():
                idx = int(token)
                if 1 <= idx <= max_idx:
                    if idx in new_sel: new_sel.discard(idx)
                    else:              new_sel.add(idx)
        return new_sel
    return new_sel


def interactive_payments(service, payments: list):
    """Affichage interactif des paiements avec sélection et actions."""
    if not payments:
        console.print(Panel("[green]✅ Aucun email de paiement trouvé.[/green]", border_style="green"))
        return

    selected = set()   # rien sélectionné par défaut (mode consultation)

    while True:
        console.clear()
        console.rule("[bold magenta]💳 Paiements & Finances[/bold magenta]")
        _render_payments_table(payments, selected)
        console.print(
            "  [dim]Commandes :[/dim] "
            "[cyan]1,3[/cyan]=toggle  [cyan]2-5[/cyan]=plage  "
            "[cyan]a[/cyan]=tout  [cyan]n[/cyan]=rien  "
            "[cyan]s STATUT[/cyan]=filtre  "
            "[cyan]del[/cyan]=supprimer  [cyan]arc[/cyan]=archiver  "
            "[cyan]q[/cyan]=quitter  [cyan]?[/cyan]=aide"
        )
        raw = Prompt.ask("\n[bold yellow]>[/bold yellow]").strip().lower()

        if raw == "?":
            _print_module_help("payments")
            Prompt.ask("[dim]Entrée pour continuer[/dim]")
        elif raw in ("q", ""):
            break
        elif raw == "a":
            selected = set(range(1, len(payments) + 1))
        elif raw == "n":
            selected = set()
        elif raw.startswith("s "):
            # Sélection par mot-clé de statut
            kw = raw[2:].strip()
            for i, m in enumerate(payments, 1):
                if kw in m["pay_status"].lower() or kw in m["subject"].lower():
                    selected.add(i)
            console.print(f"[green]→ {len(selected)} email(s) correspondant à « {kw} » sélectionnés.[/green]")
            Prompt.ask("[dim]Entrée pour continuer[/dim]")
        elif raw == "del":
            _execute_mail_action(service, payments, selected, "DELETE")
            selected = set()
            Prompt.ask("[dim]Entrée pour continuer[/dim]")
        elif raw == "arc":
            _execute_mail_action(service, payments, selected, "ARCHIVE")
            selected = set()
            Prompt.ask("[dim]Entrée pour continuer[/dim]")
        else:
            selected = _parse_selection(raw, len(payments), selected)


def display_payments(payments):
    """Alias simple — redirige vers le mode interactif."""
    interactive_payments(None, payments)  # service injecté via closure au besoin


# ─────────────────────────────────────────────────────────
# 📈 MODULE 3 : TRADING
# ─────────────────────────────────────────────────────────
TRADING_STATUS_RULES = [
    (["margin call", "appel de marge", "liquidation", "stop out",
      "force close", "dépôt requis", "deposit required"],          "🚨 CRITIQUE",       "bold red",    1),
    (["order filled", "order executed", "trade executed",
      "position fermée", "ordre exécuté", "filled"],               "⚡ ORDRE EXÉCUTÉ",  "bold yellow", 2),
    (["stop loss", "take profit", "sl atteint", "tp atteint"],     "🎯 SL/TP ATTEINT",  "yellow",      3),
    (["deposit", "withdrawal", "dépôt", "retrait", "wire"],        "💰 TRANSFERT",      "cyan",        4),
    (["new idea", "nouvelle idée", "signal", "alert", "alerte"],   "💡 SIGNAL/IDÉE",    "blue",        5),
    (["newsletter", "weekly", "monthly", "rapport", "report"],     "📰 RAPPORT",        "dim",         7),
    (["login", "connexion", "security", "sécurité", "2fa"],        "🔐 SÉCURITÉ",       "magenta",     2),
]

def get_trading_status(text):
    for keywords, label, color, prio in TRADING_STATUS_RULES:
        if any(k in text for k in keywords):
            return label, color, prio
    return "📊 Info Trading", "white", 6


def get_trading_emails(parsed):
    trades = [m for m in parsed if m.get("category") == "TRADING"]

    enriched = []
    for m in trades:
        text = (m["subject"] + " " + m["snippet"]).lower()
        status, color, prio = get_trading_status(text)

        # Extraction du montant/prix si présent
        price_match = re.search(
            r"(\d+[.,]\d+)\s*(?:€|\$|USD|EUR|BTC|ETH|USDT)?",
            m["subject"] + " " + m["snippet"]
        )
        price = price_match.group(0) if price_match else ""

        enriched.append({**m, "tr_status": status, "tr_color": color,
                          "tr_priority": prio, "price": price})

    return sorted(enriched, key=lambda x: (x["tr_priority"], -x["date"].timestamp()))


def _render_trading_table(trades: list, selected: set):
    """Tableau trading avec cases à cocher."""
    t = Table(
        title=f"📈 Activité Trading ({len(trades)} emails)  —  [cyan]?[/cyan]=aide",
        box=box.ROUNDED, show_lines=True
    )
    t.add_column("#",          width=4,  justify="right", style="bold dim")
    t.add_column("✔",          width=3,  justify="center")
    t.add_column("Statut",     width=20)
    t.add_column("Date",       width=11, style="cyan")
    t.add_column("Plateforme", width=16, style="magenta", no_wrap=True)
    t.add_column("Sujet",      width=38, style="white")
    t.add_column("Détail",     width=14, style="bold green")
    t.add_column("Lu",         width=4,  justify="center")

    for i, m in enumerate(trades, 1):
        check = "[bold green]■[/bold green]" if i in selected else "[dim]□[/dim]"
        lu    = "[red]●[/red]" if m["is_unread"] else "[dim]○[/dim]"
        t.add_row(
            str(i), check,
            f"[{m['tr_color']}]{m['tr_status']}[/{m['tr_color']}]",
            m["date"].strftime("%Y-%m-%d"),
            (m["sender_name"] or m["sender_email"])[:15],
            m["subject"][:37],
            m["price"][:13] if m["price"] else "—",
            lu,
        )

    console.print(t)

    # Résumé compteurs
    critical  = sum(1 for m in trades if "CRITIQUE"  in m["tr_status"])
    executed  = sum(1 for m in trades if "EXÉCUTÉ"   in m["tr_status"])
    signals   = sum(1 for m in trades if "SIGNAL"    in m["tr_status"])
    transfers = sum(1 for m in trades if "TRANSFERT" in m["tr_status"])
    nb_sel    = len(selected)
    console.print(
        f"  [bold red]🚨 Critiques : {critical}[/bold red]   "
        f"[yellow]⚡ Exécutés : {executed}[/yellow]   "
        f"[blue]💡 Signaux : {signals}[/blue]   "
        f"[cyan]💰 Transferts : {transfers}[/cyan]   "
        f"[dim]|[/dim]   [bold]Sélectionnés : [cyan]{nb_sel}/{len(trades)}[/cyan][/bold]\n"
    )


def interactive_trading(service, trades: list):
    """Affichage interactif du trading avec sélection et actions."""
    if not trades:
        console.print(Panel("[green]✅ Aucun email de trading trouvé.[/green]", border_style="green"))
        return

    selected = set()

    while True:
        console.clear()
        console.rule("[bold yellow]📈 Activité Trading[/bold yellow]")
        _render_trading_table(trades, selected)
        console.print(
            "  [dim]Commandes :[/dim] "
            "[cyan]1,3[/cyan]=toggle  [cyan]2-5[/cyan]=plage  "
            "[cyan]a[/cyan]=tout  [cyan]n[/cyan]=rien  "
            "[cyan]s STATUT[/cyan]=filtre  "
            "[cyan]del[/cyan]=supprimer  [cyan]arc[/cyan]=archiver  "
            "[cyan]q[/cyan]=quitter  [cyan]?[/cyan]=aide"
        )
        raw = Prompt.ask("\n[bold yellow]>[/bold yellow]").strip().lower()

        if raw == "?":
            _print_module_help("trading")
            Prompt.ask("[dim]Entrée pour continuer[/dim]")
        elif raw in ("q", ""):
            break
        elif raw == "a":
            selected = set(range(1, len(trades) + 1))
        elif raw == "n":
            selected = set()
        elif raw.startswith("s "):
            kw = raw[2:].strip()
            for i, m in enumerate(trades, 1):
                if kw in m["tr_status"].lower() or kw in m["subject"].lower():
                    selected.add(i)
            console.print(f"[green]→ {len(selected)} email(s) correspondant à « {kw} » sélectionnés.[/green]")
            Prompt.ask("[dim]Entrée pour continuer[/dim]")
        elif raw == "del":
            _execute_mail_action(service, trades, selected, "DELETE")
            selected = set()
            Prompt.ask("[dim]Entrée pour continuer[/dim]")
        elif raw == "arc":
            _execute_mail_action(service, trades, selected, "ARCHIVE")
            selected = set()
            Prompt.ask("[dim]Entrée pour continuer[/dim]")
        else:
            selected = _parse_selection(raw, len(trades), selected)


def display_trading(trades):
    """Alias simple — redirige vers le mode interactif."""
    interactive_trading(None, trades)


# ─────────────────────────────────────────────────────────
# 📦 MODULE 4 : LIVRAISONS
# ─────────────────────────────────────────────────────────
def get_delivery_emails(service, parsed):
    deliveries = []
    candidates = [m for m in parsed if m.get("category") == "DELIVERY"]
    with Progress(SpinnerColumn(), TextColumn("📦 Analyse livraisons..."), console=console) as p:
        task = p.add_task("", total=len(candidates))
        for m in candidates:
            text    = (m["subject"] + " " + m["snippet"]).lower()
            detail  = get_message_detail(service, m["id"])
            body    = decode_body(detail.get("payload", {})) if detail else ""
            all_txt = text + " " + body.lower()

            status = "📬 Info"
            if any(w in all_txt for w in ["delivered", "livré", "remis"]):
                status = "✅ Livré"
            elif any(w in all_txt for w in ["out for delivery", "en cours de livraison"]):
                status = "🚚 En livraison"
            elif any(w in all_txt for w in ["shipped", "expédié", "en transit"]):
                status = "📦 Expédié"
            elif any(w in all_txt for w in ["order", "commande", "confirmé"]):
                status = "🛒 Confirmé"

            # Tracking numbers
            tracking = []
            for carrier, pattern in TRACKING_PATTERNS.items():
                for match in re.findall(pattern, all_txt, re.IGNORECASE):
                    if len(str(match)) > 8:
                        tracking.append(f"{carrier}: {match}")

            deliveries.append({**m, "delivery_status": status, "tracking": tracking})
            p.advance(task)
    return sorted(deliveries, key=lambda x: x["date"], reverse=True)


def display_deliveries(deliveries):
    if not deliveries:
        console.print(Panel("[green]📭 Aucune livraison détectée.[/green]", border_style="green"))
        return
    t = Table(title=f"📦 Livraisons ({len(deliveries)})", box=box.ROUNDED, show_lines=True)
    t.add_column("Statut",      width=18)
    t.add_column("Date",        width=12, style="cyan")
    t.add_column("Expéditeur",  width=20, style="magenta")
    t.add_column("Sujet",       width=40, style="white")
    t.add_column("Tracking",    width=28, style="yellow")
    for m in deliveries[:15]:
        border = ("green" if "✅" in m["delivery_status"] else
                  "yellow" if "🚚" in m["delivery_status"] else "blue")
        t.add_row(
            f"[{border}]{m['delivery_status']}[/{border}]",
            m["date"].strftime("%Y-%m-%d"),
            (m["sender_name"] or m["sender_email"])[:19],
            m["subject"][:39],
            "\n".join(m["tracking"][:2]) if m["tracking"] else "—",
        )
    console.print(t)


# ─────────────────────────────────────────────────────────
# 📊 MODULE 5 : ANALYSE DES EXPÉDITEURS
# ─────────────────────────────────────────────────────────
def analyze_senders(parsed):
    stats = defaultdict(lambda: {
        "name": "", "email": "", "domain": "", "category": "OTHER",
        "count": 0, "unread": 0, "dates": [], "subjects": [],
    })
    for msg in parsed:
        e = msg["sender_email"]
        s = stats[e]
        s["name"]     = msg["sender_name"] or e
        s["email"]    = e
        s["domain"]   = e.split("@")[-1] if "@" in e else e
        s["category"] = msg.get("category", "OTHER")
        s["count"]   += 1
        s["dates"].append(msg["date"])
        if msg["is_unread"]: s["unread"] += 1
        s["subjects"].append(msg["subject"])

    for e, s in stats.items():
        s["last_date"]     = max(s["dates"]) if s["dates"] else datetime.datetime.min
        span               = max((max(s["dates"]) - min(s["dates"])).days, 1) if len(s["dates"]) > 1 else 1
        s["freq_per_week"] = round(s["count"] / (span / 7), 1)

    return dict(stats)


CATEGORY_ICONS = {
    "TRADING" : "📈", "PAYMENT": "💳", "DELIVERY": "📦",
    "PROMO"   : "📢", "URGENT" : "🔴", "OTHER"   : "📧",
}

def display_senders(sender_stats):
    sorted_s = sorted(sender_stats.values(), key=lambda x: x["count"], reverse=True)
    t = Table(
        title=f"📊 Expéditeurs — Top 30 (sur {len(sorted_s)} uniques)",
        box=box.SIMPLE_HEAD
    )
    t.add_column("#",         width=4,  style="dim")
    t.add_column("Expéditeur",width=26, style="bold cyan")
    t.add_column("Domaine",   width=22, style="blue")
    t.add_column("Catégorie", width=14)
    t.add_column("Total",     width=7,  justify="right", style="bold white")
    t.add_column("Non lus",   width=8,  justify="right")
    t.add_column("Fréq/sem",  width=9,  justify="right", style="yellow")
    t.add_column("Dernier",   width=12, style="green")

    cat_colors = {
        "TRADING" : "bold yellow", "PAYMENT": "bold magenta",
        "DELIVERY": "bold blue",   "PROMO"  : "dim",
        "URGENT"  : "bold red",    "OTHER"  : "white",
    }
    for i, s in enumerate(sorted_s[:30], 1):
        icon  = CATEGORY_ICONS.get(s["category"], "📧")
        color = cat_colors.get(s["category"], "white")
        unread_str = f"[red]{s['unread']}[/red]" if s["unread"] > 0 else "0"
        t.add_row(
            str(i),
            (s["name"] or s["email"])[:25],
            s["domain"][:21],
            f"[{color}]{icon} {s['category']}[/{color}]",
            str(s["count"]),
            unread_str,
            str(s["freq_per_week"]),
            s["last_date"].strftime("%Y-%m-%d"),
        )
    console.print(t)

    # Stats par catégorie
    from collections import Counter
    cat_count = Counter(s["category"] for s in sender_stats.values())
    summary = Table(box=box.SIMPLE, show_header=False)
    summary.add_column("Cat",  style="bold")
    summary.add_column("Exp.", style="white", justify="right")
    summary.add_column("Emails", style="bold white", justify="right")
    for cat, icon in CATEGORY_ICONS.items():
        senders_in_cat = [s for s in sender_stats.values() if s["category"] == cat]
        total_emails   = sum(s["count"] for s in senders_in_cat)
        if senders_in_cat:
            summary.add_row(f"{icon} {cat}", str(len(senders_in_cat)), str(total_emails))
    console.print(Panel(summary, title="📈 Répartition par catégorie", border_style="cyan"))


# ─────────────────────────────────────────────────────────
# 🧹 MODULE 6 : NETTOYAGE
# ─────────────────────────────────────────────────────────
def generate_cleanup_plan(sender_stats):
    suggestions = []
    for s in sorted(sender_stats.values(), key=lambda x: x["count"], reverse=True):
        read = s["count"] - s["unread"]

        # Newsletters lues → archiver
        if s["category"] == "PROMO" and s["count"] >= 5 and s["unread"] == 0:
            suggestions.append({
                "type": "ARCHIVE", "priority": "LOW", "count": s["count"],
                "sender": s["name"], "sender_email": s["email"],
                "description": f"Archiver {s['count']} promos lues de {s['name']}",
                "email_filter": f"from:{s['email']}",
            })
        # Newsletter non lue en masse → supprimer
        if s["category"] == "PROMO" and s["unread"] > 10:
            suggestions.append({
                "type": "DELETE", "priority": "HIGH", "count": s["unread"],
                "sender": s["name"], "sender_email": s["email"],
                "description": f"Supprimer {s['unread']} promos non lues de {s['name']}",
                "email_filter": f"from:{s['email']} is:unread",
            })
        # Emails lus en volume (hors trading/paiement) → archiver
        if s["category"] == "OTHER" and read > 20:
            suggestions.append({
                "type": "ARCHIVE", "priority": "LOW", "count": read,
                "sender": s["name"], "sender_email": s["email"],
                "description": f"Archiver {read} emails lus de {s['name']}",
                "email_filter": f"from:{s['email']} is:read",
            })
        # Fréquence excessive
        if s["freq_per_week"] > 10 and s["category"] not in ("TRADING", "PAYMENT"):
            suggestions.append({
                "type": "REVIEW", "priority": "MEDIUM", "count": s["count"],
                "sender": s["name"], "sender_email": s["email"],
                "description": f"⚠️  {s['name']} → {s['freq_per_week']} emails/semaine",
                "email_filter": f"from:{s['email']}",
            })

    prio_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(suggestions, key=lambda x: prio_order.get(x["priority"], 3))


# ── Helpers visuels nettoyage ────────────────────────────────
ACTION_TYPES   = ["DELETE", "ARCHIVE", "REVIEW", "SKIP"]
ACTION_LABELS  = {
    "DELETE" : "[red]🗑️  SUPPRIMER[/red]",
    "ARCHIVE": "[blue]📁 ARCHIVER[/blue]",
    "REVIEW" : "[yellow]👁️  RÉVISER[/yellow]",
    "SKIP"   : "[dim]⏭️  IGNORER[/dim]",
}
PRIO_LABELS = {
    "HIGH"  : "[bold red]🔴 HAUTE[/bold red]",
    "MEDIUM": "[yellow]🟡 MOYENNE[/yellow]",
    "LOW"   : "[green]🟢 BASSE[/green]",
}

def _render_cleanup_table(suggestions: list, selected: set):
    """Affiche le plan de nettoyage avec cases à cocher et actions modifiables."""
    t = Table(
        title="🧹 Éditeur du Plan de Nettoyage  —  [cyan]?[/cyan]=aide",
        box=box.ROUNDED, show_lines=True, expand=False
    )
    t.add_column("#",          width=4,  justify="right", style="bold dim")
    t.add_column("✔",          width=3,  justify="center")
    t.add_column("Priorité",   width=12)
    t.add_column("Action",     width=13)
    t.add_column("Expéditeur", width=24, style="cyan",  no_wrap=True)
    t.add_column("Description",width=40, style="white")
    t.add_column("Emails",     width=7,  justify="right", style="bold")

    for i, s in enumerate(suggestions, 1):
        check  = "[bold green]■[/bold green]" if i in selected else "[dim]□[/dim]"
        prio   = PRIO_LABELS.get(s["priority"], s["priority"])
        action = ACTION_LABELS.get(s["type"], s["type"])
        t.add_row(
            str(i), check, prio, action,
            (s["sender"] or s["sender_email"])[:23],
            s["description"][:39],
            str(s["count"]),
        )

    total_sel = sum(s["count"] for i, s in enumerate(suggestions, 1)
                    if i in selected and s["type"] in ("DELETE", "ARCHIVE"))
    console.print(t)
    console.print(
        f"  [bold]Sélectionnés :[/bold] [cyan]{len(selected)}/{len(suggestions)}[/cyan] actions  |  "
        f"[bold]Emails concernés :[/bold] [bold yellow]{total_sel}[/bold yellow]"
    )


def _print_cleanup_help():
    h = Table(box=box.SIMPLE, show_header=False, padding=(0,1))
    h.add_column("Cmd",  style="bold cyan",   width=18)
    h.add_column("Effet",style="white",        width=52)
    rows = [
        ("1,3,5  ou  2-8",   "Sélectionner / désélectionner les lignes indiquées"),
        ("a",                 "Sélectionner TOUTES les actions"),
        ("n",                 "Désélectionner tout"),
        ("t N ACTION",        "Changer l'action de la ligne N  (DELETE/ARCHIVE/REVIEW/SKIP)"),
        ("p N PRIO",          "Changer la priorité de la ligne N  (HIGH/MEDIUM/LOW)"),
        ("go",                "Exécuter les actions SÉLECTIONNÉES"),
        ("q  ou  retour",     "Retour au menu principal sans exécuter"),
        ("?",                 "Afficher cette aide"),
    ]
    for cmd, desc in rows:
        h.add_row(cmd, desc)
    console.print(Panel(h, title="💡 Aide — Éditeur de nettoyage", border_style="cyan"))


def interactive_cleanup_editor(service, suggestions: list):
    """
    Éditeur interactif en console pour le plan de nettoyage.
    Permet :
      - cocher/décocher chaque action individuellement ou en lot
      - changer le type (DELETE ↔ ARCHIVE ↔ REVIEW ↔ SKIP)
      - changer la priorité
      - exécuter uniquement les actions cochées
    """
    if not suggestions:
        console.print(Panel("[green]✅ Aucune action de nettoyage suggérée.[/green]", border_style="green"))
        return

    # Copie locale pour ne pas altérer la liste originale
    plan     = [dict(s) for s in suggestions]
    selected = set(range(1, len(plan) + 1))   # tout coché par défaut

    while True:
        console.clear()
        console.rule("[bold cyan]🧹 Éditeur du Plan de Nettoyage[/bold cyan]")
        _render_cleanup_table(plan, selected)

        console.print(
            "  [dim]Commandes :[/dim] "
            "[cyan]1,3[/cyan]=toggle  [cyan]2-5[/cyan]=plage  "
            "[cyan]a[/cyan]=tout  [cyan]n[/cyan]=rien  "
            "[cyan]t N TYPE[/cyan]=changer action  "
            "[cyan]go[/cyan]=exécuter  "
            "[cyan]q[/cyan]=quitter  "
            "[cyan]?[/cyan]=aide"
        )
        raw = Prompt.ask("\n[bold yellow]>[/bold yellow]").strip().lower()

        # ── Aide ─────────────────────────────────────────────────
        if raw == "?":
            _print_cleanup_help()
            Prompt.ask("[dim]Appuyer sur Entrée pour continuer[/dim]")
            continue

        # ── Quitter ───────────────────────────────────────────────
        if raw in ("q", "quit", "retour", ""):
            console.print("[dim]→ Retour au menu principal.[/dim]")
            break

        # ── Tout sélectionner ────────────────────────────────────
        if raw == "a":
            selected = set(range(1, len(plan) + 1))
            continue

        # ── Tout désélectionner ──────────────────────────────────
        if raw == "n":
            selected = set()
            continue

        # ── Exécuter ─────────────────────────────────────────────
        if raw == "go":
            to_run = [plan[i-1] for i in sorted(selected)
                      if plan[i-1]["type"] not in ("SKIP", "REVIEW")]
            if not to_run:
                console.print("[yellow]⚠️  Aucune action exécutable sélectionnée (SKIP/REVIEW exclus).[/yellow]")
                Prompt.ask("[dim]Entrée pour continuer[/dim]")
                continue

            console.print(Panel(
                f"[bold]Vous allez exécuter {len(to_run)} action(s) :[/bold]\n" +
                "\n".join(f"  [{ACTION_LABELS[s['type']]}] {s['description']}" for s in to_run),
                title="⚡ Confirmation", border_style="yellow"
            ))
            if not Confirm.ask("[bold red]Confirmer l'exécution ?[/bold red]", default=False):
                continue

            executed = 0
            for s in to_run:
                console.print(f"\n[bold]→ {s['description']}[/bold]  [dim]({s['type']})[/dim]")
                msgs = get_messages(service, max_results=500, query=s["email_filter"])
                ids  = [m["id"] for m in msgs]
                if not ids:
                    console.print("[dim]  Aucun message trouvé.[/dim]")
                    continue
                for start in range(0, len(ids), 1000):
                    batch = ids[start:start+1000]
                    if s["type"] == "DELETE":
                        service.users().messages().batchDelete(
                            userId="me", body={"ids": batch}).execute()
                    elif s["type"] == "ARCHIVE":
                        service.users().messages().batchModify(
                            userId="me",
                            body={"ids": batch, "removeLabelIds": ["INBOX"]}).execute()
                console.print(f"  [green]✅ {len(ids)} messages traités.[/green]")
                executed += 1

            console.print(Rule())
            console.print(f"[bold green]✅ {executed} action(s) exécutée(s) avec succès ![/bold green]")
            Prompt.ask("[dim]Entrée pour continuer[/dim]")
            break

        # ── Changer le type d'action : t N TYPE ─────────────────
        if raw.startswith("t "):
            parts = raw.split()
            if len(parts) == 3:
                try:
                    idx    = int(parts[1])
                    new_tp = parts[2].upper()
                    if 1 <= idx <= len(plan) and new_tp in ACTION_TYPES:
                        plan[idx-1]["type"] = new_tp
                        console.print(f"[green]→ Action {idx} changée en {new_tp}[/green]")
                    else:
                        console.print(f"[red]Index ou type invalide. Types valides : {', '.join(ACTION_TYPES)}[/red]")
                except ValueError:
                    console.print("[red]Format : t N TYPE  (ex: t 3 DELETE)[/red]")
            else:
                console.print("[red]Format : t N TYPE  (ex: t 3 ARCHIVE)[/red]")
            continue

        # ── Changer la priorité : p N PRIO ───────────────────────
        if raw.startswith("p "):
            parts = raw.split()
            if len(parts) == 3:
                try:
                    idx     = int(parts[1])
                    new_p   = parts[2].upper()
                    if 1 <= idx <= len(plan) and new_p in ("HIGH", "MEDIUM", "LOW"):
                        plan[idx-1]["priority"] = new_p
                        console.print(f"[green]→ Priorité {idx} changée en {new_p}[/green]")
                    else:
                        console.print("[red]Index ou priorité invalide. Valides : HIGH MEDIUM LOW[/red]")
                except ValueError:
                    console.print("[red]Format : p N PRIO  (ex: p 2 HIGH)[/red]")
            else:
                console.print("[red]Format : p N PRIO  (ex: p 1 LOW)[/red]")
            continue

        # ── Toggle/plage de numéros : 1,3,5  ou  2-7 ────────────
        # Plage : "2-5"
        range_match = re.match(r"^(\d+)-(\d+)$", raw)
        if range_match:
            a, b = int(range_match.group(1)), int(range_match.group(2))
            for idx in range(min(a,b), max(a,b)+1):
                if 1 <= idx <= len(plan):
                    if idx in selected: selected.discard(idx)
                    else:               selected.add(idx)
            continue

        # Liste : "1,3,5"
        if re.match(r"^[\d,\s]+$", raw):
            for token in re.split(r"[,\s]+", raw):
                if token.isdigit():
                    idx = int(token)
                    if 1 <= idx <= len(plan):
                        if idx in selected: selected.discard(idx)
                        else:               selected.add(idx)
            continue

        # Commande inconnue
        console.print("[red]Commande non reconnue. Tapez [bold]?[/bold] pour l'aide.[/red]")


# ── Affichage simple du plan (lecture seule) ─────────────────
def display_cleanup(suggestions):
    if not suggestions:
        console.print(Panel("[green]✅ Boîte déjà bien organisée ![/green]", border_style="green"))
        return
    _render_cleanup_table(suggestions, set(range(1, len(suggestions)+1)))
    console.print("[dim]Utilisez l'option [bold]7[/bold] du menu pour éditer et exécuter.[/dim]")


# ─────────────────────────────────────────────────────────
# 🎛️  MENU PRINCIPAL
# ─────────────────────────────────────────────────────────
BANNER = """
╔══════════════════════════════════════════════════════════╗
║        Gmail Smart Manager — Premier Tech Edition        ║
║              Pascal Bey  ·  v2.2  ·  2026               ║
╠══════════════════════════════════════════════════════════╣
║  🔴 Urgents   💳 Paiements   📈 Trading                  ║
║  📦 Colis     📊 Expéditeurs  🧹 Nettoyage               ║
╚══════════════════════════════════════════════════════════╝
"""

def main():
    console.print(Panel(BANNER, border_style="cyan", padding=(0, 2)))

    # Auth
    console.print("\n[bold]🔐 Connexion Gmail...[/bold]")
    try:
        service = authenticate_gmail()
        console.print("[green]✅ Connecté ![/green]\n")
    except FileNotFoundError:
        return

    # Chargement
    console.print(f"[bold]📥 Chargement des {MAX_MESSAGES} derniers messages INBOX...[/bold]")
    raw = get_messages(service, max_results=MAX_MESSAGES, label_ids=["INBOX"])
    if not raw:
        console.print("[red]Aucun message trouvé.[/red]"); return
    console.print(f"[green]✅ {len(raw)} messages récupérés.[/green]\n")

    # Parsing + catégorisation
    with Progress(SpinnerColumn(), TextColumn("Parsing et catégorisation..."), console=console) as p:
        task   = p.add_task("", total=len(raw))
        parsed = []
        for rm in raw:
            d = get_message_detail(service, rm["id"])
            if d:
                msg = parse_message(d)
                msg["category"] = categorize_message(msg)
                parsed.append(msg)
            p.advance(task)

    console.print(f"[green]✅ {len(parsed)} messages parsés.[/green]\n")

    # Pré-calculs
    sender_stats = analyze_senders(parsed)
    suggestions  = generate_cleanup_plan(sender_stats)

    # Résumé rapide au démarrage
    from collections import Counter
    cats = Counter(m.get("category","OTHER") for m in parsed)
    console.print(Panel(
        f"  📈 Trading   : [bold yellow]{cats.get('TRADING',0)}[/bold yellow] emails\n"
        f"  💳 Paiements : [bold magenta]{cats.get('PAYMENT',0)}[/bold magenta] emails\n"
        f"  📦 Livraisons: [bold blue]{cats.get('DELIVERY',0)}[/bold blue] emails\n"
        f"  📢 Promos    : [bold dim]{cats.get('PROMO',0)}[/bold dim] emails\n"
        f"  📧 Autres    : {cats.get('OTHER',0)} emails\n"
        f"  👥 Expéditeurs uniques : {len(sender_stats)}",
        title="📊 Vue d'ensemble", border_style="cyan"
    ))

    # Menu
    while True:
        console.print(Rule("[bold]MENU[/bold]"))
        t = Table(box=box.SIMPLE, show_header=False)
        t.add_column("", style="bold cyan",  width=4)
        t.add_column("", style="bold white", width=45)
        t.add_row("1", "🔴 Emails urgents / importants à répondre")
        t.add_row("2", "💳 Paiements en cours / à faire")
        t.add_row("3", "📈 Activité Trading (Kraken, TradingView...)")
        t.add_row("4", "📦 Suivi des livraisons de colis")
        t.add_row("5", "📊 Analyse et tri des expéditeurs")
        t.add_row("6", "🧹 Plan de nettoyage")
        t.add_row("7", "⚡ Exécuter le nettoyage")
        t.add_row("8", "🔄 Rafraîchir les emails")
        t.add_row("0", "🚪 Quitter")
        console.print(t)

        choice = Prompt.ask("[bold cyan]Votre choix[/bold cyan]",
                            choices=["0","1","2","3","4","5","6","7","8"])

        if choice == "1":
            display_urgent(get_urgent_emails(service, parsed))
        elif choice == "2":
            interactive_payments(service, get_payment_emails(parsed))
        elif choice == "3":
            interactive_trading(service, get_trading_emails(parsed))
        elif choice == "4":
            display_deliveries(get_delivery_emails(service, parsed))
        elif choice == "5":
            display_senders(sender_stats)
        elif choice == "6":
            display_cleanup(suggestions)
        elif choice == "7":
            interactive_cleanup_editor(service, suggestions)
        elif choice == "8":
            console.print("[yellow]🔄 Rechargement...[/yellow]")
            raw    = get_messages(service, max_results=MAX_MESSAGES, label_ids=["INBOX"])
            parsed = []
            for rm in raw:
                d = get_message_detail(service, rm["id"])
                if d:
                    msg = parse_message(d)
                    msg["category"] = categorize_message(msg)
                    parsed.append(msg)
            sender_stats = analyze_senders(parsed)
            suggestions  = generate_cleanup_plan(sender_stats)
            console.print(f"[green]✅ {len(parsed)} messages rechargés.[/green]")
        elif choice == "0":
            console.print("[bold cyan]\n👋 À bientôt, Pascal !\n[/bold cyan]")
            break

if __name__ == "__main__":
    main()
