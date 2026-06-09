Here is a comprehensive, ready-to-use `README.md` for your Discord bot. It covers installation, configuration, usage, and security best practices.

---

# 🚀 EVE Killmail Analyzer Discord Bot

A specialized Discord bot Cog designed for EVE Online players. It analyzes screenshots or text inputs to identify a solar system, calculates a 7-jump radius, fetches recent killmail data, and generates strictly formatted, length-limited clickable system links for in-game chat.

## ✨ Features

* **Dual Input Modes**: 
  * **Text**: Type a single system name (e.g., `Jita`) for instant lookup.
  * **Image**: Upload a screenshot of the in-game system name. The bot crops, applies a 90% brightness threshold, and runs OCR to identify the system.
* **Visual Feedback**: Returns the processed, thresholded image to Discord so you can verify exactly what the OCR engine "saw".
* **7-Jump Radius Calculation**: Uses a Breadth-First Search (BFS) graph traversal to find all valid systems within 7 jumps of the target.
* **Live Killmail Aggregation**: Fetches the last 15 days of killmail data from `echoes.mobi` and aggregates total ISK value per system in the radius.
* **Strict EVE Chat Formatting**: Outputs results as clickable EVE chat links (`<loc s="ID" t="system" sj="1">`). Automatically chunks results to strictly adhere to Discord/EVE message length limits (max 128 characters per message, up to 3 messages).
* **100% Proxy Routed**: All network traffic (Discord API, image downloads, and external API calls) is routed through a configurable local proxy.
* **Zero Hardcoded Secrets**: All sensitive configuration is managed strictly via environment variables.

---

## 📋 Prerequisites

1. **Python 3.8+** installed on your system.
 the Tesseract OCR engine installed on your host machine:
   * **Windows**: Download the installer from [UB-Mannheim Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and ensure it is added to your system `PATH`.
   * **Linux (Ubuntu/Debian)**: `sudo apt install tesseract-ocr`
   * **macOS**: `brew install tesseract`
3. A valid `systems.json` file containing EVE Online map data (ID, Name, Neighbors).


