# Build Log

A running record of what was built, what broke, and how it was fixed.

---

## Step 0: Project setup (2026-10-17)

**What we did**
- Chose the project location `C:\Users\hrzai\Documents\company-analyzer`, outside OneDrive.
  Syncing tools and coding projects clash: thousands of small, changing files, plus Git's
  history. GitHub serves as the backup instead.
- Created a virtual environment (`.venv`), a private package folder for this project only,
  and installed streamlit, requests, pandas, plotly, beautifulsoup4, anthropic and pytest.
  Exact versions are pinned in `requirements.txt` so the project installs the same way later.
- Started Git with a `.gitignore` written **before** the first commit, so the secrets file,
  downloaded data and `.venv` can never be uploaded by accident.
- Set this project's commit email to the GitHub "noreply" address, so commits link to the
  GitHub profile without publishing a personal email.
- Stored the SEC contact (User-Agent) and the Anthropic API key in `.streamlit/secrets.toml`
  (private), with a blank `secrets.toml.example` template for anyone cloning the repo.
- Built a starter `app.py` that confirms each secret is present **without displaying it**.
- Chose Claude Opus 5.5 for the question box: accuracy and careful citation matter more than
  the per-question cost for a personal tool.

**What broke / how we fixed it**
- **API key format confusion.** The Console's default key type ("linked to your account")
  starts with `sk-ant-usr-`, not the older `sk-ant-api` style. Both are valid; we confirmed
  the key with a free "list models" request. The first key was accidentally pasted into a
  chat, so it was deleted and replaced. Rule: keys go only in `secrets.toml`.
- **First GitHub push failed** ("Invalid username or token"). Git's sign-in window can't
  open from a background process. Fix: run `git push` in a visible terminal so the GitHub
  browser sign-in can appear.

---

## Step 1: Ticker lookup (2026-10-17)

**What we did**
- Added `analyzer/edgar_client.py`, the only file that contacts the SEC. It:
  - converts a ticker to the SEC's company ID (CIK) using the SEC's official ticker list
  - fetches the company's "submissions" record for industry, exchange, fiscal year end
    and filer category
  - sends the User-Agent on every request, waits 0.15s between requests (the SEC allows
    10 per second), and saves downloads to `data/cache/` (ticker list refreshed daily,
    company records every 6 hours)
  - turns technical failures (no internet, SEC refusal, unknown ticker) into plain-English
    messages
- The dashboard now has a ticker box (default AXP) and a company card.
- Added 15 automated tests (`tests/test_edgar_client.py`) that run without internet.

**Things learned about EDGAR**
- The SEC writes share classes with a dash (`BRK-B`), so the app converts `BRK.B` to `BRK-B`.
- CIKs must be padded to 10 digits in SEC web addresses (`4962` → `0000004962`).
- The SEC classifies AmEx as "Finance Services" (SIC 6199). We'll use this code later to
  decide which metrics to highlight for banks versus other companies.

**What broke / how we fixed it**
- **Berkshire showed "NYSE, NYSE".** The SEC lists the exchange once per share class.
  Fix: remove repeats while keeping the order.
