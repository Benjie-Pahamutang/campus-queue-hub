# Campus Queue Hub 🎓🎫

A professional desktop queue management application built for campus administration offices, student services, and registrar kiosks. Features a modern CustomTkinter user interface, automated SQLite database tracking, real-time logging, and Arduino hardware buzzer integration.

---

## ✨ Features

* **Interactive GUI:** Modern UI powered by CustomTkinter for seamless ticket creation and status display.
* **Hardware Alert System:** Integrated Arduino C++ code (`buzzeer.ino`) triggering physical alerts/buzzers when calling numbers.
* **Authentication & Authorization:** Secure login system (`login.py`) for administrative controls.
* **Database Management:** Lightweight, persistent SQLite database operations (`database.py`).
* **Easy Distribution:** Bundled into a native Windows executable with an Inno Setup wizard (`CampusQueueSetup.exe`).

---

## 🛠️ Built With

* **Language:** Python 3.14
* **GUI Library:** CustomTkinter / Tkinter
* **Hardware:** Arduino (C++ Sketch)
* **Packaging:** PyInstaller & Inno Setup 6

---

## 🚀 Quick Start & Installation

### Option 1: Standalone Installer (Recommended for Users)
1. Go to the **[Releases](https://github.com/Benjie-Pahamutang/campus-queue-hub/releases)** section on the right sidebar of this repository.
2. Download **`CampusQueueSetup.exe`**.
3. Run the installer and follow the setup wizard to create a desktop shortcut.

### Option 2: Running from Source
1. **Clone the repository:**
   ```bash
   git clone [https://github.com/Benjie-Pahamutang/campus-queue-hub.git](https://github.com/Benjie-Pahamutang/campus-queue-hub.git)
   cd campus-queue-hub
