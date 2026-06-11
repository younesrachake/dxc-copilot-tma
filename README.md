# DXC Copilot — TMA Platform

> Enterprise-grade AI assistant platform for DXC Technology infrastructure teams.
> Built with **Angular 17**, served via **Nginx**, containerised with **Docker**, deployed via **GitHub Actions**.

[![CI/CD](https://github.com/dxc/dxc-copilot-tma/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/dxc/dxc-copilot-tma/actions/workflows/ci-cd.yml)
[![Security Scan](https://github.com/dxc/dxc-copilot-tma/actions/workflows/security-scan.yml/badge.svg)](https://github.com/dxc/dxc-copilot-tma/actions/workflows/security-scan.yml)
[![Docker Image](https://ghcr.io/dxc/dxc-copilot-tma/badges/latest)](https://ghcr.io/dxc/dxc-copilot-tma)

---

## 🚀 Démarrage rapide

### Option A — Local (Node.js)

```bash
# Prérequis: Node.js 20+
npm install
npm start          # → http://localhost:4200
```

### Option B — Docker (production)

```bash
cp .env.example .env          # fill in your secrets
docker compose up -d          # app + postgres + redis
# → http://localhost
```

### Option C — Docker dev (hot-reload)

```bash
docker compose -f docker-compose.dev.yml up
# → http://localhost:4200 with live reload
```

## 📁 Structure du projet

```
src/
├── app/
│   ├── admin-dashboard/     # Tableau de bord administration
│   ├── chat/                # Interface de chat
│   ├── document-viewer/     # Visionneuse de documents
│   ├── layout/              # Layout principal (sidebar)
│   ├── login/               # Page de connexion
│   ├── settings/            # Page de paramètres
│   ├── app.component.ts     # Composant racine
│   ├── app.config.ts        # Configuration Angular
│   └── app.routes.ts        # Configuration du routage
├── assets/
│   └── images/
│       └── dxc-logo.png     # Logo DXC
└── styles.scss              # Styles globaux et design system
```

## 🎨 Design System DXC

Le projet utilise un design system complet avec :

### Variables CSS
- `--dxc-purple`: #5F259F (couleur principale)
- `--dxc-purple-light`: #7A3BBD (variante claire)
- `--dxc-black`: #000000
- `--dxc-dark-gray`: #1A1A1A
- `--dxc-medium-gray`: #4B5563
- `--dxc-light-gray`: #F9FAFB
- `--dxc-white`: #FFFFFF
- `--dxc-success`: #10B981
- `--dxc-danger`: #EF4444

### Composants réutilisables
- Boutons (btn-primary, btn-outline, btn-sso)
- Champs de formulaire (input-group)
- Navigation (nav-list, nav-item)
- Layouts (sidebar, main-content)

## 🧭 Navigation

### Routes configurées

- `/` → Redirection vers `/login`
- `/login` → Page de connexion (sans layout)
- `/chat` → Interface de chat (avec layout)
- `/settings` → Paramètres (avec layout)
- `/admin` → Administration (avec layout)
- `/viewer` → Visionneuse de documents (avec layout)

### Structure du routing

Les pages internes (`chat`, `settings`, `admin`, `viewer`) utilisent le **Layout component** comme coquille avec :
- Sidebar navigation
- Zone principale pour le contenu
- Design responsive

## 📱 Composants

### Login
- Page de connexion avec animations futuristes
- Formulaire email/mot de passe
- Connexion SSO
- Arrière-plan dynamique avec grille 3D

### Layout
- Sidebar avec navigation
- Historique des chats
- Menu responsive mobile
- Branding DXC

### Chat
- Interface de conversation
- Saisie de message avec textarea
- Indicateur de frappe
- Avatars et timestamps

### Settings
- Navigation par onglets
- Profil utilisateur
- Préférences
- Sécurité
- Configuration API

### AdminDashboard
- Statistiques en temps réel
- Activité récente
- Actions rapides
- Interface d'administration

### DocumentViewer
- Visionneuse de documents
- Contrôles de zoom
- Navigation entre pages
- Toolbar avec actions

## 🛠 Technologies

- **Angular 17+** avec Standalone Components
- **TypeScript** pour le typage fort
- **SCSS** pour les styles
- **Angular Router** pour la navigation
- **Angular Forms** pour les formulaires

## 🎯 Fonctionnalités

- ✅ Design system DXC complet
- ✅ Layout responsive avec sidebar
- ✅ Navigation entre pages
- ✅ Composants réutilisables
- ✅ Animations et transitions
- ✅ Support mobile
- ✅ Architecture modulaire

## 📝 Notes de développement

### Architecture
- Utilisation des **Standalone Components** (Angular 17+)
- **Lazy loading** des composants via les routes
- **SCSS** pour les styles avec variables globales
- **Design system** centralisé dans `styles.scss`

### Prochaines étapes
- Intégration avec une API backend
- Gestion de l'authentification réelle
- Service de chat avec WebSocket
- Gestion des documents et uploads
- Tests unitaires et E2E

## 🤝 Contributeurs

Projet développé pour DXC Technology - TMA

---

**DXC Copilot TMA** © 2024
