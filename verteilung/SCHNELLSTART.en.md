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
- **An AI app with a subscription:** Claude Desktop (with a Claude
  subscription, Pro or Max) or the ChatGPT app from OpenAI (with a ChatGPT
  subscription, Plus or Pro). A subscription is a monthly fee with the
  provider. It only works with the app on the PC, not in the browser or
  on the phone. It also works without
  a subscription, with a **key** – an access code from the provider's
  website; you then pay per request (see «For advanced users» in
  section 6).

## 2. Install (one double-click)

Section 6 shows these steps in pictures.

1. Right-click the ZIP file → **Extract All …** → **Extract**.
2. **Close Cadwork.**
3. In the unzipped folder, double-click **1_INSTALLIEREN.cmd**.
   If Windows asks whether you really want to run the file: **Run** (or
   **More info** → **Run anyway**).
4. The window «Open MCP CAD einrichten» (set up Open MCP CAD) opens. It
   asks where you want to work with the AI: in your AI app, right in
   Cadwork in the chat, or both. Under **Deine KI-App** (your AI app),
   whatever it found on the PC is already ticked. If it finds none, it
   shows you where to get one.
5. Click **Weiter** (next) and then **Installieren** (install). The
   window shows every step; this takes a few minutes. If the PC is
   missing a component, it asks first whether it may install it too. This
   also works on company PCs without the Windows package manager: it then
   downloads it directly from the maker and checks its digital signature
   first. It makes a backup copy of your AI app's settings first.
6. When it says **Fertig eingerichtet** (all set up), everything is
   there. If something goes wrong, the window says what is missing and
   names the log file `C:\Users\Public\OpenMcpCad_installer.log`.

> Tip: if you install an AI app later, simply double-click
> 1_INSTALLIEREN.cmd again. It only adds what is missing and changes
> nothing that is already right.

Already using an AI app on your PC? Copy this text and send it to it, it
will help you set things up. The setup window remains the recommended way;
on its first page, **Text kopieren** (copy text) copies the same text in
German.

> Please help me set up Open MCP CAD. It connects Cadwork 3D 2026 with
> an AI. Guide me step by step, one step at a time, and wait until I
> have done it. 1) Download the latest ZIP file:
> https://github.com/sebastiankoukoui/open-mcp-cad/releases/latest 2)
> Close Cadwork and unzip the ZIP file (right-click, «Extract All»). 3)
> In the unzipped folder, double-click 1_INSTALLIEREN.cmd and click
> «Installieren» in the setup window. That is the recommended way. 4)
> Then quit the AI app completely and start it again. 5) In Cadwork,
> click «Open MCP CAD» until it says «Bereit». If something does not
> work, read the file Programmdateien\FUER_KI_ASSISTENTEN.md in the
> unzipped folder. Do not build your own adapter and do not talk to the
> plugin's port yourself, everything is already there.

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

There are three ways to talk to the AI. **Ways B and C are the
easiest**, with an AI app that matches your subscription. Way A is for
advanced users. Section 6 shows the ways in pictures.

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

### Way B: ChatGPT app with a ChatGPT subscription

You write in the ChatGPT app from OpenAI on the PC, Cadwork draws.

1. Install the ChatGPT app for the PC (in the setup window,
   **ChatGPT-App holen** (get the ChatGPT app) opens the Microsoft Store), start it and sign in with
   your ChatGPT account.
2. Double-click **1_INSTALLIEREN.cmd** (again). In the window,
   **ChatGPT-App (mit Codex)** is ticked: **Weiter** → **Installieren**.
3. Close the ChatGPT app completely and start it again.
4. In Cadwork, click **Open MCP CAD** (the bar shows **Bereit**).
5. Start a new chat with Codex in the ChatGPT app and write the test
   sentence. If the app asks whether it may use Open MCP CAD: allow it.

### Way C: Claude Desktop or Claude Code with a Claude subscription

You write in the Claude app (or in the command window), Cadwork draws.

1. Install **Claude Desktop** (in the setup window: **Claude Desktop
   holen** (get Claude Desktop), or from claude.com/download), start it
   and sign in.
2. Quit Claude Desktop completely (also at the bottom right next to the
   clock: right-click the Claude icon → **Quit**) before you start
   1_INSTALLIEREN.cmd.
3. Double-click **1_INSTALLIEREN.cmd** (again). In the window, **Claude
   Desktop** is ticked: **Weiter** → **Installieren**.
4. Start Claude Desktop again. In Cadwork, click **Open MCP CAD** (the
   bar shows **Bereit**).
5. Write the test sentence in Claude. If Claude asks whether it may use
   Open MCP CAD: allow it.

It also works with **Claude Code** (way A, step 1) in the command window:
the setup window adds Open MCP CAD there as well. Type **claude** in a
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

## 6. How to set it up

Sections 2 to 4 in pictures, in four steps. The numbers in each picture
match the points below it.

### Step 1: get an AI app

You need **Claude Desktop** (with a Claude subscription) or the **ChatGPT app** on the PC (with a ChatGPT subscription). If you have neither yet, the setup
window (step 2) shows this page:

![Setup 1: the setup window while there is no AI app yet](bilder/einrichten-1-ki-app-holen.png)

1. Opens Anthropic's page for Claude Desktop.
2. Opens the ChatGPT app in the Microsoft Store.
3. It only works with the app on the PC, not in the browser or on the phone.
4. After installing and signing in, click here. Then go on as in step 3.

### Step 2: unzip and double-click

![Setup 2: the ZIP file and the unzipped folder](bilder/einrichten-2-entpacken.png)

1. Right-click the ZIP file → **Extract All …** → **Extract**.
2. Close Cadwork. Then double-click **1_INSTALLIEREN.cmd** in the
   unzipped folder. The setup window opens.
3. This guide as a PDF (German; the English one is next to it).
4. Everything the setup window needs is in here. You do not have to
   open anything in it.

### Step 3: «Installieren» in the window

![Setup 3a: «Wo möchtest du mit der KI arbeiten?» (where do you want to work with the AI?)](bilder/einrichten-3a-wo.png)

1. In your AI app: Claude Desktop or the ChatGPT app.
2. Right in Cadwork in the chat, next to the drawing (see «Chat right in
   Cadwork» below).
3. Both. If an AI app is already there, this is preselected.
4. **Weiter** (next).

![Setup 3: «Deine KI-App» (your AI app) in the setup window](bilder/einrichten-3-ki-app.png)

1. Found on the PC and ticked: the window adds Open MCP CAD here.
2. The same. Untick an app you do not want to connect.
3. It only works with the app on the PC, not in the browser or on the phone.
4. **Weiter** (next).

![Setup 4: «Bereit zum Installieren» (ready to install)](bilder/einrichten-4-installieren.png)

1. What the window sets up. If the PC is missing a component, the window
   asks first whether it may install it too; it is then listed here as
   well.
2. Click **Installieren** (install).

![Setup 5: the window is setting things up and shows what is being downloaded](bilder/einrichten-5-laeuft.png)

1. The progress. This takes a few minutes.
2. What is happening right now, for example which add-on is being
   downloaded. The line above it moves as long as work is going on.
3. The step that is running right now.
4. Shows what exactly happens. This is also in the log file
   `C:\Users\Public\OpenMcpCad_installer.log`.

![Setup 6: «Fertig eingerichtet» (all set up)](bilder/einrichten-6-fertig.png)

1. Which app Open MCP CAD is now connected to.
2. The next steps, see step 4.
3. Opens this guide.
4. Closes the window.

### Step 4: restart the AI app and get going

![Setup 7: Claude Desktop or the ChatGPT app, Open MCP CAD and Cadwork](bilder/einrichten-7-apps.png)

1. The setup window has added Open MCP CAD to the app. If you only
   installed the app afterwards: double-click 1_INSTALLIEREN.cmd again.
2. Quit the app completely and start it again. Only then does it know
   Open MCP CAD.
3. In Cadwork, click **Open MCP CAD** until the bar shows **Bereit**.
4. Just write in the app's chat as usual, for example the test sentence
   from section 5. If the app asks whether it may use Open MCP CAD:
   allow it. To check, you can ask: «Which file is open in Cadwork?» If
   the AI names your file, everything is connected. Otherwise see
   section 8.
5. It does not work in the browser or on the phone, only with the app on
   the PC.

### Chat right in Cadwork

If you choose «Direkt in Cadwork im Chat» (right in Cadwork in the chat)
or «Beides» (both), the window asks for the AI of the chat:

![Setup 8a: «Welche KI im Chat in Cadwork?» (which AI in the chat in Cadwork?)](bilder/einrichten-8a-chat-ki.png)

1. Claude, with a Claude subscription. The window installs Claude Code
   for it, with Anthropic's official command.
2. ChatGPT, with a ChatGPT subscription. The window installs Codex for
   it, with OpenAI's official command. The ChatGPT app alone is not
   enough for the chat in Cadwork.
3. Later or with your own key (see below).
4. **Weiter** (next).

After installing, you sign in once:

![Setup 8b: «Bei Claude anmelden» (sign in to Claude)](bilder/einrichten-8b-anmelden.png)

1. How it works: a small black window and your browser open. Sign in
   with your account in the browser.
2. Click **Anmelden** (sign in). Then it says «Fertig eingerichtet».
   **Später** (later) also works; then run 1_INSTALLIEREN.cmd again
   later.

Then click **Open MCP CAD** in Cadwork, click the speech bubble in the
bar and write in the chat.

### For advanced users

If no AI is set up yet in the chat in Cadwork (for example after «Später»,
later), it shows this card (the speech bubble in the bar opens the chat):

![Setup 8: «Womit möchtest du chatten?» in the chat of Open MCP CAD](bilder/einrichten-8-chat.png)

1. With a Claude subscription: **So geht's** (how it works) shows the
   one step that is still missing (the same commands as in way A,
   step 1).
2. With a ChatGPT subscription: **So geht's** shows the commands for
   Codex.
3. Without a subscription: **Schlüssel eingeben** (enter key) opens the
   settings at the key field. There, under **Wer antwortet** (who
   answers), you can also choose a local AI on your PC, for example
   Ollama: no subscription, but good results need a strong model and a
   strong PC.
4. Once set up, **Nochmal prüfen** (check again). As soon as one way is
   ready, the card disappears and you can write.

## 7. How it works

This is what Open MCP CAD looks like in Cadwork. The numbers in each
picture match the points below it.

### Start the plugin

![Step 1: the bar at the top right in Cadwork](bilder/anleitung-1-leiste.png)

1. In the plugin menu, click **Open MCP CAD**. The bar appears at the top
   right, above the drawing.
2. **Bereit** (ready) means Cadwork is connected and the AI can start.
3. The speech bubble opens the chat below the bar.
4. This button docks the window on the right, in a column of its own.

### Chat with the AI

![Step 2: the chat with the test sentence and the AI's answer](bilder/anleitung-2-chat.png)

1. Write what you need here, for example the test sentence from
   section 5.
2. Every step in Cadwork appears in the history. A click shows the
   details.
3. The arrow undoes the last step in Cadwork. Next to it: redo and
   redraw.
4. The mode sets how much the AI may do on its own: **Nur lesen** (read
   only), **Fragen** (ask before every change), **Cadwork frei** (free in
   Cadwork) or **Alles automatisch** (fully automatic).
5. Choose the model and the thinking level here.

### Docked on the right

![Step 3: docked on the right, in the mailbox](bilder/anleitung-3-angedockt.png)

1. Switches between **Chat** and **Briefkasten** (mailbox).
2. The mailbox shows what is running in Cadwork right now, with the
   latest jobs below.
3. Leave a note for the AI here. It waits until the AI picks it up.
4. Undocks the window so that it floats again.

### While the AI is drawing

![Step 4: the card KI zeichnet (AI is drawing) above the drawing](bilder/anleitung-4-anzeige.png)

1. A small card above the drawing shows that the AI is at work.
2. How many parts are done and how long it will take.
3. **Anhalten** (stop) discards the waiting jobs. The current step still
   finishes.

## 8. If it does not work

- **Clicking Open MCP CAD does nothing:** the reason is in the file
  `C:\Users\Public\OpenMcpCad_start.log`.
- **The AI does not know Cadwork:** quit the AI program completely and
  start it again. If that does not help, double-click 1_INSTALLIEREN.cmd
  again, leave the app ticked and click **Installieren**. For ChatGPT,
  take the ChatGPT app from the Microsoft Store; the older «ChatGPT
  Classic» does not know Open MCP CAD.
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
  or via [lignoai.ch](https://lignoai.ch). Attach the files
  `C:\Users\Public\OpenMcpCad_start.log` and
  `C:\Users\Public\OpenMcpCad_installer.log` (the log of the setup
  window).

![First contact in the plugin chat, as long as nothing is set up yet](bilder/willkommen.png)

More (all settings, uninstalling): the detailed guide in the folder
Programmdateien.
