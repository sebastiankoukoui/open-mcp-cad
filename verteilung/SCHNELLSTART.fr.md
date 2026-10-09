# Open MCP CAD – Démarrage rapide

Du fichier ZIP au premier mur qu'une IA dessine dans Cadwork. Sans
connaissances en informatique, en 20 minutes environ.

Open MCP CAD relie un programme d'IA (par exemple ChatGPT ou Claude) à ton
Cadwork ouvert. Tu écris avec des mots simples ce que tu veux, et l'IA le
dessine dans Cadwork. Avant chaque modification, elle te demande. (MCP est
le nom du pont par lequel un programme d'IA peut piloter un autre
programme.)

Le plugin et l'installateur parlent allemand. Leurs mots sont écrits ici
en **gras**, avec la traduction entre parenthèses si nécessaire.

## 1. Ce qu'il te faut

- Un PC Windows avec **Cadwork 3D 2026**.
- Internet pendant l'installation.
- **Une application d'IA avec abonnement :** Claude Desktop (avec un
  abonnement Claude, Pro ou Max) ou l'application ChatGPT d'OpenAI (avec un
  abonnement ChatGPT, Plus ou Pro). Un abonnement est un montant mensuel
  chez le fournisseur. Cela marche seulement avec l'application sur le
  PC, pas dans le navigateur ni sur le téléphone. Sans abonnement, cela marche aussi avec une **clé** – un code
  d'accès pris sur le site du fournisseur ; tu paies alors par requête
  (voir « Pour les utilisateurs avancés » à la section 6).

## 2. Installer (un double-clic)

La section 6 montre ces étapes en images.

1. Clic droit sur le fichier ZIP → **Extraire tout …** → **Extraire**.
2. **Fermer Cadwork.**
3. Dans le dossier extrait, double-cliquer sur **1_INSTALLIEREN.cmd**.
   Si Windows demande si tu veux vraiment exécuter le fichier :
   **Exécuter** (ou **Informations complémentaires** → **Exécuter quand
   même**).
4. La fenêtre «Open MCP CAD einrichten» (installer Open MCP CAD)
   s'ouvre. Elle demande où tu veux travailler avec l'IA : dans ton
   application d'IA, directement dans Cadwork dans le chat, ou les deux.
   Sous **Deine KI-App** (ton application d'IA), ce qu'elle a trouvé sur
   le PC est déjà coché. Si elle n'en trouve aucune, elle te montre où en
   obtenir une.
5. Cliquer sur **Weiter** (suivant) puis sur **Installieren**
   (installer). La fenêtre montre chaque étape ; cela prend quelques
   minutes. S'il manque un composant au PC, elle demande d'abord si elle
   peut l'installer aussi. Cela marche aussi sur les PC d'entreprise sans
   le gestionnaire de paquets de Windows : elle le télécharge alors
   directement chez l'éditeur et vérifie d'abord sa signature numérique.
   Elle fait d'abord une copie de sauvegarde des réglages de ton
   application d'IA.
6. Quand **Fertig eingerichtet** (installation terminée) s'affiche, tout
   est là. Si quelque chose ne marche pas, la fenêtre dit ce qui manque
   et indique le journal `C:\Users\Public\OpenMcpCad_installer.log`.

> Astuce : si tu installes une application d'IA plus tard, double-clique
> simplement à nouveau sur 1_INSTALLIEREN.cmd. Il ajoute seulement ce qui
> manque et ne change rien de ce qui est déjà juste.

Tu utilises déjà une application d'IA sur ton PC ? Copie ce texte et
envoie-le-lui, elle t'aidera à installer. La fenêtre d'installation reste
le chemin recommandé ; sur sa première page, **Text kopieren** (copier le
texte) copie le même texte en allemand.

> Aide-moi s'il te plaît à installer Open MCP CAD. Il relie Cadwork 3D
> 2026 à une IA. Guide-moi pas à pas, une seule étape à la fois, et
> attends que je l'aie faite. 1) Télécharger le dernier fichier ZIP :
> https://github.com/sebastiankoukoui/open-mcp-cad/releases/latest 2)
> Fermer Cadwork et extraire le fichier ZIP (clic droit, «Extraire
> tout»). 3) Dans le dossier extrait, double-cliquer sur
> 1_INSTALLIEREN.cmd et cliquer sur «Installieren» dans la fenêtre
> d'installation. C'est le chemin recommandé. 4) Ensuite, quitter
> complètement l'application d'IA et la redémarrer. 5) Dans Cadwork,
> cliquer sur «Open MCP CAD» jusqu'à ce que «Bereit» s'affiche. Si
> quelque chose ne marche pas, lis le fichier
> Programmdateien\FUER_KI_ASSISTENTEN.md dans le dossier extrait. Ne
> construis pas d'adaptateur et ne parle pas toi-même au port du plugin,
> tout est déjà là.

## 3. Connecter Cadwork

1. Démarrer Cadwork et ouvrir un fichier (un nouveau fichier vide suffit).
2. Dans le menu des plugins, cliquer sur **Open MCP CAD**.
3. La petite **barre** d'Open MCP CAD apparaît en haut à droite, au-dessus
   du dessin. Quand elle affiche **Bereit** (prêt), Cadwork est connecté.

![La barre en haut à droite dans Cadwork : connectée et prête](bilder/monitor.png)

Les boutons de la barre :

- **Bulle** : ouvre le chat en dessous. Le trait tout à droite le
  replie en barre.
- **Deux flèches** : place la fenêtre à droite du dessin, dans sa propre
  colonne. Cliquer encore la détache.
- **Trennen** (déconnecter) : déconnecte Cadwork de l'IA. Ensuite un **×**
  apparaît à droite et ferme la fenêtre. Un clic sur **Open MCP CAD** dans
  le menu des plugins la ramène.

## 4. Choisir un chemin

Il y a trois chemins pour parler à l'IA. **Les chemins B et C sont les
plus simples**, avec une application d'IA qui correspond à ton
abonnement. Le chemin A est pour les utilisateurs avancés. La section 6
montre les chemins en images.

### Chemin A : chat dans le plugin avec un abonnement Claude

Tu écris directement dans Cadwork, dans le chat d'Open MCP CAD.

1. Installer Claude Code une fois : appuyer sur la touche Windows, taper
   **PowerShell**, Entrée. Une fenêtre pour les commandes s'ouvre. Y taper
   (ou copier) cette ligne et appuyer sur Entrée :
   ```
   irm https://claude.ai/install.ps1 | iex
   ```
   Cela prend environ une minute et ne demande pas de droits
   d'administrateur. Ensuite fermer la fenêtre, en ouvrir une **nouvelle**
   (à nouveau **PowerShell**) et taper :
   ```
   claude
   ```
   Au premier démarrage, le navigateur s'ouvre : se connecter avec ton
   compte Claude. Ensuite fermer la fenêtre. Si Windows ne connaît pas
   encore «claude», utiliser plutôt cette ligne :
   ```
   ~\.local\bin\claude.exe
   ```
   Seulement si la première ligne ne marche pas (par exemple parce qu'un
   ordinateur d'entreprise la bloque) : Claude Code s'installe aussi avec
   Node.js, avec `winget install OpenJS.NodeJS.LTS` puis, dans une
   nouvelle fenêtre, `npm install -g @anthropic-ai/claude-code`. Si winget
   manque, installer Node.js (version «LTS») depuis
   [nodejs.org](https://nodejs.org).
2. Dans Cadwork, cliquer sur la **bulle** dans la barre. Le chat
   s'ouvre en dessous.
3. En haut à gauche du chat, cliquer sur **Ordner wählen**
   (choisir le dossier) et choisir un dossier de projet (pas tout le
   disque). Claude peut y lire.
4. Écrire la phrase de test en bas (voir section 5) et appuyer sur
   Entrée.

![Le chat sous la barre : tu écris en bas, l'IA répond et dessine](bilder/chat.png)

### Chemin B : application ChatGPT avec un abonnement ChatGPT

Tu écris dans l'application ChatGPT d'OpenAI sur le PC, Cadwork dessine.

1. Installer l'application ChatGPT pour le PC (dans la fenêtre
   d'installation, **ChatGPT-App holen** (obtenir l'application ChatGPT)
   ouvre le Microsoft Store), la démarrer et se connecter avec ton compte ChatGPT.
2. Double-cliquer (à nouveau) sur **1_INSTALLIEREN.cmd**. Dans la
   fenêtre, **ChatGPT-App (mit Codex)** est coché : **Weiter** → **Installieren**.
3. Fermer complètement l'application ChatGPT et la redémarrer.
4. Dans Cadwork, cliquer sur **Open MCP CAD** (la barre affiche
   **Bereit**).
5. Dans l'application ChatGPT, commencer un nouveau chat avec Codex et
   écrire la phrase de test. Si l'application demande si elle peut
   utiliser Open MCP CAD : l'autoriser.

### Chemin C : Claude Desktop ou Claude Code avec un abonnement Claude

Tu écris dans l'application Claude (ou dans la fenêtre de commandes),
Cadwork dessine.

1. Installer **Claude Desktop** (dans la fenêtre d'installation :
   **Claude Desktop holen** (obtenir Claude Desktop), ou depuis
   claude.com/download), le démarrer et se connecter.
2. Quitter complètement Claude Desktop (aussi en bas à droite près de
   l'heure : clic droit sur l'icône Claude → **Quitter**) avant de lancer
   1_INSTALLIEREN.cmd.
3. Double-cliquer (à nouveau) sur **1_INSTALLIEREN.cmd**. Dans la
   fenêtre, **Claude Desktop** est coché : **Weiter** → **Installieren**.
4. Redémarrer Claude Desktop. Dans Cadwork, cliquer sur **Open MCP CAD**
   (la barre affiche **Bereit**).
5. Écrire la phrase de test dans Claude. Si Claude demande s'il peut
   utiliser Open MCP CAD : l'autoriser.

Cela marche aussi avec **Claude Code** (chemin A, étape 1) dans la fenêtre
de commandes : la fenêtre d'installation y inscrit aussi Open MCP CAD.
Taper **claude** dans un dossier de projet et écrire la phrase de test.

## 5. Le premier test

Écris à l'IA :

> Dessine un mur de 4 m de long et 2,5 m de haut

L'IA regarde d'abord le modèle Cadwork ouvert. Avant de dessiner, elle te
demande (dans le chat du plugin avec **Erlauben** / **Ablehnen**,
autoriser / refuser). Pendant qu'elle travaille, un petit affichage
au-dessus de Cadwork montre ce qu'elle fait, par exemple **KI zeichnet**
(l'IA dessine). Après ton accord, le mur est dans Cadwork. Ensuite
tu peux continuer, par exemple « Fais-le épais de 20 cm » ou « Mets une
fenêtre au milieu ».

## 6. Comment l'installer

Les sections 2 à 4 en images, en quatre étapes. Les numéros sur chaque
image renvoient aux points en dessous.

### Étape 1 : obtenir une application d'IA

Il te faut **Claude Desktop** (avec un abonnement Claude) ou
l'**application ChatGPT** sur le PC (avec un abonnement ChatGPT). Si tu n'en as
encore aucune, la fenêtre d'installation (étape 2) montre cette page :

![Installation 1 : la fenêtre d'installation tant qu'il n'y a pas d'application d'IA](bilder/einrichten-1-ki-app-holen.png)

1. Ouvre la page d'Anthropic pour Claude Desktop.
2. Ouvre l'application ChatGPT dans le Microsoft Store.
3. Cela marche seulement avec l'application sur le PC, pas dans le navigateur ni sur le téléphone.
4. Après l'installation et la connexion, cliquer ici. Ensuite, continuer
   comme à l'étape 3.

### Étape 2 : extraire le ZIP et double-cliquer

![Installation 2 : le fichier ZIP et le dossier extrait](bilder/einrichten-2-entpacken.png)

1. Clic droit sur le fichier ZIP → **Extraire tout …** → **Extraire**.
2. Fermer Cadwork. Puis, dans le dossier extrait, double-cliquer sur
   **1_INSTALLIEREN.cmd**. La fenêtre d'installation s'ouvre.
3. Ce guide en PDF (en allemand ; ce guide en français est dans le
   dossier Programmdateien).
4. Ici se trouve tout ce dont la fenêtre d'installation a besoin. Tu n'as
   rien à y ouvrir.

### Étape 3 : «Installieren» dans la fenêtre

![Installation 3a : «Wo möchtest du mit der KI arbeiten?» (où veux-tu travailler avec l'IA ?)](bilder/einrichten-3a-wo.png)

1. Dans ton application d'IA : Claude Desktop ou l'application ChatGPT.
2. Directement dans Cadwork dans le chat, à côté du dessin (voir «Chat
   directement dans Cadwork» plus bas).
3. Les deux. Si une application d'IA est déjà là, c'est présélectionné.
4. **Weiter** (suivant).

![Installation 3 : «Deine KI-App» (ton application d'IA) dans la fenêtre d'installation](bilder/einrichten-3-ki-app.png)

1. Trouvé sur le PC et coché : la fenêtre y inscrit Open MCP CAD.
2. De même. Décoche une application que tu ne veux pas connecter.
3. Cela marche seulement avec l'application sur le PC, pas dans le navigateur ni sur le téléphone.
4. **Weiter** (suivant).

![Installation 4 : «Bereit zum Installieren» (prêt à installer)](bilder/einrichten-4-installieren.png)

1. Ce que la fenêtre installe. S'il manque un composant au PC, la
   fenêtre demande d'abord si elle peut l'installer aussi ; il figure
   alors aussi ici.
2. Cliquer sur **Installieren** (installer).

![Installation 5 : la fenêtre installe et montre ce qui se télécharge](bilder/einrichten-5-laeuft.png)

1. La progression. Cela prend quelques minutes.
2. Ce qui se passe en ce moment, par exemple quel composant se
   télécharge. Le trait au-dessus bouge tant que le travail continue.
3. L'étape en cours.
4. Montre ce qui se passe exactement. C'est aussi dans le journal
   `C:\Users\Public\OpenMcpCad_installer.log`.

![Installation 6 : «Fertig eingerichtet» (installation terminée)](bilder/einrichten-6-fertig.png)

1. L'application à laquelle Open MCP CAD est maintenant connecté.
2. Les étapes suivantes, voir l'étape 4.
3. Ouvre ce guide.
4. Ferme la fenêtre.

### Étape 4 : redémarrer l'application d'IA et commencer

![Installation 7 : Claude Desktop ou l'application ChatGPT, Open MCP CAD et Cadwork](bilder/einrichten-7-apps.png)

1. La fenêtre d'installation a inscrit Open MCP CAD dans l'application.
   Si tu n'as installé l'application qu'après : double-cliquer encore une
   fois sur 1_INSTALLIEREN.cmd.
2. Fermer complètement l'application et la redémarrer. C'est seulement
   alors qu'elle connaît Open MCP CAD.
3. Dans Cadwork, cliquer sur **Open MCP CAD** jusqu'à ce que la barre
   affiche **Bereit**.
4. Écrire tout simplement dans le chat de l'application, par exemple la
   phrase de test de la section 5. Si l'application demande si elle peut
   utiliser Open MCP CAD : l'autoriser. Pour vérifier, tu peux demander :
   « Quel fichier est ouvert dans Cadwork ? » Si l'IA nomme ton fichier,
   tout est connecté. Sinon, voir la section 8.
5. Cela ne marche pas dans le navigateur ni sur le téléphone, seulement
   avec l'application sur le PC.

### Chat directement dans Cadwork

Si tu choisis «Direkt in Cadwork im Chat» (directement dans Cadwork dans
le chat) ou «Beides» (les deux), la fenêtre demande l'IA du chat :

![Installation 8a : «Welche KI im Chat in Cadwork?» (quelle IA dans le chat de Cadwork ?)](bilder/einrichten-8a-chat-ki.png)

1. Claude, avec un abonnement Claude. La fenêtre installe pour cela
   Claude Code avec la commande officielle d'Anthropic.
2. ChatGPT, avec un abonnement ChatGPT. La fenêtre installe pour cela
   Codex avec la commande officielle d'OpenAI. L'application ChatGPT
   seule ne suffit pas pour le chat dans Cadwork.
3. Plus tard ou avec ta propre clé (voir plus bas).
4. **Weiter** (suivant).

Après l'installation, tu te connectes une fois :

![Installation 8b : «Bei Claude anmelden» (se connecter à Claude)](bilder/einrichten-8b-anmelden.png)

1. Voici comment : une petite fenêtre noire et ton navigateur s'ouvrent.
   Connecte-toi avec ton compte dans le navigateur.
2. Cliquer sur **Anmelden** (se connecter). Ensuite, «Fertig
   eingerichtet» s'affiche. **Später** (plus tard) marche aussi ; relance
   alors 1_INSTALLIEREN.cmd plus tard.

Ensuite, dans Cadwork, cliquer sur **Open MCP CAD**, sur la bulle de la
barre, et écrire dans le chat.

### Pour les utilisateurs avancés

Si aucune IA n'est encore configurée dans le chat de Cadwork (par exemple
après «Später», plus tard), cette carte s'affiche (la bulle de la barre
ouvre le chat) :

![Installation 8 : «Womit möchtest du chatten?» dans le chat d'Open MCP CAD](bilder/einrichten-8-chat.png)

1. Avec un abonnement Claude : **So geht's** (comment faire) montre la
   seule étape qui manque encore (les mêmes commandes que dans le chemin
   A, étape 1).
2. Avec un abonnement ChatGPT : **So geht's** montre les commandes pour
   Codex.
3. Sans abonnement : **Schlüssel eingeben** (saisir la clé) ouvre les
   réglages au champ de la clé. Là, sous **Wer antwortet** (qui répond),
   tu choisis aussi une IA locale sur ton PC, par exemple Ollama : sans
   abonnement, mais de bons résultats demandent un modèle puissant et un
   PC puissant.
4. Une fois configuré, **Nochmal prüfen** (vérifier à nouveau). Dès qu'un
   chemin est prêt, la carte disparaît et tu peux écrire.

## 7. Comment ça marche

Voici Open MCP CAD dans Cadwork. Les numéros sur chaque image renvoient
aux points en dessous.

### Lancer le plugin

![Étape 1 : la barre en haut à droite dans Cadwork](bilder/anleitung-1-leiste.png)

1. Dans le menu des plugins, cliquer sur **Open MCP CAD**. La barre
   apparaît en haut à droite, au-dessus du dessin.
2. **Bereit** (prêt) signifie que Cadwork est connecté et que l'IA peut
   commencer.
3. La bulle ouvre le chat sous la barre.
4. Ce bouton ancre la fenêtre à droite, dans sa propre colonne.

### Discuter avec l'IA

![Étape 2 : le chat avec la phrase de test et la réponse de l'IA](bilder/anleitung-2-chat.png)

1. Écris ici ce dont tu as besoin, par exemple la phrase de test de la
   section 5.
2. Chaque étape dans Cadwork figure dans l'historique. Un clic affiche
   les détails.
3. La flèche annule la dernière étape dans Cadwork. À côté : rétablir et
   redessiner.
4. Le mode définit ce que l'IA peut faire seule : **Nur lesen** (lecture
   seule), **Fragen** (demander avant chaque modification), **Cadwork
   frei** (libre dans Cadwork) ou **Alles automatisch** (tout
   automatique).
5. Ici tu choisis le modèle et le niveau de réflexion.

### Ancré à droite

![Étape 3 : ancré à droite, dans la boîte aux lettres](bilder/anleitung-3-angedockt.png)

1. Passe du **Chat** à la **Briefkasten** (boîte aux lettres) et
   inversement.
2. La boîte aux lettres montre ce qui tourne en ce moment dans Cadwork,
   avec les derniers travaux en dessous.
3. Ici tu déposes une note pour l'IA. Elle attend jusqu'à ce que l'IA la
   récupère.
4. Détache la fenêtre pour qu'elle flotte à nouveau.

### Pendant que l'IA dessine

![Étape 4 : l'affichage KI zeichnet (l'IA dessine) au-dessus du dessin](bilder/anleitung-4-anzeige.png)

1. Un petit affichage au-dessus du dessin montre que l'IA travaille.
2. Combien d'éléments sont déjà dessinés et combien de temps il reste.
3. **Anhalten** (arrêter) annule les travaux en attente. L'étape en cours
   se termine encore.

## 8. Si cela ne marche pas

- **Le clic sur Open MCP CAD ne fait rien :** la raison est dans le
  fichier `C:\Users\Public\OpenMcpCad_start.log`.
- **L'IA ne connaît pas Cadwork :** fermer complètement le programme d'IA
  et le redémarrer. Si cela n'aide pas, double-cliquer encore une fois sur
  1_INSTALLIEREN.cmd, laisser l'application cochée et cliquer sur
  **Installieren**. Pour ChatGPT, prendre l'application ChatGPT du
  Microsoft Store ; l'ancienne «ChatGPT Classic» ne connaît pas Open MCP
  CAD.
- **L'IA dit que Cadwork n'est pas joignable :** dans Cadwork, cliquer sur
  **Open MCP CAD** et attendre que la barre affiche **Bereit**.
- **Le chat du plugin affiche «Womit möchtest du chatten?»** (avec quoi
  veux-tu discuter ?) : choisir le chemin qui correspond à ton
  abonnement ; les boutons montrent l'étape suivante.
- **Si tu demandes de l'aide à une IA** (par exemple «installe ça») :
  donne-lui le fichier `Programmdateien\FUER_KI_ASSISTENTEN.md`. Il dit
  ce qu'elle doit faire. Si elle veut d'abord construire quelque chose en
  plus (par exemple un «adaptateur») : inutile, tout est déjà là.
- **Sinon :** écris-nous sur
  [github.com/sebastiankoukoui/open-mcp-cad/issues](https://github.com/sebastiankoukoui/open-mcp-cad/issues)
  ou via [lignoai.ch](https://lignoai.ch). Joins les fichiers
  `C:\Users\Public\OpenMcpCad_start.log` et
  `C:\Users\Public\OpenMcpCad_installer.log` (le journal de la
  fenêtre d'installation).

![Premier contact dans le chat du plugin, tant que rien n'est configuré](bilder/willkommen.png)

Plus (tous les réglages, désinstallation) : le guide détaillé dans le
dossier Programmdateien.
