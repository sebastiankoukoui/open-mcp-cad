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
- **Un abonnement IA** que tu as peut-être déjà : ChatGPT (Plus ou Pro) ou
  Claude (Pro ou Max). Un abonnement est un montant mensuel chez le
  fournisseur. Sans abonnement, cela marche aussi avec une **clé** – un
  code d'accès pris sur le site du fournisseur ; tu paies alors par
  requête.

## 2. Installer (un double-clic)

1. Clic droit sur le fichier ZIP → **Extraire tout …** → **Extraire**.
2. **Fermer Cadwork.**
3. Dans le dossier extrait, double-cliquer sur **1_INSTALLIEREN.cmd**.
   Si Windows demande si tu veux vraiment exécuter le fichier :
   **Exécuter** (ou **Informations complémentaires** → **Exécuter quand
   même**).
4. Une fenêtre noire apparaît et travaille quelques minutes. Réponds aux
   questions avec **Entrée** – la proposition est alors retenue. S'il
   manque un composant au PC, elle demande si elle peut le chercher. Cela
   marche aussi sur les PC d'entreprise sans le gestionnaire de paquets
   Windows winget : elle le télécharge alors directement chez l'éditeur et
   vérifie d'abord sa signature numérique.
5. À la fin, elle demande pour chaque programme d'IA trouvé, par exemple
   «Open MCP CAD in Codex eintragen? [J/n]» (inscrire Open MCP CAD dans
   Codex ?). **Entrée** l'y inscrit. Une copie de sauvegarde est faite
   avant.
6. Tout en bas, sous **Ergebnis** (résultat), chaque partie est listée
   séparément. S'il est écrit «NICHT vollstaendig installiert» (pas
   entièrement installé), les raisons sont juste au-dessus.

> Astuce : si tu installes un programme d'IA plus tard, double-clique
> simplement à nouveau sur 1_INSTALLIEREN.cmd. Il ajoute seulement ce qui
> manque et ne change rien de ce qui est déjà juste.

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

Il y a trois chemins pour parler à l'IA. **Prends le chemin de
l'abonnement IA que tu as déjà.** Si tu n'en as pas encore : le chemin B
avec l'application Codex est le plus éprouvé chez les collègues.

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

### Chemin B : application Codex avec un abonnement ChatGPT

Tu écris dans l'application Codex d'OpenAI, Cadwork dessine.

1. Installer l'application **Codex** depuis le **Microsoft Store**, la
   démarrer et se connecter avec ton compte ChatGPT.
2. Double-cliquer (à nouveau) sur **1_INSTALLIEREN.cmd** et confirmer
   «Open MCP CAD in Codex eintragen?» avec **Entrée**.
3. Fermer complètement l'application Codex et la redémarrer.
4. Dans Cadwork, cliquer sur **Open MCP CAD** (la barre affiche
   **Bereit**).
5. Dans l'application Codex, commencer un nouveau chat et écrire la phrase
   de test. Si Codex demande s'il peut utiliser Open MCP CAD : l'autoriser.

### Chemin C : Claude Desktop ou Claude Code avec un abonnement Claude

Tu écris dans l'application Claude (ou dans la fenêtre de commandes),
Cadwork dessine.

1. Installer **Claude Desktop** depuis claude.ai/download, le démarrer et
   se connecter.
2. Quitter complètement Claude Desktop (aussi en bas à droite près de
   l'heure : clic droit sur l'icône Claude → **Quitter**) avant de lancer
   l'installateur.
3. Double-cliquer (à nouveau) sur **1_INSTALLIEREN.cmd** et confirmer
   «Open MCP CAD in Claude Desktop eintragen?» avec **Entrée**.
4. Redémarrer Claude Desktop. Dans Cadwork, cliquer sur **Open MCP CAD**
   (la barre affiche **Bereit**).
5. Écrire la phrase de test dans Claude. Si Claude demande s'il peut
   utiliser Open MCP CAD : l'autoriser.

Cela marche aussi avec **Claude Code** (chemin A, étape 1) dans la fenêtre
de commandes : l'installateur y inscrit aussi Open MCP CAD. Taper
**claude** dans un dossier de projet et écrire la phrase de test.

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

## 6. Si cela ne marche pas

- **Le clic sur Open MCP CAD ne fait rien :** la raison est dans le
  fichier `C:\Users\Public\OpenMcpCad_start.log`.
- **L'IA ne connaît pas Cadwork :** fermer complètement le programme d'IA
  et le redémarrer. Si cela n'aide pas, double-cliquer encore une fois sur
  1_INSTALLIEREN.cmd et confirmer l'inscription avec Entrée.
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
  ou via [lignoai.ch](https://lignoai.ch). Joins le fichier
  `C:\Users\Public\OpenMcpCad_start.log` et une capture d'écran du
  **Ergebnis** (résultat) de l'installateur.

![Premier contact dans le chat du plugin, tant que rien n'est configuré](bilder/willkommen.png)

Plus (tous les réglages, désinstallation) : le guide détaillé dans le
dossier Programmdateien.
