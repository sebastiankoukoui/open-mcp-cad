# Open MCP CAD – Quick start

From the ZIP file to the first wall an AI draws in Cadwork. No IT
knowledge needed, about 20 minutes.

Open MCP CAD connects an AI program (for example ChatGPT or Claude) with
your open Cadwork. You write in plain words what you want, and the AI draws
it in Cadwork. It asks you before every change. (MCP is the name of the
bridge through which an AI program may operate another program.)

The plugin and the installer speak German. Their words are shown here in
**bold**, with the meaning in brackets where needed.

## 1. What you need

- A Windows PC with **Cadwork 3D 2026**.
- Internet during the installation.
- **An AI subscription** you may already have: ChatGPT (Plus or Pro) or
  Claude (Pro or Max). A subscription is a monthly fee with the provider.
  It also works without one, with a **key** – an access code from the
  provider's website; you then pay per request.

## 2. Install (one double-click)

1. Right-click the ZIP file → **Extract All …** → **Extract**.
2. **Close Cadwork.**
3. In the unzipped folder, double-click **1_INSTALLIEREN.cmd**.
   If Windows asks whether you really want to run the file: **Run** (or
   **More info** → **Run anyway**).
4. A black window appears and works for a few minutes. Answer its
   questions with **Enter** – that accepts the suggestion. If the PC is
   missing a component, it asks whether it may fetch it. This also works
   on company PCs without the Windows package manager winget: it then
   downloads it directly from the maker and checks its digital signature
   first.
5. At the end it asks for each AI program it found, for example «Open MCP
   CAD in Codex eintragen? [J/n]» (add Open MCP CAD to Codex?). **Enter**
   adds it there. It makes a backup copy first.
6. At the very bottom, under **Ergebnis** (result), each part is listed on
   its own. If it says «NICHT vollstaendig installiert» (not completely
   installed), the reasons are right above.

> Tip: if you set up an AI program later, simply double-click
> 1_INSTALLIEREN.cmd again. It only adds what is missing and changes
> nothing that is already right.

## 3. Connect Cadwork

1. Start Cadwork and open a file (a new, empty file is enough).
2. In the plugin menu, click **Open MCP CAD**.
3. The small **bar** of Open MCP CAD appears at the top right, above the
   drawing. When it says **Bereit** (ready), Cadwork is connected.

![The bar at the top right in Cadwork: connected and ready](bilder/monitor.png)

The buttons of the bar:

- **Speech bubble**: opens the chat below it. The dash on the far right
  turns it back into the bar.
- **Two arrows**: puts the window to the right of the drawing, as a
  column of its own. Click again to release it.
- **Trennen** (disconnect): disconnects Cadwork from the AI. Then an **×**
  appears on the right that closes the window. A click on **Open MCP CAD**
  in the plugin menu brings it back.

## 4. Choose one way

There are three ways to talk to the AI. **Take the way that matches the AI
subscription you already have.** If you have none yet: way B with the
Codex app is the most tested among colleagues.

### Way A: chat in the plugin with a Claude subscription

You write directly in Cadwork, in the chat of Open MCP CAD.

1. Set up Claude Code once: press the Windows key, type **PowerShell**,
   press Enter. A window for commands opens. Type (or copy) this line and
   press Enter:
   ```
   irm https://claude.ai/install.ps1 | iex
   ```
   It takes about a minute and needs no administrator rights. Then close
   the window, open a **new** one (again **PowerShell**) and type:
   ```
   claude
   ```
   On the first start the browser opens: sign in with your Claude account.
   Then close the window. If Windows does not know «claude» yet, use this
   line instead:
   ```
   ~\.local\bin\claude.exe
   ```
   Only if the first line does not work (for example because a company
   computer blocks it): Claude Code can also be set up with Node.js, with
   `winget install OpenJS.NodeJS.LTS` and then, in a new window,
   `npm install -g @anthropic-ai/claude-code`. If winget is missing,
   install Node.js (version «LTS») from [nodejs.org](https://nodejs.org).
2. In Cadwork, click the **speech bubble** in the bar. The chat opens
   below it.
3. At the top left of the chat, click **Ordner wählen** (choose
   folder) and pick a project folder (not the whole drive). Claude may
   read in it.
4. Write the test sentence at the bottom (see section 5) and press Enter.

![The chat below the bar: you write at the bottom, the AI answers and draws](bilder/chat.png)

### Way B: Codex app with a ChatGPT subscription

You write in the Codex app from OpenAI, Cadwork draws.

1. Install the app **Codex** from the **Microsoft Store**, start it and
   sign in with your ChatGPT account.
2. Double-click **1_INSTALLIEREN.cmd** (again) and confirm «Open MCP CAD
   in Codex eintragen?» with **Enter**.
3. Close the Codex app completely and start it again.
4. In Cadwork, click **Open MCP CAD** (the bar shows **Bereit**).
5. Start a new chat in the Codex app and write the test sentence. If
   Codex asks whether it may use Open MCP CAD: allow it.

### Way C: Claude Desktop or Claude Code with a Claude subscription

You write in the Claude app (or in the command window), Cadwork draws.

1. Install **Claude Desktop** from claude.ai/download, start it and sign
   in.
2. Quit Claude Desktop completely (also at the bottom right next to the
   clock: right-click the Claude icon → **Quit**) before you start the
   installer.
3. Double-click **1_INSTALLIEREN.cmd** (again) and confirm «Open MCP CAD
   in Claude Desktop eintragen?» with **Enter**.
4. Start Claude Desktop again. In Cadwork, click **Open MCP CAD** (the
   bar shows **Bereit**).
5. Write the test sentence in Claude. If Claude asks whether it may use
   Open MCP CAD: allow it.

It also works with **Claude Code** (way A, step 1) in the command window:
the installer adds Open MCP CAD there as well. Type **claude** in a
project folder and write the test sentence.

## 5. The first test

Write to the AI:

> Draw a wall 4 m long, 2.5 m high

The AI first looks into the open Cadwork model. Before drawing, it asks
you (in the plugin chat with **Erlauben** / **Ablehnen**, allow / decline).
While it works, a small display above Cadwork shows what it is doing, for
example **KI zeichnet** (AI is drawing). After you allow it, the wall is in
Cadwork. Then you can keep talking, for
example "Make it 20 cm thick" or "Put a window in the middle".

## 6. If it does not work

- **Clicking Open MCP CAD does nothing:** the reason is in the file
  `C:\Users\Public\OpenMcpCad_start.log`.
- **The AI does not know Cadwork:** quit the AI program completely and
  start it again. If that does not help, double-click 1_INSTALLIEREN.cmd
  again and confirm the entry with Enter.
- **The AI says Cadwork cannot be reached:** in Cadwork, click **Open MCP
  CAD** and wait until the bar shows **Bereit**.
- **The plugin chat says «Womit möchtest du chatten?»** (what do you want
  to chat with?): choose the way that matches your subscription; the
  buttons show the next step.
- **If you ask an AI for help** (for example «install this»): give it
  the file `Programmdateien\FUER_KI_ASSISTENTEN.md`. It says what the AI
  should do. If it wants to build something extra first (such as an
  «adapter»): not needed, everything is already there.
- **Otherwise:** write to us at
  [github.com/sebastiankoukoui/open-mcp-cad/issues](https://github.com/sebastiankoukoui/open-mcp-cad/issues)
  or via [lignoai.ch](https://lignoai.ch). Attach the file
  `C:\Users\Public\OpenMcpCad_start.log` and a screenshot of the
  installer's **Ergebnis** (result).

![First contact in the plugin chat, as long as nothing is set up yet](bilder/willkommen.png)

More (all settings, uninstalling): the detailed guide in the folder
Programmdateien.
