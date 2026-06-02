# 🧠 GmailMind — Gmail Smart Manager

> **Gérez votre boîte Gmail intelligemment depuis le terminal — 100% console, 100% couleurs.**
>
> Développé par Pascal Bey · Premier Tech · 2026

---

## ✨ Fonctionnalités

| Module | Description |
|--------|-------------|
| 🔴 **Urgents** | Scoring 0-100, filtrage des faux positifs (promos exclues) |
| 💳 **Paiements** | PayPal, Klarna, Cofidis, Oney — statuts, montants, échéances |
| 📈 **Trading** | Kraken, TradingView — Margin Call 🚨, ordres, signaux |
| 📦 **Livraisons** | 10+ transporteurs, numéros de tracking extraits |
| 📊 **Expéditeurs** | Stats volume / fréquence / catégorie sur 500 emails |
| 🧹 **Nettoyage** | Éditeur interactif : sélection, changement d'action, exécution |

### 🎮 Mode interactif console (tous les modules)
- `1,3,5` ou `2-6` → sélection individuelle ou par plage
- `a` / `n` → tout sélectionner / désélectionner
- `s STATUT` → filtrer par mot-clé (ex: `s retard`, `s critique`)
- `del` → 🗑️ Supprimer les sélectionnés
- `arc` → 📁 Archiver les sélectionnés
- `t N TYPE` → changer l'action d'une ligne (nettoyage)
- `go` → exécuter le plan de nettoyage
- `?` → aide contextuelle

---

## ⚙️ Installation

### 1. Cloner le repo
```bash
git clone https://github.com/VOTRE_USERNAME/GmailMind.git
cd GmailMind
```

### 2. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 3. Configurer Google Cloud Console

1. Aller sur https://console.cloud.google.com
2. **Créer un projet** → APIs & Services → Activer **Gmail API**
3. Identifiants → **Créer ID client OAuth 2.0** → Type : *Application de bureau*
4. Télécharger le JSON → renommer en **`credentials.json`**
5. Placer dans le dossier du projet
6. Dans **Écran de consentement OAuth** → Utilisateurs test → ajouter votre email

### 4. Lancer
```bash
python gmail_smart_manager.py
```

> Au 1er lancement, un navigateur s'ouvre pour autoriser l'accès.
> Le token est sauvegardé dans `token.pickle` pour les prochaines fois.

---

## 📁 Structure du projet

```
GmailMind/
├── gmail_smart_manager.py   # Script principal
├── requirements.txt          # Dépendances Python
├── README.md                 # Ce fichier
├── credentials.json          # ⚠️ À ne PAS committer (dans .gitignore)
└── token.pickle              # ⚠️ Généré automatiquement (dans .gitignore)
```

---

## 🔒 Sécurité

> ⚠️ **Ne jamais committer `credentials.json` ni `token.pickle`** — ils donnent accès à votre Gmail.

Ces fichiers sont déjà dans le `.gitignore` fourni.

---

## 🗺️ Roadmap

- [ ] Intégration **Mistral Local** (via Ollama) pour analyse sémantique
- [ ] Résumé IA des emails urgents
- [ ] Brouillons de réponse générés par l'IA
- [ ] Export rapport PDF / CSV
- [ ] Mode `--auto` pour nettoyage planifié

---

## 📦 Dépendances

```
google-auth>=2.20.0
google-auth-oauthlib>=1.0.0
google-auth-httplib2>=0.1.0
google-api-python-client>=2.90.0
rich>=13.5.0
```

---

*GmailMind — Premier Tech Edition · Pascal Bey · 2026*
