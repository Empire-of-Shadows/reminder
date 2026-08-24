<div align="center">

# Imperial Reminder

**Automated server bump tracker and reminder bot for Empire of Shadows**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://python.org)
[![discord.py](https://img.shields.io/badge/discord.py-2.7-5865F2?logo=discord&logoColor=white)](https://github.com/Rapptz/discord.py)
[![MongoDB](https://img.shields.io/badge/MongoDB-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)](https://docs.docker.com/compose/)

Tracks successful server bumps across every major listing platform and sends timely reminders the moment each cooldown expires - so your server stays visible without anyone watching the clock.

</div>

---

## ✨ Features

### 🎯 Multi-Platform Bump Tracking

Detects and tracks successful bumps across all major Discord server listing services:

| Platform | Default Cooldown | Shorter Option |
|---|---|---|
| **Disboard** | 2 hours | - |
| **BumpIt** | 1 hour | - |
| **Bump4You** | 2 hours | - |
| **WeBump** | 2 hours | - |
| **OneBump** | 2 hours | 30 minutes |
| **Unfocused** | 2 hours | 90 minutes |

### 🔔 Smart Reminders
- Recognizes successful bump messages instantly across all supported platforms
- Sends reminders exactly when each platform's cooldown expires
- Configurable role mentions to notify your bump team
- Batches multiple ready-to-bump notifications to reduce spam

### 🧠 Intelligent Detection

The bot uses a **four-layer detection system** to catch bump success messages reliably - Discord's event delivery is inconsistent for webhook messages:

1. Real-time `on_message` monitoring
2. Message edit tracking (`on_message_edit`) for async embed population
3. Raw gateway event parsing for webhook messages
4. Force-refetch with retries for platforms with delayed embeds (e.g. WeBump)

### 📊 Live Timer Display

- Real-time status embed showing all bump cooldowns and remaining times
- Visual indicators for which platforms are ready to bump
- Auto-updates as cooldowns expire

### ⚙️ Configurable Per Server
- Separate channels for bump commands and live timer display
- Custom reminder messages with `{bump_role}` and `{bots}` placeholders
- Per-bot cooldown overrides
- Toggle individual bump platforms on or off

### 🆓 100% Free
Every feature - custom reminder wording and the shorter cooldown options included - is
available to every server at no cost. There is no premium tier.

### ⚙️ Admin Panel
> `/admin panel` - unified guild configuration (Discord Components v2). Sections: **Core Setup** (bump channel, bump role, timers channel), **Bump Bots** (which platforms to track and their cooldowns), **Messages** (custom reminder text and live timer toggle), and **Panel Access Roles**.

---

## 🔧 Tech Stack

| Layer | Technology |
|---|---|
| **Runtime** | Python 3.10+ |
| **Discord** | discord.py 2.7 |
| **Database** | MongoDB · pymongo (async) |
| **Dashboard** | FastAPI · React 19 · Vite · TypeScript |
| **Timer System** | Monotonic scheduling with jitter, exponential backoff, and graceful restart persistence |
| **Admin Panel** | Discord Components v2 (vendored `admin_engine`) |
| **Storage** | Vendored `storage_engine` |
| **Deployment** | Docker Compose · `obsidian_grid` network |

---

<div align="center">
<sub>Part of the **Empire of Shadows** ecosystem · `Informatinal/ImperialReminder`</sub>
</div>
