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

# Mots-clés urgence RÉELLE
# ⚠️  Règle : chaque mot-clé doit SEUL impliquer une action humaine requise
# ❌  Retirés car trop génériques (déclenchaient faux positifs) :
#     "votre compte", "your account", "verify", "vérifiez",
#     "confirmation requise" → présents dans tout email transactionnel/promo
URGENT_KEYWORDS = [
    # Urgence explicite
    "urgent", "urgence",
    "action requise", "action required",
    "réponse requise", "response needed", "response required",
    "please respond", "awaiting your reply", "awaiting your response",
    # Délais réels
    "deadline", "overdue", "en retard", "past due",
    "dès que possible", "asap",
    "time sensitive", "time-sensitive",
    # Blocage
    "bloqué", "blocked", "suspendu", "suspended",
    "accès refusé", "access denied", "account suspended",
    "compte bloqué", "account locked",
    # Financier critique (hors module PAYMENT/TRADING)
    "impayé", "unpaid", "recouvrement", "huissier",
    "mise en demeure", "formal notice",
]

# Indicateurs newsletters/promos → si présents, score urgence réduit
PROMO_INDICATORS = [
    "unsubscribe", "désabonner", "se désabonner",
    "newsletter", "no-reply", "noreply", "do-not-reply",
    "offre exclusive", "bon plan", "bons plans", "promo", "solde",
    "réduction", "discount", "-50%", "-30%", "cashback",
    "découvrir", "voir les offres", "shop now", "achetez",
]

# ── Mots-clés → catégorie NOTIF (onboarding, confirmations auto) ─────────────
NOTIF_KEYWORDS = [
    "bienvenue", "welcome", "compte créé", "account created",
    "mot de passe initial", "initial password",
    "confirmez votre email", "confirm your email",
    "verify your email", "vérifiez votre adresse",
    "nouveau bénéficiaire", "new beneficiary",
    "connexion depuis", "new login", "new sign-in",
    "code de vérification", "verification code",
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

# ═══════════════════════════════════════════════════════════════════════
# 🏷️  CATÉGORISATION À 2 NIVEAUX
# Niveau 1 : SENDER_DEFAULT  → catégorie par défaut selon expéditeur
# Niveau 2 : SUBJECT_OVERRIDES → mots-clés sujet qui overrident le défaut
# ═══════════════════════════════════════════════════════════════════════

SENDER_DEFAULT = {
    # 📦 TRANSPORTEURS PURS
    "colis prive"        : "DELIVERY",  "colisprive"       : "DELIVERY",
    "ups"                : "DELIVERY",  "fedex"            : "DELIVERY",
    "dhl"                : "DELIVERY",  "purolator"        : "DELIVERY",
    "intelcom"           : "DELIVERY",  "chronopost"       : "DELIVERY",
    "mondial relay"      : "DELIVERY",  "gls"              : "DELIVERY",
    "amazon logistics"   : "DELIVERY",  "nationex"         : "DELIVERY",
    "dicom"              : "DELIVERY",

    # 📈 TRADING PURS — uniquement plateformes crypto/bourse dédiées
    # Règle : seuls les expéditeurs dont le BUT UNIQUE est le trading
    "kraken"             : "TRADING",   "tradingview"      : "TRADING",
    "binance"            : "TRADING",   "coinbase"         : "TRADING",
    "crypto.com"         : "TRADING",   "coinhouse"        : "TRADING",
    "bitget"             : "TRADING",   "bybit"            : "TRADING",
    "kucoin"             : "TRADING",   "bitmex"           : "TRADING",
    "ftx"                : "TRADING",   "gate.io"          : "TRADING",
    "okx"                : "TRADING",   "huobi"            : "TRADING",
    # Bourse traditionnelle
    "degiro"             : "TRADING",   "bourse direct"    : "TRADING",
    "interactive broker" : "TRADING",   "saxo"             : "TRADING",
    "ig.com"             : "TRADING",   "trade republic"   : "TRADING",
    # Revolut → BANQUE (app bancaire qui PROPOSE aussi du crypto)
    # Ses emails sont à 80% du marketing, pas du vrai trading
    "revolut"            : "BANQUE",

    # 💳 PAIEMENT PURS
    "paypal"             : "PAYMENT",   "klarna"           : "PAYMENT",
    "cofidis"            : "PAYMENT",   "oney"             : "PAYMENT",
    "alma"               : "PAYMENT",   "floa"             : "PAYMENT",
    "cetelem"            : "PAYMENT",   "sofinco"          : "PAYMENT",
    "stripe"             : "PAYMENT",   "lydia"            : "PAYMENT",
    "sumeria"            : "PAYMENT",

    # 🏦 BANQUE
    "boursorama"         : "BANQUE",    "fortuneo"         : "BANQUE",
    "societegenerale"    : "BANQUE",    "bnp"              : "BANQUE",
    "credit agricole"    : "BANQUE",    "caisse d'epargne" : "BANQUE",
    "credit mutuel"      : "BANQUE",    "banque postale"   : "BANQUE",
    "la banque postale"  : "BANQUE",    "lcl"              : "BANQUE",
    "hsbc"               : "BANQUE",    "ing"              : "BANQUE",
    "hello bank"         : "BANQUE",    "n26"              : "BANQUE",
    # SG → BANQUE (override possible vers PAYMENT si "virement")
    "sg"                 : "BANQUE",    "societegenerale"  : "BANQUE",

    # 🏥 SANTÉ
    "ameli"              : "SANTE",     "cpam"             : "SANTE",
    "assurance maladie"  : "SANTE",     "assurance malad"  : "SANTE",
    "mgen"               : "SANTE",     "malakoff"         : "SANTE",
    "alan"               : "SANTE",     "maif"             : "SANTE",

    # 📱 TÉLÉCOM
    "sfr"                : "TELECOM",   "orange"           : "TELECOM",
    "bouygues"           : "TELECOM",   "free"             : "TELECOM",
    "sosh"               : "TELECOM",   "red by sfr"       : "TELECOM",
    "prixtel"            : "TELECOM",   "coriolis"         : "TELECOM",

    # 🛡️ ASSURANCE
    "maaf"               : "ASSURANCE", "allianz"          : "ASSURANCE",
    "matmut"             : "ASSURANCE", "macif"            : "ASSURANCE",
    "axa"                : "ASSURANCE", "generali"         : "ASSURANCE",
    "covea"              : "ASSURANCE", "groupama"         : "ASSURANCE",

    # ⚡ ÉNERGIE
    "edf"                : "ENERGIE",   "engie"            : "ENERGIE",
    "totalenergies"      : "ENERGIE",   "ekwateur"         : "ENERGIE",
    "lesfurets"          : "ENERGIE",   "hello watt"       : "ENERGIE",

    # 🚢 Croisières / voyages promos
    "croisiere"          : "PROMO",
    "croisières"         : "PROMO",
    "destockage crois"   : "PROMO",
    "déstockage crois"   : "PROMO",
    "so'croisières"      : "PROMO",
    "so croisières"      : "PROMO",
    # 📢 PROMO / MULTI-CAT (override par sujet possible)
    "amazon"             : "PROMO",     "fnac"             : "PROMO",
    "cdiscount"          : "PROMO",     "aliexpress"       : "PROMO",
    "ebay"               : "PROMO",     "vente-privee"     : "PROMO",
    "veepee"             : "PROMO",     "leroy merlin"     : "PROMO",
    "boulanger"          : "PROMO",     "darty"            : "PROMO",
    "decathlon"          : "PROMO",     "groupon"          : "PROMO",
    "ebuyclub"           : "PROMO",     "voyage prive"     : "PROMO",
    "voyage privé"       : "PROMO",     "voyageprive"      : "PROMO",
    "france.tv"          : "PROMO",     "substack"         : "PROMO",
    "medium"             : "PROMO",     "taaft"            : "PROMO",
    "brilland"           : "PROMO",     "felix baron"      : "PROMO",
    "club des invest"    : "PROMO",     "prime video"      : "PROMO",
    "vistaprint"         : "PROMO",

    # 🔔 NOTIF PURS
    "mailersend"         : "NOTIF",     "sendgrid"         : "NOTIF",
    "mailchimp"          : "NOTIF",     "ecoflow"          : "NOTIF",
    "no-reply"           : "NOTIF",     "noreply"          : "NOTIF",
    "do-not-reply"       : "NOTIF",     "donotreply"       : "NOTIF",
}

SUBJECT_OVERRIDES = {
    # Priorité décroissante : DELIVERY > PAYMENT > TRADING > ...
    "DELIVERY": [
        "expédié", "shipped", "livraison", "livré", "en transit",
        "suivi de", "tracking", "colis", "commande expédiée",
        "order shipped", "out for delivery", "en cours de livraison",
        "votre commande est en route", "numéro de suivi",
    ],
    "PAYMENT": [
        "facture", "invoice", "échéance", "echeance", "prélèvement",
        "mensualité", "4x", "3x", "crédit renouvelable",
        "montant dû", "amount due", "relevé de compte",
        "votre abonnement", "renouvellement", "renewal",
        "regroupement de crédit",
    ],
    "TRADING": [
        "ordre d'achat", "ordre de vente", "order executed",
        "exécuté", "crypto", "btc", "eth", "sol", "trading",
        "négocier", "portefeuille", "wallet",
    ],
    "ENERGIE": [
        "facture énergie", "consommation électricité", "nouveau calendrier",
        "votre facture de gaz", "relevé de compteur",
    ],
    "SANTE": [
        "remboursement santé", "soins", "ordonnance", "pharmacie",
        "relevé de remboursement", "carte vitale",
    ],
    "BANQUE": [
        "relevé de compte", "virement", "découvert",
        "nouveau bénéficiaire", "extrait de compte",
    ],
    "TELECOM": [
        "votre facture", "facture mensuelle", "consommation",
        "recharge", "forfait mobile",
    ],
    "NOTIF": [
        "bienvenue", "welcome", "compte créé", "confirmez",
        "confirm your email", "verify your email",
        "connexion depuis", "code de vérification",
    ],
    "PROMO": [
        "offre", "promo", "réduction", "solde", "bon plan",
        "-50%", "-30%", "-20%", "cashback", "découvrez nos",
        "vos offres", "coup de coeur", "besoin d'un break",
        "à partir de", "dès maintenant",
    ],
}

# Catégories dont le défaut NE PEUT PAS être overridé vers autre chose
LOCKED_CATEGORIES = {"TRADING", "DELIVERY"}

# ── Alias pour compatibilité ─────────────────────────────────────────
SENDER_CATEGORIES = SENDER_DEFAULT

def categorize_message(msg) -> str:
    """
    Catégorisation à 2 niveaux :
      Niveau 1 → SENDER_DEFAULT  : catégorie par défaut selon expéditeur
      Niveau 2 → SUBJECT_OVERRIDES : override par mots-clés du sujet
    Les catégories LOCKED_CATEGORIES (TRADING, DELIVERY) ne sont jamais dégradées.
    """
    sender  = (msg["sender_name"] + " " + msg["sender_email"]).lower()
    subject = msg["subject"].lower()
    content = subject + " " + msg["snippet"].lower()

    # ── Niveau 1 : défaut expéditeur ────────────────────────────────
    default_cat = None
    for key, cat in SENDER_DEFAULT.items():
        if key in sender:
            default_cat = cat
            break

    # ── Niveau 2 : override par sujet ───────────────────────────────
    OVERRIDE_PRIORITY = [
        "DELIVERY", "PAYMENT", "TRADING", "ENERGIE",
        "SANTE", "BANQUE", "TELECOM", "ASSURANCE", "NOTIF", "PROMO"
    ]
    for cat in OVERRIDE_PRIORITY:
        if any(kw in content for kw in SUBJECT_OVERRIDES.get(cat, [])):
            # Ne pas dégrader une catégorie verrouillée
            if default_cat in LOCKED_CATEGORIES and cat not in LOCKED_CATEGORIES:
                continue
            return cat

    # ── Catégorie défaut expéditeur connu ────────────────────────────
    if default_cat:
        return default_cat

    # ── Fallback global ──────────────────────────────────────────────
    combined = sender + " " + content
    if any(kw in combined for kw in TRADING_CRITICAL_KEYWORDS): return "TRADING"
    if any(kw in combined for kw in PAYMENT_KEYWORDS):          return "PAYMENT"
    if any(kw in combined for kw in DELIVERY_KEYWORDS):         return "DELIVERY"
    if any(kw in combined for kw in NOTIF_KEYWORDS):            return "NOTIF"
    if sum(1 for p in PROMO_INDICATORS if p in combined) >= 2:  return "PROMO"
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
            if msg.get("category") in ("PAYMENT", "TRADING", "DELIVERY", "PROMO", "NOTIF",
                                   "BANQUE", "SANTE", "TELECOM", "ASSURANCE", "ENERGIE"):
                p.advance(task); continue  # traités dans leurs modules ou ignorés; continue  # traités dans leurs modules ou ignorés
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


def _parse_amount(text: str) -> float:
    """Extrait le premier montant trouvé dans un texte, retourne 0.0 si absent."""
    m = re.search(r"(\d+[.,]\d{2})\s*€|€\s*(\d+[.,]\d{2})", text)
    if m:
        raw = m.group(1) or m.group(2)
        return float(raw.replace(",", "."))
    return 0.0


def _group_installments(enriched: list) -> list:
    """
    Regroupe les paiements fractionnés (4X, 3X, etc.) par marchand/montant.
    Ajoute pour chaque groupe :
      - total_amount   : montant total estimé
      - paid_amount    : montant déjà payé
      - remaining      : reste à payer
      - installments   : liste des versements détectés
      - progress_bar   : barre de progression ASCII
    """
    # Patterns de détection de paiement fractionné
    FRAC_PATTERNS = [
        r"(\d+)[eè]re?\s+(?:fois|paiement|versement)",   # "1er paiement"
        r"(\d+)(?:e|ème|eme)\s+(?:fois|paiement|versement)",  # "2e paiement"
        r"paiement\s+(\d+)\s*/\s*(\d+)",                  # "paiement 2/4"
        r"(\d+)\s*/\s*(\d+)\s+(?:paiements?|versements?)",
        r"en\s+(\d+)[xX]\s+de",                           # "en 4X de"
        r"(\d+)[xX]\s+(?:sans frais|de|\d)",
    ]

    groups = {}   # clé → liste de messages

    for m in enriched:
        text = (m["subject"] + " " + m["snippet"]).lower()

        # Déterminer si c'est un fractionné
        is_frac    = any(kw in text for kw in ["4x", "3x", "2x", "en 4", "en 3",
                                                 "paiement reçu", "paiement programmé",
                                                 "versement", "1er paiement", "2e paiement",
                                                 "3e paiement", "4e paiement"])
        # Extraire marchand depuis le sujet
        merchant   = ""
        merch_m    = re.search(r"(?:pour|chez|à)\s+([A-Za-zÀ-ÿ0-9\s\.\-]{3,25})", m["subject"], re.IGNORECASE)
        if merch_m:
            merchant = merch_m.group(1).strip()[:20]

        # Clé de groupe : expéditeur + marchand + montant approximatif
        amount = m.get("amount_float", 0.0)
        # Arrondir pour regrouper les versements similaires
        amount_key = round(amount, 0) if amount > 0 else 0

        group_key = f"{m['sender_email']}|{merchant}|{amount_key}" if is_frac else None

        if group_key:
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(m)
        
        m["group_key"] = group_key
        m["merchant"]  = merchant

    # Enrichir chaque groupe avec les stats
    processed_keys = set()
    result_list    = []

    for m in enriched:
        gk = m.get("group_key")

        if gk and gk not in processed_keys:
            group_msgs = groups[gk]
            processed_keys.add(gk)

            # Compter versements payés vs programmés
            paid_msgs = [gm for gm in group_msgs
                         if any(kw in (gm["subject"]+gm["snippet"]).lower()
                                for kw in ["reçu", "confirmé", "autorisé", "payé", "received", "confirmed"])]
            prog_msgs = [gm for gm in group_msgs
                         if any(kw in (gm["subject"]+gm["snippet"]).lower()
                                for kw in ["programmé", "à venir", "scheduled", "upcoming", "prochain"])]

            amounts   = [gm.get("amount_float", 0.0) for gm in group_msgs if gm.get("amount_float", 0.0) > 0]
            avg_inst  = sum(amounts) / len(amounts) if amounts else 0

            # Détecter le nombre total de versements
            nb_total  = 4   # défaut
            for gm in group_msgs:
                txt = (gm["subject"] + " " + gm["snippet"]).lower()
                nm  = re.search(r"en\s+(\d+)[xX]|(\d+)[xX]\s+(?:de|sans)", txt)
                if nm:
                    nb_total = int(nm.group(1) or nm.group(2))
                    break

            nb_paid   = len(paid_msgs)
            paid_amt  = avg_inst * nb_paid
            total_amt = avg_inst * nb_total
            remaining = total_amt - paid_amt

            # Barre de progression
            pct      = int((nb_paid / nb_total) * 10) if nb_total > 0 else 0
            bar      = "█" * pct + "░" * (10 - pct)
            pct_str  = f"{int(nb_paid/nb_total*100)}%" if nb_total > 0 else "?"

            m["is_group_header"] = True
            m["group_msgs"]      = group_msgs
            m["nb_paid"]         = nb_paid
            m["nb_total"]        = nb_total
            m["paid_amount"]     = paid_amt
            m["total_amount"]    = total_amt
            m["remaining"]       = remaining
            m["progress_bar"]    = f"{bar} {pct_str} ({nb_paid}/{nb_total})"
            m["is_complete"]     = nb_paid >= nb_total
            result_list.append(m)

        elif not gk:
            m["is_group_header"] = False
            m["group_msgs"]      = []
            result_list.append(m)

    return result_list


def get_payment_emails(parsed):
    payments = [m for m in parsed if m.get("category") == "PAYMENT"]

    enriched = []
    for m in payments:
        text   = (m["subject"] + " " + m["snippet"]).lower()
        status, color, prio = get_payment_status(text)

        # Extraction du montant (float + string)
        amount_float = _parse_amount(m["subject"] + " " + m["snippet"])
        amount_str   = f"{amount_float:.2f}".replace(".", ",") if amount_float > 0 else ""

        # Extraction de la date d'échéance
        date_match = re.search(
            r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}|\d{1,2}\s+(?:jan|fév|mar|avr|mai|jun|jul|aoû|sep|oct|nov|déc|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*\d{4})",
            m["subject"] + " " + m["snippet"], re.IGNORECASE
        )
        due_date = date_match.group(0) if date_match else ""

        enriched.append({
            **m,
            "pay_status"  : status,
            "pay_color"   : color,
            "pay_priority": prio,
            "amount"      : amount_str,
            "amount_float": amount_float,
            "due_date"    : due_date,
        })

    # Regrouper les fractionnés
    enriched = _group_installments(enriched)

    return sorted(enriched, key=lambda x: (x["pay_priority"], -x["date"].timestamp()))



def _compute_credit_groups(enriched: list) -> dict:
    """
    Regroupe les paiements fractionnés en crédits cohérents.

    Logique en 3 étapes :
      1. Identifier les emails d'ACTIVATION (création du plan)
      2. Identifier les VERSEMENTS (payés / programmés)
      3. Associer les versements à leur crédit par montant unitaire
    """

    # ── Expéditeurs promos à ignorer ──────────────────────────────
    PROMO_BLACKLIST = [
        "croisiere", "croisières", "destockage", "déstockage",
        "vacances", "voyage prive", "voyageprive",
        "groupon", "veepee", "vente-privee", "newsletter",
    ]

    # ── Mots-clés de statut ───────────────────────────────────────
    INIT_KW  = [
        "est prêt", "is ready", "a été créé", "has been set up",
        "votre paiement en 4x est", "votre paiement en 3x est",
        "votre paiement en 2x est", "paiement en 4x sans frais de",
        "paiement en 3x sans frais de", "paiement en 2x sans frais de",
        "prêt à démarrer", "votre plan de paiement",
    ]
    PAID_KW  = [
        "confirmation", "confirmé", "autorisé", "a bien été",
        "payé", "reçu", "received", "1er paiement reçu",
        "2e paiement reçu", "3e paiement reçu", "4e paiement reçu",
        "2ème paiement", "3ème paiement", "nous avons reçu",
        "dernier paiement", "paiement reçu",
    ]
    SCHED_KW = [
        "programmé", "à venir", "approche", "sera prélevé",
        "upcoming", "scheduled", "prochaine échéance",
        "rappel", "reminder",
    ]

    # ── Produits connus ───────────────────────────────────────────
    KNOWN_PRODUCTS = [
        "EcoFlow", "iPhone", "Samsung", "MacBook", "iPad",
        "Temu", "Fnac", "Darty", "Boulanger", "Amazon",
        "Cdiscount", "Vistaprint", "AirPods", "PlayStation",
        "Xbox", "Nintendo", "Dyson", "Nespresso",
    ]

    groups = {}   # clé → dict du crédit

    for m in enriched:
        sender_low = (m["sender_name"] + " " + m["sender_email"]).lower()
        subj_orig  = m["subject"]
        subj_low   = (subj_orig + " " + m["snippet"]).lower()

        # ── 1. Exclure les promos ─────────────────────────────────
        if any(bl in sender_low for bl in PROMO_BLACKLIST):
            continue

        # ── 2. Détecter X fois ────────────────────────────────────
        nb_fois = None
        # Chercher "4X", "en 4 fois", "4 versements"
        xm = re.search(
            r"(\d+)\s*x\s+(?:sans frais|de\s+\d|€)|"
            r"en\s+(\d+)\s*(?:x|fois)|"
            r"(\d+)\s+fois\s+(?:de|sans)|"
            r"paiement\s+en\s+(\d+)",
            subj_low
        )
        if xm:
            nb_fois = int(next(g for g in xm.groups() if g))
        elif "4x" in subj_low: nb_fois = 4
        elif "3x" in subj_low: nb_fois = 3
        elif "2x" in subj_low: nb_fois = 2

        # Détecter depuis "Xe paiement reçu pour..." → nb_fois déduit à 4 par défaut
        ord_m = re.search(r"(\d+)(?:er|e|ème|eme)\s+paiement\s+re[çc]u", subj_low)
        if ord_m:
            current_num = int(ord_m.group(1))
            if not nb_fois:
                nb_fois = 4  # défaut PayPal/Klarna = 4x
        else:
            current_num = None

        if not nb_fois:
            continue

        # ── 3. Montant ────────────────────────────────────────────
        amt_str = m.get("amount", "")
        try:
            unit = float(amt_str.replace(",", ".")) if amt_str else 0.0
        except ValueError:
            unit = 0.0

        if unit <= 0:
            continue

        # ── 4. Statut de l'email ──────────────────────────────────
        is_init  = any(kw in subj_low for kw in INIT_KW)
        is_paid  = any(kw in subj_low for kw in PAID_KW)
        is_sched = any(kw in subj_low for kw in SCHED_KW)

        # Email d'activation : le montant = TOTAL du crédit
        if is_init:
            total_for_init = unit
            unit_for_init  = round(unit / nb_fois, 2)
        else:
            total_for_init = None
            unit_for_init  = unit

        # ── 5. Produit/service ────────────────────────────────────
        product = ""
        known_m = re.search(
            "(" + "|".join(KNOWN_PRODUCTS) + ")",
            subj_orig, re.IGNORECASE
        )
        if known_m:
            product = known_m.group(0)
        else:
            pm = re.search(
                r"(?:pour|chez|à)\s+([A-Za-zÀ-ÿ0-9][A-Za-zÀ-ÿ0-9\s\.\-]{2,22})",
                subj_orig, re.IGNORECASE
            )
            if pm:
                product = pm.group(1).strip()[:22]

        # ── 6. Clé de groupe ──────────────────────────────────────
        # Utiliser le montant UNITAIRE pour regrouper correctement
        # Email init → montant/nb_fois, sinon → montant tel quel
        key_unit   = unit_for_init if is_init else unit
        key_sender = m["sender_email"].split("@")[-1]  # domaine seulement
        group_key  = f"{key_sender}|{round(key_unit, 1)}"

        if group_key not in groups:
            groups[group_key] = {
                "sender"      : m["sender_name"] or m["sender_email"],
                "product"     : product,
                "nb_fois"     : nb_fois,
                "unit_amount" : key_unit,
                "total_estim" : round(key_unit * nb_fois, 2),
                "paid_count"  : 0,
                "paid_total"  : 0.0,
                "sched_count" : 0,
                "emails"      : [],
                "has_init"    : is_init,
            }
        g = groups[group_key]
        g["emails"].append(m)

        # Mise à jour produit
        if product and len(product) > len(g["product"]):
            g["product"] = product

        # Compter les versements selon statut
        if is_init:
            g["has_init"]    = True
            # Si email init : le total est connu avec certitude
            g["total_estim"] = total_for_init if total_for_init else g["total_estim"]
            g["unit_amount"] = unit_for_init
        elif is_paid:
            g["paid_count"] += 1
            g["paid_total"]  = round(g["paid_total"] + key_unit, 2)
        elif is_sched:
            g["sched_count"] += 1

    # ── 7. Calcul final du restant dû ─────────────────────────────
    for g in groups.values():
        g["remaining"]   = max(0.0, round(g["total_estim"] - g["paid_total"], 2))
        g["is_complete"] = g["paid_count"] >= g["nb_fois"]

    # ── 8. Filtrer les groupes incohérents ────────────────────────
    groups = {
        k: g for k, g in groups.items()
        if g["total_estim"] > 0
        and (g["paid_count"] > 0 or g["sched_count"] > 0 or g["has_init"])
    }

    return groups


def display_payment_summary(enriched: list):
    """Affiche le récapitulatif des crédits / paiements en X fois."""
    groups = _compute_credit_groups(enriched)
    if not groups:
        return

    console.print(Rule(
        "[bold magenta]💳 Récapitulatif Crédits & Paiements en X fois[/bold magenta]"
    ))

    t = Table(box=box.ROUNDED, show_lines=True)
    t.add_column("Expéditeur",   width=18, style="magenta",    no_wrap=True)
    t.add_column("Produit/Serv", width=20, style="cyan",       no_wrap=True)
    t.add_column("Échéances",    width=14, justify="center")
    t.add_column("Progression",  width=14, justify="center")
    t.add_column("Payé",         width=10, justify="right",    style="green")
    t.add_column("Total",        width=10, justify="right",    style="white")
    t.add_column("Restant dû",   width=11, justify="right")
    t.add_column("Statut",       width=12, justify="center")

    total_remaining = 0.0

    for g in sorted(groups.values(),
                    key=lambda x: (x["is_complete"], -x["remaining"])):
        nb    = g["nb_fois"]
        paid  = min(g["paid_count"], nb)

        # Barre de progression
        filled = int((paid / nb) * 10) if nb else 0
        bar    = (
            f"[green]{'█' * filled}[/green]"
            f"[dim]{'░' * (10 - filled)}[/dim]"
        )
        pct    = f"{int(paid/nb*100)}%" if nb else "?"

        # Couleur restant dû
        rem    = g["remaining"]
        if g["is_complete"]:
            rem_str = "[green]0.00 €[/green]"
        elif rem > 200:
            rem_str = f"[bold red]{rem:.2f} €[/bold red]"
        elif rem > 50:
            rem_str = f"[yellow]{rem:.2f} €[/yellow]"
        else:
            rem_str = f"{rem:.2f} €"

        # Note sur le total (si 0 versement payé → montant = total de l'échéance)
        total_note = ""
        if paid == 0:
            total_note = "[dim] (1 éch.)[/dim]"

        status = (
            "[green]✅ Soldé[/green]"
            if g["is_complete"]
            else f"[yellow]⏳ {nb - paid} restant(s)[/yellow]"
        )

        t.add_row(
            (g["sender"])[:17],
            (g["product"] or "—")[:19],
            f"{paid}/{nb}x  {g['unit_amount']:.2f}€",
            f"{bar} {pct}",
            f"{g['paid_total']:.2f} €",
            f"{g['total_estim']:.2f} €{total_note}",
            rem_str,
            status,
        )

        if not g["is_complete"]:
            total_remaining += rem

    console.print(t)

    if total_remaining > 0:
        console.print(
            f"  [bold red]💰 Total restant dû (crédits actifs) : "
            f"{total_remaining:.2f} €[/bold red]\n"
        )
    else:
        console.print("  [green]✅ Tous les crédits sont soldés ![/green]\n")


def _render_payments_table(payments: list, selected: set):
    """Tableau des paiements avec cases à cocher et affichage des fractionnés."""
    # ── Section 1 : Paiements fractionnés regroupés ───────────────────
    fractioned = [m for m in payments if m.get("is_group_header") and not m.get("is_complete")]
    completed  = [m for m in payments if m.get("is_group_header") and m.get("is_complete")]
    singles    = [m for m in payments if not m.get("is_group_header")]

    if fractioned:
        tf = Table(
            title="📊 Crédits & Paiements Fractionnés EN COURS",
            box=box.ROUNDED, show_lines=True, style="bold"
        )
        tf.add_column("Expéditeur",  width=18, style="magenta")
        tf.add_column("Marchand",    width=18, style="cyan")
        tf.add_column("Progression", width=22, style="yellow")
        tf.add_column("Payé",        width=10, style="bold green",  justify="right")
        tf.add_column("Reste",       width=10, style="bold red",    justify="right")
        tf.add_column("Total",       width=10, style="bold white",  justify="right")
        tf.add_column("Statut",      width=10)

        total_remaining = 0.0
        for m in fractioned:
            remaining = m.get("remaining", 0.0)
            total_remaining += remaining
            complete_label = "[green]✅ Soldé[/green]" if m.get("is_complete") else "[yellow]⏳ En cours[/yellow]"
            tf.add_row(
                (m["sender_name"] or m["sender_email"])[:17],
                m.get("merchant", "—")[:17],
                f"[yellow]{m.get('progress_bar','—')}[/yellow]",
                f"{m.get('paid_amount',0):.2f} €",
                f"[red]{remaining:.2f} €[/red]" if remaining > 0 else "—",
                f"{m.get('total_amount',0):.2f} €" if m.get("total_amount",0) > 0 else "—",
                complete_label,
            )

        console.print(tf)
        console.print(
            f"  [bold red]💸 Total restant à rembourser : {total_remaining:.2f} €[/bold red]\n"
        )

    if completed:
        console.print(f"  [dim]✅ {len(completed)} crédit(s)/fractionné(s) soldé(s) — archivables[/dim]\n")

    # ── Section 2 : Tous les emails avec numérotation + cases ────────
    t = Table(
        title=f"💳 Tous les emails Paiements ({len(payments)})  —  [cyan]?[/cyan]=aide",
        box=box.SIMPLE_HEAD, show_lines=False
    )
    t.add_column("#",          width=4,  justify="right", style="bold dim")
    t.add_column("✔",          width=3,  justify="center")
    t.add_column("Statut",     width=20)
    t.add_column("Date",       width=11, style="cyan")
    t.add_column("Expéditeur", width=18, style="magenta", no_wrap=True)
    t.add_column("Sujet",      width=38, style="white")
    t.add_column("Montant",    width=9,  style="bold green", justify="right")
    t.add_column("Progrès",    width=16, style="yellow")

    for i, m in enumerate(payments, 1):
        check = "[bold green]■[/bold green]" if i in selected else "[dim]□[/dim]"
        progress = ""
        if m.get("is_group_header") and m.get("total_amount", 0) > 0:
            progress = m.get("progress_bar", "")[:15]
        elif m.get("is_complete"):
            progress = "[green]✅ Soldé[/green]"

        t.add_row(
            str(i), check,
            f"[{m['pay_color']}]{m['pay_status']}[/{m['pay_color']}]",
            m["date"].strftime("%Y-%m-%d"),
            (m["sender_name"] or m["sender_email"])[:17],
            m["subject"][:37],
            m["amount"] + " €" if m["amount"] else "—",
            progress,
        )

    console.print(t)

    # Résumé
    late     = sum(1 for m in payments if "EN RETARD" in m.get("pay_status",""))
    upcoming = sum(1 for m in payments if "ÉCHÉANCE"  in m.get("pay_status",""))
    nb_sel   = len(selected)
    console.print(
        f"  [red]🔴 En retard : {late}[/red]   "
        f"[yellow]🟠 Échéances : {upcoming}[/yellow]   "
        f"[bold]Sélectionnés : [cyan]{nb_sel}/{len(payments)}[/cyan][/bold]\n"
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


def _verify_action(service, sample_id: str, action: str) -> bool:
    """
    Vérifie qu'une action a bien été appliquée sur un email test.
    Retourne True si OK, False si l'API a accepté mais n'a rien fait.
    """
    try:
        msg = service.users().messages().get(
            userId="me", id=sample_id, format="minimal"
        ).execute()
        labels = msg.get("labelIds", [])
        if action == "DELETE":
            # Doit avoir le label TRASH ou ne plus exister
            return "TRASH" in labels
        elif action == "ARCHIVE":
            # Ne doit plus avoir le label INBOX
            return "INBOX" not in labels
        elif action == "TRASH":
            return "TRASH" in labels
    except Exception:
        # 404 = message supprimé définitivement = succès batchDelete
        return True
    return False


def _execute_mail_action(service, emails: list, indices: set, action: str):
    """
    Supprime ou archive les emails dont l'index est dans `indices`.

    Stratégie de suppression (du plus sûr au plus définitif) :
      TRASH  → Corbeille Gmail  (récupérable 30j, fonctionne toujours)
      DELETE → Suppression définitive via batchDelete
      ARCHIVE→ Retrait du label INBOX (archivage)
    """
    targets = [emails[i-1] for i in sorted(indices) if 1 <= i <= len(emails)]
    if not targets:
        console.print("[yellow]⚠️  Aucun email sélectionné.[/yellow]")
        return

    verb  = ("mis à la corbeille" if action == "TRASH"
             else "supprimés définitivement" if action == "DELETE"
             else "archivés")
    icon  = ("🗑️ " if action in ("TRASH","DELETE") else "📁")
    color = ("red" if action in ("TRASH","DELETE") else "blue")

    console.print(Panel(
        f"[{color}]{icon} {action}[/{color}] — [bold]{len(targets)}[/bold] email(s) :\n" +
        "\n".join(f"  • {m['subject'][:65]}" for m in targets[:8]) +
        (f"\n  … et {len(targets)-8} autres" if len(targets) > 8 else ""),
        title="⚡ Confirmation", border_style=color
    ))

    if not Confirm.ask("[bold red]Confirmer ?[/bold red]", default=False):
        console.print("[dim]→ Annulé.[/dim]")
        return

    ids         = [m["id"] for m in targets]
    ok_count    = 0
    error_count = 0

    if action == "TRASH":
        # ── Méthode 1 : batchModify → ajouter label TRASH + retirer INBOX ──
        # Fonctionne en mode TEST et PRODUCTION
        for start in range(0, len(ids), 1000):
            batch = ids[start:start+1000]
            try:
                service.users().messages().batchModify(
                    userId="me",
                    body={
                        "ids"           : batch,
                        "addLabelIds"   : ["TRASH"],
                        "removeLabelIds": ["INBOX", "UNREAD"],
                    }
                ).execute()
                ok_count += len(batch)
            except Exception as e:
                console.print(f"[red]Erreur batch : {e}[/red]")
                error_count += len(batch)

        # ── Vérification sur 1 email sample ─────────────────────────────────
        if ids and ok_count > 0:
            verified = _verify_action(service, ids[0], "TRASH")
            if verified:
                console.print(f"[bold green]✅ {ok_count} email(s) mis à la corbeille.[/bold green]")
            else:
                console.print(
                    f"[yellow]⚠️  API a répondu OK mais la corbeille n'a pas changé.\n"
                    f"   Cause probable : scope Gmail insuffisant ou app en mode TEST.\n"
                    f"   → Voir section DIAGNOSTIC ci-dessous.[/yellow]"
                )
                _print_scope_diagnostic()

    elif action == "DELETE":
        # ── Méthode 2 : batchDelete → suppression définitive ────────────────
        # Nécessite scope https://mail.google.com/
        for start in range(0, len(ids), 1000):
            batch = ids[start:start+1000]
            try:
                service.users().messages().batchDelete(
                    userId="me", body={"ids": batch}
                ).execute()
                ok_count += len(batch)
            except Exception as e:
                console.print(f"[red]Erreur batchDelete : {e}[/red]")
                # Fallback automatique vers TRASH
                console.print("[yellow]→ Fallback vers mise à la corbeille...[/yellow]")
                try:
                    service.users().messages().batchModify(
                        userId="me",
                        body={"ids": batch, "addLabelIds": ["TRASH"],
                              "removeLabelIds": ["INBOX", "UNREAD"]}
                    ).execute()
                    console.print(f"[green]  ✅ {len(batch)} mis à la corbeille (fallback).[/green]")
                    ok_count += len(batch)
                except Exception as e2:
                    console.print(f"[red]  ❌ Fallback échoué : {e2}[/red]")
                    error_count += len(batch)
        if ok_count > 0:
            console.print(f"[bold green]✅ {ok_count} email(s) supprimés définitivement.[/bold green]")

    elif action == "ARCHIVE":
        # ── Méthode 3 : retrait label INBOX ──────────────────────────────────
        for start in range(0, len(ids), 1000):
            batch = ids[start:start+1000]
            try:
                service.users().messages().batchModify(
                    userId="me",
                    body={"ids": batch, "removeLabelIds": ["INBOX"]}
                ).execute()
                ok_count += len(batch)
            except Exception as e:
                console.print(f"[red]Erreur archivage : {e}[/red]")
                error_count += len(batch)

        if ids and ok_count > 0:
            verified = _verify_action(service, ids[0], "ARCHIVE")
            status = "[bold green]✅" if verified else "[yellow]⚠️ "
            console.print(f"{status} {ok_count} email(s) archivés.[/bold green]" if verified
                          else f"{status} {ok_count} archivés (non vérifié — vérifier dans Gmail).[/yellow]")

    if error_count:
        console.print(f"[red]❌ {error_count} email(s) en erreur.[/red]")


def _print_scope_diagnostic():
    """Affiche un guide de diagnostic quand les actions ne fonctionnent pas."""
    console.print(Panel(
        "[bold yellow]🔧 DIAGNOSTIC — Pourquoi les suppressions ne fonctionnent pas ?[/bold yellow]\n\n"
        "[bold]Cause 1 — Scope OAuth insuffisant[/bold]\n"
        "  → Supprimer [cyan]token.pickle[/cyan] et relancer le script\n"
        "  → Le script demandera à nouveau l'autorisation avec les bons scopes\n\n"
        "[bold]Cause 2 — App Google Cloud en mode TEST[/bold]\n"
        "  → console.cloud.google.com\n"
        "  → APIs & Services → Écran de consentement OAuth\n"
        "  → Changer le statut de [red]TEST[/red] → [green]PRODUCTION[/green]\n"
        "  → (Pas besoin de validation Google pour usage personnel)\n\n"
        "[bold]Cause 3 — Vérification manuelle[/bold]\n"
        "  → Ouvrir Gmail → Corbeille → vérifier si les emails y sont\n"
        "  → Si oui : tout fonctionne, ils seront supprimés dans 30 jours\n"
        "  → Ou vider la corbeille manuellement",
        border_style="yellow"
    ))


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
        display_payment_summary(payments)
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
            # Proposer TRASH (sûr) ou DELETE (définitif)
            mode = Prompt.ask(
                "  [yellow]Mode suppression[/yellow]",
                choices=["trash", "delete"],
                default="trash"
            )
            _execute_mail_action(service, payments, selected,
                                 "TRASH" if mode == "trash" else "DELETE")
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
    # Niveau 1 — Critiques (action immédiate requise)
    (["margin call", "appel de marge", "liquidation", "margin level",
      "force close", "dépôt requis", "deposit required", "stop out"],
     "🚨 CRITIQUE",      "bold red",    1),

    # Niveau 2 — Sécurité compte
    (["login", "connexion", "security", "sécurité", "2fa",
      "sign-in", "suspicious", "unauthorized"],
     "🔐 SÉCURITÉ",      "bold magenta", 2),

    # Niveau 3 — Ordres exécutés
    (["order filled", "order executed", "trade executed", "filled",
      "position fermée", "ordre exécuté",
      "ordre d'achat", "ordre de vente",
      "exécuté", "exécutée"],
     "⚡ ORDRE EXÉCUTÉ", "bold yellow", 3),

    # Niveau 4 — SL / TP
    (["stop loss", "take profit", "sl atteint", "tp atteint",
      "stop-loss", "take-profit"],
     "🎯 SL/TP",         "yellow",      4),

    # Niveau 5 — Transferts / dépôts
    (["deposit", "withdrawal", "dépôt", "retrait", "wire",
      "virement", "funding"],
     "💰 TRANSFERT",     "cyan",        5),

    # Niveau 6 — Signaux / alertes prix
    (["signal", "alert", "alerte", "new idea", "nouvelle idée",
      "price alert", "alerte de prix"],
     "💡 SIGNAL/IDÉE",   "blue",        6),

    # Niveau 7 — Rapports périodiques
    (["weekly", "monthly", "rapport", "report", "statement",
      "relevé", "summary"],
     "📊 RAPPORT",       "dim",         7),
]


def get_trading_status(text):
    for keywords, label, color, prio in TRADING_STATUS_RULES:
        if any(k in text for k in keywords):
            return label, color, prio
    return "📊 Info Trading", "white", 6



# ── Whitelist stricte des expéditeurs TRADING ────────────────────────
# Seuls ces domaines/noms peuvent apparaître dans le module Trading
TRADING_WHITELIST = {
    "kraken", "tradingview", "binance", "coinbase", "crypto.com",
    "coinhouse", "bitget", "bybit", "kucoin", "bitmex", "gate.io",
    "okx", "huobi", "degiro", "bourse direct", "interactive broker",
    "saxo", "ig.com", "trade republic", "etoro",
}

# Mots-clés de marketing/promo à exclure même dans les emails trading
TRADING_PROMO_BLACKLIST = [
    "inscrivez-vous", "terminez votre inscription",
    "gagnez jusqu", "pour chaque ami", "parrainage",
    "passez au trading", "dépensez vos cryptos",
    "sublimez", "rentabilisez", "transformez votre curiosité",
    "il vous reste", "plus que", "rejoindre notre",
    "nos astuces", "préparez vos impôts",
    "remboursement", "refund", "retour commande",
    "amazon", "temu", "fnac", "cdiscount",
    "jour de paie", "épargnez chaque semaine",
]

def get_trading_emails(parsed: list) -> list:
    """
    Retourne uniquement les emails de trading RÉELS :
    - Expéditeur dans TRADING_WHITELIST
    - Contenu non promotionnel
    - Filtre les remboursements Amazon, pubs Revolut, etc.
    """
    trades    = []
    for m in parsed:
        sender_low = (m["sender_name"] + " " + m["sender_email"]).lower()
        subj_low   = (m["subject"]     + " " + m["snippet"]).lower()

        # ── 1. Expéditeur doit être dans la whitelist ─────────────
        is_whitelisted = any(w in sender_low for w in TRADING_WHITELIST)
        if not is_whitelisted:
            continue

        # ── 2. Exclure le contenu promotionnel/marketing ──────────
        if any(bl in subj_low for bl in TRADING_PROMO_BLACKLIST):
            continue

        # ── 3. Déterminer le statut ───────────────────────────────
        text = subj_low
        status, color, prio = get_trading_status(text)

        # Extraction prix/montant
        price_m = re.search(
            r"(\d[\d\s]*[.,]\d{2})\s*(?:€|\$|USD|EUR|BTC|ETH|USDT|SOL)?",
            m["subject"] + " " + m["snippet"]
        )
        price = price_m.group(0).strip() if price_m else ""

        trades.append({
            **m,
            "tr_status"  : status,
            "tr_color"   : color,
            "tr_priority": prio,
            "price"      : price,
        })

    return sorted(trades, key=lambda x: (x["tr_priority"], -x["date"].timestamp()))


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
            mode = Prompt.ask(
                "  [yellow]Mode suppression[/yellow]",
                choices=["trash", "delete"],
                default="trash"
            )
            _execute_mail_action(service, trades, selected,
                                 "TRASH" if mode == "trash" else "DELETE")
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
    "TRADING"   : "📈",
    "PAYMENT"   : "💳",
    "DELIVERY"  : "📦",
    "BANQUE"    : "🏦",
    "SANTE"     : "🏥",
    "TELECOM"   : "📱",
    "ASSURANCE" : "🛡️",
    "PROMO"     : "📢",
    "NOTIF"     : "🔔",
    "ENERGIE"   : "⚡",
    "OTHER"     : "📧",
}

# Couleurs Rich associées
CATEGORY_COLORS = {
    "TRADING"   : "bold yellow",
    "PAYMENT"   : "bold magenta",
    "DELIVERY"  : "bold blue",
    "BANQUE"    : "bold cyan",
    "SANTE"     : "bold green",
    "TELECOM"   : "bold bright_blue",
    "ASSURANCE" : "bold bright_magenta",
    "PROMO"     : "dim",
    "NOTIF"     : "dim cyan",
    "ENERGIE"   : "bold bright_yellow",
    "OTHER"     : "white",
}

def _render_senders_table(sorted_s: list, selected: set, page: int, page_size: int = 25):
    """Affiche le tableau paginé des expéditeurs avec cases à cocher."""
    start_i = page * page_size
    end_i   = min(start_i + page_size, len(sorted_s))
    page_items = sorted_s[start_i:end_i]

    t = Table(
        title=f"📊 Expéditeurs — [{start_i+1}-{end_i}] sur {len(sorted_s)}  "
              f"(page {page+1}/{-(-len(sorted_s)//page_size)})  —  [cyan]?[/cyan]=aide",
        box=box.SIMPLE_HEAD, show_lines=False
    )
    t.add_column("#",          width=4,  justify="right", style="bold dim")
    t.add_column("✔",          width=3,  justify="center")
    t.add_column("Expéditeur", width=26, style="bold cyan")
    t.add_column("Domaine",    width=22, style="blue")
    t.add_column("Catégorie",  width=16)
    t.add_column("Total",      width=6,  justify="right", style="bold white")
    t.add_column("Non lus",    width=7,  justify="right")
    t.add_column("Fréq/sem",   width=8,  justify="right", style="yellow")
    t.add_column("Dernier",    width=11, style="green")

    for abs_i, s in enumerate(page_items, start=start_i+1):
        icon  = CATEGORY_ICONS.get(s["category"], "📧")
        color = CATEGORY_COLORS.get(s["category"], "white")
        check = "[bold green]■[/bold green]" if abs_i in selected else "[dim]□[/dim]"
        unread_str = f"[red]{s['unread']}[/red]" if s["unread"] > 0 else "0"
        t.add_row(
            str(abs_i), check,
            (s["name"] or s["email"])[:25],
            s["domain"][:21],
            f"[{color}]{icon} {s['category']}[/{color}]",
            str(s["count"]),
            unread_str,
            str(s["freq_per_week"]),
            s["last_date"].strftime("%Y-%m-%d"),
        )
    console.print(t)

    # Résumé stats par catégorie
    from collections import Counter
    cat_totals = {}
    for s in sorted_s:
        c = s["category"]
        if c not in cat_totals:
            cat_totals[c] = {"senders": 0, "emails": 0}
        cat_totals[c]["senders"] += 1
        cat_totals[c]["emails"]  += s["count"]

    parts = []
    for cat in ["TRADING","PAYMENT","DELIVERY","BANQUE","SANTE","TELECOM","ASSURANCE","PROMO","NOTIF","OTHER"]:
        if cat in cat_totals:
            icon  = CATEGORY_ICONS.get(cat, "📧")
            color = CATEGORY_COLORS.get(cat, "white")
            parts.append(f"[{color}]{icon}{cat_totals[cat]['emails']}[/{color}]")
    console.print("  " + "  ".join(parts) + f"   [bold]Sélectionnés: [cyan]{len(selected)}[/cyan][/bold]\n")


def _print_senders_help():
    h = Table(box=box.SIMPLE, show_header=False, padding=(0,1))
    h.add_column("Cmd",  style="bold cyan", width=22)
    h.add_column("Effet",style="white",     width=55)
    rows = [
        ("1,3,5  ou  2-8",    "Toggle sélection individuelle ou plage"),
        ("a  /  n",           "Tout sélectionner / désélectionner"),
        ("f CAT",             "Filtrer par catégorie  ex: f PROMO  f BANQUE"),
        ("n+  /  n-",         "Page suivante / précédente"),
        ("cat N NOUVELLE_CAT","Changer la catégorie de l'expéditeur N"),
        ("del",               "🗑️  Supprimer TOUS les emails des expéditeurs sélectionnés"),
        ("arc",               "📁 Archiver tous les emails des expéditeurs sélectionnés"),
        ("trash",             "🗑️  Mettre à la corbeille (recommandé)"),
        ("info N",            "Afficher les derniers sujets de l'expéditeur N"),
        ("q",                 "Retour au menu principal"),
        ("?",                 "Afficher cette aide"),
    ]
    for cmd, desc in rows:
        h.add_row(cmd, desc)
    console.print(Panel(h, title="💡 Aide — Gestion des Expéditeurs", border_style="cyan"))


def interactive_senders(service, sender_stats: dict):
    """Module expéditeurs interactif avec pagination, filtrage et actions."""
    all_senders = sorted(sender_stats.values(), key=lambda x: x["count"], reverse=True)
    display_list = list(all_senders)   # liste affichée (peut être filtrée)
    selected  = set()
    page      = 0
    PAGE_SIZE = 25
    active_filter = None

    ALL_CATS = list(CATEGORY_ICONS.keys())

    while True:
        console.clear()
        title = "[bold]📊 Gestion des Expéditeurs[/bold]"
        if active_filter:
            title += f"  [yellow]— Filtre: {active_filter}[/yellow]"
        console.rule(title)
        _render_senders_table(display_list, selected, page, PAGE_SIZE)

        console.print(
            "  [dim]Commandes :[/dim] "
            "[cyan]1,3[/cyan]=toggle  [cyan]2-5[/cyan]=plage  "
            "[cyan]a[/cyan]/[cyan]n[/cyan]=tout/rien  "
            "[cyan]f CAT[/cyan]=filtre  "
            "[cyan]n+[/cyan]/[cyan]n-[/cyan]=pages  "
            "[cyan]cat N CAT[/cyan]=recatégoriser  "
            "[cyan]del[/cyan]/[cyan]arc[/cyan]/[cyan]trash[/cyan]=actions  "
            "[cyan]info N[/cyan]=détails  "
            "[cyan]q[/cyan]=quitter  [cyan]?[/cyan]=aide"
        )
        raw = Prompt.ask("\n[bold yellow]>[/bold yellow]").strip()
        rl  = raw.lower()

        # ── Aide ────────────────────────────────────────────────────
        if rl == "?":
            _print_senders_help()
            Prompt.ask("[dim]Entrée pour continuer[/dim]")

        # ── Quitter ─────────────────────────────────────────────────
        elif rl in ("q", ""):
            break

        # ── Pagination ──────────────────────────────────────────────
        elif rl in ("n+", "next", ">"):
            max_page = max(0, (-(-len(display_list)//PAGE_SIZE)) - 1)
            page = min(page + 1, max_page)
        elif rl in ("n-", "prev", "<"):
            page = max(0, page - 1)

        # ── Tout / rien ─────────────────────────────────────────────
        elif rl == "a":
            selected = set(range(1, len(display_list) + 1))
        elif rl == "n":
            selected = set()

        # ── Filtre par catégorie : f PROMO ───────────────────────────
        elif rl.startswith("f "):
            cat_filter = raw[2:].strip().upper()
            if cat_filter == "ALL" or cat_filter == "":
                display_list  = list(all_senders)
                active_filter = None
                console.print("[green]→ Filtre retiré.[/green]")
            elif cat_filter in ALL_CATS:
                display_list  = [s for s in all_senders if s["category"] == cat_filter]
                active_filter = cat_filter
                selected      = set()
                page          = 0
                console.print(f"[green]→ {len(display_list)} expéditeur(s) dans {cat_filter}.[/green]")
            else:
                console.print(f"[red]Catégorie inconnue. Valides : {', '.join(ALL_CATS)}[/red]")
            Prompt.ask("[dim]Entrée pour continuer[/dim]")

        # ── Recatégoriser : cat N NOUVELLE_CAT ──────────────────────
        elif rl.startswith("cat "):
            parts = raw.split()
            if len(parts) == 3:
                try:
                    idx     = int(parts[1])
                    new_cat = parts[2].upper()
                    if 1 <= idx <= len(display_list) and new_cat in ALL_CATS:
                        old_cat = display_list[idx-1]["category"]
                        email   = display_list[idx-1]["email"]
                        # Mise à jour dans display_list ET all_senders
                        display_list[idx-1]["category"] = new_cat
                        for s in all_senders:
                            if s["email"] == email:
                                s["category"] = new_cat
                        # Mise à jour dans SENDER_DEFAULT pour cette session
                        SENDER_DEFAULT[email] = new_cat
                        console.print(
                            f"[green]✅ {display_list[idx-1]['name']} : "
                            f"{old_cat} → {new_cat}[/green]"
                        )
                    else:
                        console.print(f"[red]Index ou catégorie invalide. Cats: {', '.join(ALL_CATS)}[/red]")
                except ValueError:
                    console.print("[red]Format : cat N CATÉGORIE  (ex: cat 3 PAYMENT)[/red]")
            else:
                console.print("[red]Format : cat N CATÉGORIE  (ex: cat 5 DELIVERY)[/red]")
            Prompt.ask("[dim]Entrée pour continuer[/dim]")

        # ── Infos détaillées : info N ────────────────────────────────
        elif rl.startswith("info "):
            try:
                idx = int(raw.split()[1])
                if 1 <= idx <= len(display_list):
                    s = display_list[idx-1]
                    subjects_preview = "\n".join(
                        f"  • {subj[:70]}" for subj in s.get("subjects", [])[:10]
                    )
                    console.print(Panel(
                        f"[bold cyan]{s['name']}[/bold cyan]  —  [blue]{s['email']}[/blue]\n"
                        f"Catégorie : [{CATEGORY_COLORS.get(s['category'],'white')}]"
                        f"{CATEGORY_ICONS.get(s['category'],'')} {s['category']}[/{CATEGORY_COLORS.get(s['category'],'white')}]\n"
                        f"Total : [bold]{s['count']}[/bold] emails  |  "
                        f"Non lus : [red]{s['unread']}[/red]  |  "
                        f"Fréq : [yellow]{s['freq_per_week']}/sem[/yellow]\n"
                        f"Premier : {s.get('first_date', s['last_date']).strftime('%Y-%m-%d')}  →  "
                        f"Dernier : {s['last_date'].strftime('%Y-%m-%d')}\n\n"
                        f"[bold]Derniers sujets :[/bold]\n{subjects_preview}",
                        title=f"ℹ️  Détails expéditeur #{idx}",
                        border_style="cyan"
                    ))
                    Prompt.ask("[dim]Entrée pour continuer[/dim]")
            except (ValueError, IndexError):
                console.print("[red]Format : info N  (ex: info 3)[/red]")

        # ── Actions sur sélection ────────────────────────────────────
        elif rl in ("del", "arc", "trash"):
            if not selected:
                console.print("[yellow]⚠️  Aucun expéditeur sélectionné.[/yellow]")
                Prompt.ask("[dim]Entrée pour continuer[/dim]")
                continue

            # Construire la liste des emails à traiter
            target_senders = [display_list[i-1] for i in sorted(selected)
                              if 1 <= i <= len(display_list)]
            total_emails   = sum(s["count"] for s in target_senders)

            action_map = {"del": "DELETE", "arc": "ARCHIVE", "trash": "TRASH"}
            action     = action_map[rl]

            console.print(Panel(
                f"[bold]{action}[/bold] sur [bold]{len(target_senders)}[/bold] expéditeur(s) "
                f"— environ [bold yellow]{total_emails}[/bold yellow] emails :\n" +
                "\n".join(f"  • {s['name']} ({s['count']} emails)" for s in target_senders[:8]) +
                (f"\n  … et {len(target_senders)-8} autres" if len(target_senders) > 8 else ""),
                title="⚡ Confirmation", border_style="yellow"
            ))

            if not Confirm.ask("[bold red]Confirmer ?[/bold red]", default=False):
                console.print("[dim]→ Annulé.[/dim]")
                continue

            for s in target_senders:
                query  = f"from:{s['email']}"
                msgs   = get_messages(service, max_results=500, query=query)
                ids    = [m["id"] for m in msgs]
                if not ids:
                    continue
                for start in range(0, len(ids), 1000):
                    batch = ids[start:start+1000]
                    if action == "DELETE":
                        try:
                            service.users().messages().batchDelete(
                                userId="me", body={"ids": batch}).execute()
                        except Exception:
                            service.users().messages().batchModify(
                                userId="me",
                                body={"ids": batch,
                                      "addLabelIds": ["TRASH"],
                                      "removeLabelIds": ["INBOX","UNREAD"]}
                            ).execute()
                    elif action == "TRASH":
                        service.users().messages().batchModify(
                            userId="me",
                            body={"ids": batch,
                                  "addLabelIds": ["TRASH"],
                                  "removeLabelIds": ["INBOX","UNREAD"]}
                        ).execute()
                    elif action == "ARCHIVE":
                        service.users().messages().batchModify(
                            userId="me",
                            body={"ids": batch, "removeLabelIds": ["INBOX"]}
                        ).execute()
                console.print(f"  [green]✅ {s['name']} : {len(ids)} emails traités.[/green]")

            selected = set()
            Prompt.ask("[dim]Entrée pour continuer[/dim]")

        # ── Sélection numérique ──────────────────────────────────────
        else:
            import re as _re
            range_m = _re.match(r"^(\d+)-(\d+)$", rl)
            if range_m:
                a, b = int(range_m.group(1)), int(range_m.group(2))
                for idx in range(min(a,b), max(a,b)+1):
                    if 1 <= idx <= len(display_list):
                        if idx in selected: selected.discard(idx)
                        else:               selected.add(idx)
            elif _re.match(r"^[\d,\s]+$", rl):
                for token in _re.split(r"[,\s]+", rl):
                    if token.isdigit():
                        idx = int(token)
                        if 1 <= idx <= len(display_list):
                            if idx in selected: selected.discard(idx)
                            else:               selected.add(idx)
            else:
                console.print("[red]Commande inconnue. [bold]?[/bold] pour l'aide.[/red]")


def display_senders(sender_stats):
    """Alias — redirige vers le module interactif."""
    interactive_senders(None, sender_stats)


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
        f"[bold]Emails concernés :[/bold] [bold yellow]{total_sel}[/bold yellow]\n"
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
                        try:
                            service.users().messages().batchDelete(
                                userId="me", body={"ids": batch}).execute()
                        except Exception:
                            service.users().messages().batchModify(
                                userId="me",
                                body={"ids": batch,
                                      "addLabelIds"   : ["TRASH"],
                                      "removeLabelIds": ["INBOX","UNREAD"]}
                            ).execute()
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
║              Pascal Bey  ·  v2.7  ·  2026               ║
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
    nb_urgent_other = sum(1 for m in parsed
                          if m.get("category") == "OTHER" and m.get("is_unread"))
    overview_lines = []
    overview_map = [
        ("TRADING",   "bold yellow"),   ("PAYMENT",   "bold magenta"),
        ("DELIVERY",  "bold blue"),      ("BANQUE",    "bold cyan"),
        ("SANTE",     "bold green"),     ("TELECOM",   "bold bright_blue"),
        ("ASSURANCE", "bold bright_magenta"),
        ("PROMO",     "dim"),            ("NOTIF",     "dim cyan"),
    ]
    for cat, color in overview_map:
        n = cats.get(cat, 0)
        if n > 0:
            icon = CATEGORY_ICONS.get(cat, "📧")
            overview_lines.append(f"  {icon} {cat:<10}: [{color}]{n}[/{color}]")
    overview_lines.append(
        f"  📧 Autres     : {cats.get('OTHER',0)} "
        f"([bold red]{nb_urgent_other} non lus[/bold red])"
    )
    overview_lines.append(f"  👥 Expéditeurs uniques : {len(sender_stats)}")
    console.print(Panel(
        "\n".join(overview_lines),
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
            interactive_senders(service, sender_stats)
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
