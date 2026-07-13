# How to Open HTML Files on Windows

This guide shows every way to open `frontend.html` (or any local HTML file) in your browser.

## Method 1 — Double-click
1. Find `frontend.html` in File Explorer.
2. Double-click it.
3. It opens in your default browser.

> If it downloads instead of opening, use Method 4 or 5.

## Method 2 — Right-click > Open with
1. Right-click `frontend.html`.
2. Select **Open with**.
3. Choose **Microsoft Edge**, **Chrome**, or **Firefox**.

## Method 3 — Drag into browser
1. Open your browser (Chrome, Edge, etc.).
2. Drag the `frontend.html` file from File Explorer into the browser window.

## Method 4 — Open with Chrome via command line
1. Open PowerShell or Command Prompt.
2. Run:
   ```powershell
   cd C:/Users/arpit/Downloads/revenue-readiness-scorer
   start chrome frontend.html
   ```

For Edge:
```powershell
start msedge frontend.html
```

For Firefox:
```powershell
start firefox frontend.html
```

## Method 5 — Serve via local HTTP server
Best if the file opens but the API calls fail due to `file://` restrictions.

1. Open PowerShell.
2. Run:
   ```powershell
   cd C:/Users/arpit/Downloads/revenue-readiness-scorer
   python -m http.server 3000
   ```
3. In your browser go to:
   ```
   http://localhost:3000/frontend.html
   ```
4. To stop the server later, press `Ctrl + C` in the PowerShell window.

## Quick checklist before scanning
1. Start the API server:
   ```powershell
   cd C:/Users/arpit/Downloads/revenue-readiness-scorer
   python start.py
   ```
2. Open `frontend.html` using one of the methods above.
3. Enter a URL and email, then click **Get My Score**.
