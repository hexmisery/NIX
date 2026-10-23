# NIX

Desktop search for public profiles by username. Results appear as sites respond. NIX also collects new sites from public directories and links between servers.

![NIX searching for admin, filtering results and collecting sites](docs/demo.gif)

[Download for Windows](https://github.com/hexmisery/NIX/releases/latest) · [Watch the full demo](https://github.com/hexmisery/NIX/releases/latest/download/NIX-demo.mp4)

## What it does

- Search across 25,000 profile URL templates covering 23,666 hostnames in the bundled snapshot.
- Show confirmed, unverified and unavailable results, with a reason for each result.
- Filter by status, source and region. A region filter uses domain and language metadata; it cannot establish a person's location.
- Discover public sites, save progress and continue until stopped.
- Add your own site rules and transfer collected catalogs between installations.
- Import and check HTTP/SOCKS proxies. Choose direct access or one selected working proxy.
- Export results as JSON, CSV or HTML.
- Switch between English and Russian and adjust window transparency.

The catalog combines Maigret, Sherlock, WhatsMyName, NExfil, Social Analyzer, public forum directories, collected server metadata and FediDB. Blackbird uses WhatsMyName; a separate Blackbird executable is not bundled. Adult sources are available through the settings and are off by default.

## Windows

Download `NIX.exe` from Releases and run it. This is a standalone build; Python is not required. Microsoft Edge WebView2 Runtime is required. The executable is unsigned. SHA-256 checksums are included with each release.

Enter a username, choose a search size and press **Search**. **Quick** checks the first 100 sources; **Full catalog** checks all eligible sources. Higher connection counts help when requests are waiting on the network. They do not bypass website limits.

Open **Discovery**, select a region and press **Start** to collect sites. **Until stopped** repeats collection cycles and saves progress. Use **Sites** to manage rules and import or export catalogs.

Search history, collected sites, preferences and proxies are stored separately from the executable. Replacing the executable keeps that data. Share the catalog export when transferring sites; it excludes search history and proxy credentials.

## Run from source

Python 3.11 or newer:

```sh
python -m venv .venv
```

Activate the environment with `.venv\Scripts\activate` on Windows or `source .venv/bin/activate` on macOS/Linux, then:

```sh
python -m pip install -r requirements.txt
python run.py
```

Windows uses WebView2. macOS uses WebKit. Linux needs a GTK/WebKit backend; consult [pywebview's Linux installation instructions](https://pywebview.flowrl.com/guide/installation.html#linux). The published executable is tested on Windows; macOS and Linux require building from source and have not been validated for this release.

A limited command-line search:

```sh
python run.py --cli admin --full --region all --limit 20 --output results.json
```

No API keys or `.env` file are required. `NICKATLAS_DATA_DIR` optionally changes the local data directory.

## Checks and build

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
python build.py
```

The build writes the desktop application to `dist/`. Keep the complete output folder together. On Windows, `python build.py --onefile` creates a standalone executable in `standalone/`.

## Limits

A matching username does not prove that accounts belong to the same person. A **Confirmed** result means the site's response matched the available identity checks. It does not verify ownership. **Unverified** results need manual review. Login walls, CAPTCHAs, rate limits, changed page layouts and offline sites can prevent a result.

The bundled count is a count of URL templates, not a count of independent platforms or confirmed accounts. Federation servers contribute many entries. FediDB's snapshot is dated October 18, 2026; directory entries were normalized and deduplicated, not individually checked for every username. Discovery adds supported sites and cannot cover every website.

Use public pages within the sites' access rules. NIX does not bypass authentication or CAPTCHAs. Network requests are paced, private destination addresses are rejected, and blocked proxy requests do not silently fall back to a direct connection. Free proxies are third-party infrastructure; avoid sending credentials through them.

## License

NIX code is MIT licensed. Bundled datasets, fonts and libraries retain their own licenses; see [LICENSE.txt](LICENSE.txt) and [licenses/ATTRIBUTION.txt](licenses/ATTRIBUTION.txt). FediDB-derived data is CC BY 4.0. WhatsMyName is CC BY-SA 4.0. The Social Analyzer dataset retains AGPL-3.0 terms.

Author: [@hexmisery](https://github.com/hexmisery).
