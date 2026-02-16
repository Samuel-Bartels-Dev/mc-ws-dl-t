manga_downloader/              ← Your project root (also your Git repo)
│
├── env/                       ← Python virtual environment (auto-created)
│
├── main.py                    ← Entry point for the application (starts CLI or GUI)
│
├── requirements.txt           ← List of all dependencies (generated with `pip freeze > requirements.txt`)
│
├── README.md                  ← Project overview and instructions
│
├── modules/                   ← Core functionality, broken into modules
│   ├── __init__.py            ← Makes this a package
│   ├── scraper.py             ← Handles fetching HTML (static or dynamic)
│   ├── parser.py              ← Extracts title, chapters, and image URLs
│   ├── downloader.py          ← Downloads images from URLs
│   ├── organizer.py           ← Manages folder creation and naming
│
├── gui/                       ← GUI-related files (will grow later with PyQt)
│   ├── __init__.py
│   ├── main_window.py         ← PyQt main window setup
│   └── widgets/               ← Optional: custom widgets for PyQt
│
├── assets/                    ← Optional: icons, logos, etc. for GUI
│
├── utils/                     ← Helper utilities (e.g., logging, file ops)
│   ├── __init__.py
│   └── logger.py              ← Custom logging wrapper
│
├── tests/                     ← Unit tests and test data
│   ├── test_scraper.py
│   ├── test_parser.py
│   └── ...
│
└── logs/                      ← Runtime logs (auto-created if needed)