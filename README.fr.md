<p align="center">
  <img src="assets/logo.png" alt="Open MCP CAD" width="210">
</p>

<p align="center">
  <a href="README.md">Deutsch</a> · <a href="README.en.md">English</a> · <b>Français</b> · <a href="README.it.md">Italiano</a>
</p>

# Open MCP CAD

**Le pont entre un assistant IA et votre CAO en cours d'exécution.**

Un serveur MCP et un plugin CAO qui permettent à un modèle de langage de
lire et de créer de la géométrie dans un **document Cadwork 3D ouvert**,
avec file d'attente, cartes d'autorisation, licence d'écriture, prise en
charge de l'annulation et une fenêtre qui montre à tout moment ce qui est
en cours.

> **Ce qui n'est PAS ici :** de la logique de construction. Pas de
> catalogue de détails, pas de générateurs d'éléments, pas de savoir-faire
> métier. Ce dépôt est le tuyau, pas l'eau. Vous ajoutez votre propre
> savoir-faire via `OPEN_MCP_CAD_KNOWLEDGE`, voir
> [Votre propre savoir-faire](#votre-propre-savoir-faire).

---

<!-- ki-assistenten:anfang -->
## Pour les assistants IA (For AI assistants)

Vous êtes une IA et devez installer Open MCP CAD ? Alors :

- **Le serveur MCP existe déjà.** Il s'appelle `open-mcp-cad` et démarre
  avec `python -m open_mcp_cad.server`. **Ne construisez ni adaptateur, ni
  passerelle, ni serveur maison.**
- **Ne parlez jamais vous-même au plugin.** Le plugin dans Cadwork écoute
  sur `127.0.0.1`, ports 53127–53199, avec un protocole interne (lignes
  JSON) qui n'existe que pour ce serveur. Aucun programme d'IA ne s'y
  connecte directement.

Votre tâche se limite à ceci :

1. **Lancer l'installateur, si ce n'est pas encore fait.** L'utilisateur
   double-clique sur `1_INSTALLIEREN.cmd` en haut du ZIP décompressé
   (dernière version :
   https://github.com/sebastiankoukoui/open-mcp-cad/releases/latest). Il
   copie le plugin dans Cadwork, installe le serveur dans
   `%LOCALAPPDATA%\OpenMcpCad\python` et propose à la fin de faire
   lui-même l'étape 2. Le serveur est installé quand
   `"%LOCALAPPDATA%\OpenMcpCad\python\Scripts\python.exe" -c "import open_mcp_cad.server"`
   se termine sans erreur.
2. **Inscrire le serveur dans le programme d'IA**, si l'installateur ne
   l'a pas fait. `<PYTHON>` est le chemin complet de
   `%LOCALAPPDATA%\OpenMcpCad\python\Scripts\pythonw.exe` (avec **w** :
   sans fenêtre de console). Faire d'abord une copie de sauvegarde du
   fichier, ajouter uniquement l'entrée `open-mcp-cad` et laisser toutes
   les autres entrées telles quelles.
   - **Codex** (CLI et application de bureau avec Codex) :
     `%USERPROFILE%\.codex\config.toml` (ou `%CODEX_HOME%\config.toml`)
     ```toml
     [mcp_servers.open-mcp-cad]
     command = '<PYTHON>'
     args = ["-m", "open_mcp_cad.server"]
     ```
   - **Claude Desktop** : `%APPDATA%\Claude\claude_desktop_config.json`
     (version du Store : sous
     `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\`), barres
     obliques inverses doublées dans le JSON
     ```json
     {
       "mcpServers": {
         "open-mcp-cad": { "command": "<PYTHON>", "args": ["-m", "open_mcp_cad.server"] }
       }
     }
     ```
   - **Claude Code** :
     ```
     claude mcp add --scope user open-mcp-cad -- "<PYTHON>" -m open_mcp_cad.server
     ```
3. **Dire à l'utilisateur :** quitter complètement le programme d'IA et le
   relancer, puis dans Cadwork cliquer sur **Open MCP CAD** dans le menu
   des plugins, jusqu'à ce que la petite barre en haut à droite affiche
   **Bereit** (prêt).
   Ensuite, les outils d'Open MCP CAD (par exemple `get_document_info`)
   sont disponibles dans le programme d'IA.

ChatGPT dans le navigateur ou sur le téléphone ne peut pas utiliser de
serveurs MCP locaux. Sur le PC, cela fonctionne dans l'application de
bureau ChatGPT avec Codex (anciennement l'application Codex) ; selon
OpenAI, elle utilise le même dossier `%USERPROFILE%\.codex` que la CLI
Codex.
<!-- ki-assistenten:ende -->

## Pourquoi ce projet existe

Un modèle de langage sait écrire du code cwapi3d. Le faire parvenir dans
une CAO en cours d'exécution, c'est là le vrai problème :

- **cwapi3d n'est pas thread-safe.** Chaque appel à l'API doit s'exécuter
  dans le thread principal, l'un après l'autre. Sinon, on obtient des
  plantages qui semblent impossibles à reproduire.
- **La CAO ne doit pas se figer** pendant qu'une tâche s'exécute.
- **Rien ne doit arriver au modèle sans qu'on le remarque.** Chaque appel
  va dans un historique, chaque accès en écriture passe par une
  autorisation.
- **Plusieurs documents en même temps** demandent des lignes séparées qui
  ne se croisent pas.

Tout cela est ici, mesuré plutôt qu'affirmé : **plus de 600 contrôles sans
installation de CAO**, plus un test qui construit et utilise réellement
l'interface.

## Architecture

```
Assistant IA --stdio--> serveur MCP --TCP 127.0.0.1:53127..53199--> plugin CAO
   (hôte)              (open-mcp-cad)                               (dans Cadwork)
                                                                         |
                                                                      cwapi3d
```

**Autant de lignes que nécessaire.** Une seule entrée de menu
**Open MCP CAD**, lancée dans autant de fenêtres Cadwork que nécessaire. Un
clic ouvre le panneau et se connecte : chaque fenêtre reçoit le prochain
port libre (53127–53199), son propre journal et sa propre boîte aux
lettres. Vous travaillez ainsi sur plusieurs documents en parallèle sans
que les lignes se croisent.

Chaque instance s'inscrit avec le **nom de son document**. On la retrouve
ensuite par le document, pas par le port :

```bat
set OPEN_MCP_CAD_DOC=Seeblick
```

C'est la vraie question qu'on se pose. *« Quel port sert Seeblick ? »*
n'était écrit nulle part avant, il fallait s'en souvenir. Le client ne
choisit que si **exactement une** instance en cours correspond. S'il y en a
plusieurs, ou aucune (par exemple parce que le serveur a démarré avant
Cadwork), il n'envoie rien, indique ce qui est connecté et redemande à
l'appel suivant. Il ne se rabat jamais sur un port fixe : du code dans le
mauvais fichier, c'est exactement le dommage que la protection du document
doit empêcher. Une fois la fenêtre trouvée, il reste sur elle, comme décrit
ci-dessous.

Sans aucun réglage, même cela est inutile : le serveur prend la **seule**
fenêtre connectée. S'il y en a plusieurs, il ne devine pas mais répond
avec `instanz_waehlen` et la liste, et l'IA choisit avec `wait_for_bridge`.
Une fois le choix fait, il reste sur cette fenêtre, même si une deuxième se
connecte plus tard. Si elle est fermée ou affiche un autre fichier, il
redemande ; il ne change jamais en silence. (Seul le serveur choisit ainsi ;
les scripts qui importent `bridge_client` restent sur 53127 sans réglage.)

Le noyau existe **une seule fois** dans
`cad_plugin/_core/omcad_bridge_core.py`. Les dossiers de plugin en sont
générés et vérifiés octet par octet. À côté du dossier livré
`Open MCP CAD`, le dépôt contient `Open MCP CAD A` … `F` avec des ports
fixes (53127–53132), pour les tests et pour les hôtes qui ont besoin d'un
port fixe.

### Comment la CAO reste utilisable

L'écoute TCP tourne dans un thread secondaire, le traitement d'une tâche
exclusivement dans le thread principal, via un `QTimer` qui s'accroche à
la boucle d'événements **existante** de la CAO. Les demandes d'état, la
pause et l'arrêt sont traités par les threads de travail eux-mêmes et
n'attendent jamais une tâche en cours.

Quand la CAO travaille elle-même dans son thread principal (une boîte de
dialogue modale ou de progression, un menu ouvert, une boucle d'événements
imbriquée), le minuteur laisse toutes les tâches dans la file d'attente et
n'appelle pas l'API ; `get_connection_status` en donne la raison
(`cadwork_beschaeftigt`). L'origine : un plantage après deux tâches de
lecture exécutées au milieu d'un long calcul de la CAO. Un seul service au
plus tourne par processus de CAO : un nouveau clic sur le plugin ramène
celui qui tourne au lieu d'ouvrir un second port.

> L'approche évidente, pomper les messages de fenêtre depuis le plugin,
> n'était pas la solution mais la cause : elle a provoqué de façon avérée
> une violation d'accès dans le processus de la CAO. Le raisonnement se
> trouve dans [`docs/BRIDGE.md`](docs/BRIDGE.md), section 2 (en allemand).

## Outils

| Outil | Ce qu'il fait | Via le pont ? |
|---|---|---|
| `get_document_info` | nom du document + nombre d'éléments | oui |
| `get_connection_status` | état, tâche en cours, file d'attente, licence d'écriture, **répond même pendant le dessin** | oui, sans thread principal |
| `execute_cadwork_command` | exécute du code Python cwapi3d (attente de la réponse avec `timeout_s`) | oui |
| `execute_cadwork_batch` | exécute le même code par paquets sur une liste de données JSON : grandes quantités, progression dans le panneau | oui |
| `undo` / `redo` | annule ou rétablit les dernières tâches (l'annulation propre à cadwork) | oui |
| `set_fast_draw` | coupe le rafraîchissement de l'écran pendant les longs dessins | oui |
| `redraw_view` | redessine la vue si rien n'apparaît après un zoom dans une tâche (ne modifie pas le modèle) | oui |
| `report_check_note` | signale une hypothèse ou une incertitude dans la fenêtre de la CAO, avec des ID d'éléments cliquables | oui, sans thread principal |
| `clear_check_notes` | efface les remarques de contrôle traitées | oui, sans thread principal |
| `get_pending_messages` | récupère les messages que l'utilisateur a laissés dans la CAO | oui, sans thread principal |
| `list_stored_keys` / `clear_store` | afficher / vider la mémoire de session du pont (listes d'ID d'éléments) | oui |
| `create_from_init` | crée un nouveau `.3d` comme copie d'un modèle (n'écrase jamais) | non, local |
| `open_document` | ouvre un `.3d` via l'association de fichiers de Windows | non, local |
| `wait_for_bridge` | attend que ce fichier précis soit connecté, le vérifie et y lie la session | oui |
| `get_cadwork_api_help` | modules, fonctions et signatures tirés des type stubs | non, local |
| `get_working_examples` | exemples de code vérifiés | non, local |
| `get_detail` | catalogue de détails, **seulement avec un savoir-faire ajouté** | non, local |
| `get_experiences` | expériences tirées d'erreurs précédentes sur cet ordinateur | non, local |
| `record_experience` | consigne ce qui a aidé après une erreur | non, local |

**Créer un nouveau fichier et se connecter :** `create_from_init` →
`open_document` → cliquer une fois sur **Open MCP CAD** (l'utilisateur ou
l'hôte de l'agent) → `wait_for_bridge`. Ce n'est qu'ensuite qu'une tâche
écrit dans le modèle.

## Expériences (sur cet ordinateur uniquement)

Lorsqu'une tâche échoue à cause de son code (Cadwork signale une exception
Python) et qu'une tâche du même type réussit ensuite, le serveur consigne
une **expérience** : type et message d'erreur, la fonction en cause, ce qui
a changé ensuite (appels nouveaux et supprimés, un extrait de code),
versions de Cadwork et du noyau. L'agent ajoute avec `record_experience`
une phrase sur ce qui a aidé. Au démarrage suivant, les expériences les
plus récentes figurent dans la description de `execute_cadwork_command`,
et une erreur déjà rencontrée apporte son expérience dans la réponse.

Le fichier reste sur cet ordinateur ; le serveur ne l'envoie nulle part.
Ce que l'agent en lit (description, réponses) part, comme tout texte
d'outil, chez le fournisseur de son modèle. Le stockage est donc nettoyé —
sans chemins, noms de fichiers, de documents, d'utilisateur ni
d'ordinateur, sans la description de la tâche, sans chaînes de caractères
ni nombres à plusieurs chiffres du code — et
limité (200 entrées, 256 Ko), dans
`%LOCALAPPDATA%\OpenMcpCad\erfahrungen.jsonl`. Autre emplacement :
`OPEN_MCP_CAD_ERFAHRUNGEN=<fichier>` ; `OPEN_MCP_CAD_ERFAHRUNGEN=aus`
désactive la fonction.

## Votre propre savoir-faire

Le savoir intégré dans `open_mcp_cad/knowledge/` porte exclusivement sur
l'**interface cwapi3d**, des pièges que tout le monde rencontre : que
`cut_element_with_plane` conserve le côté opposé à la normale, que
`z_local` détermine la rotation, que les calculs purs n'ont rien à faire
sur le pont. Chaque entrée a été vérifiée sur un vrai modèle.

Vous ajoutez le savoir-faire de votre métier à côté :

```bat
set OPEN_MCP_CAD_KNOWLEDGE=C:\mon-catalogue\knowledge
```

Un tel dossier peut contenir :

| Fichier | Effet |
|---|---|
| `rules.md` | règles transmises avec **chaque** tâche. Les garder courtes, elles coûtent des tokens à chaque appel. Sans `rules.md`, tous les `<domaine>_rules.md` du dossier s'appliquent (ordre alphabétique). |
| `known_issues.json` | `{"issues": [...]}`, ajouté |
| `working_examples.json` | `{"examples": [...]}`, ajouté |
| `detail_catalog.json` | `{"details": [...]}`, ajouté, alimente `get_detail` |

Séparer plusieurs dossiers par `;` (Windows). Un dossier qui n'existe pas
est **signalé** et ignoré. L'avaler en silence voudrait dire qu'on ne
remarque pas pendant des mois que ses propres règles ne sont jamais
arrivées.

## Installation

**Prérequis :** Windows, Cadwork 3D 2026 (les plugins y tournent avec
Python 3.14), Python 3.10–3.13 pour le serveur MCP (s'il manque,
`1_INSTALLIEREN.cmd` installe Python 3.13 via winget après confirmation,
ou, sans winget, directement depuis python.org avec vérification de la
signature).

**En tant qu'utilisateur :** construire le paquet (ou prendre le ZIP dans
les releases), le décompresser, double-cliquer sur `1_INSTALLIEREN.cmd`. Il ouvre
une fenêtre d'installation (depuis le 2026-10-09 ; avec `-Konsole` ou une autre
option, la fenêtre de texte), demande les applications d'IA, puis copie
le plugin dans le profil de Cadwork 2026 (il demande s'il y a plusieurs
profils et ne copie pas dans le profil d'une autre version de Cadwork),
installe le serveur dans
son propre Python et l'inscrit dans les programmes d'IA choisis. Détails :
[`verteilung/ANLEITUNG.fr.md`](verteilung/ANLEITUNG.fr.md).

```bash
python scripts/paket_bauen.py      # -> dist/Open-MCP-CAD-<version>.zip
```

**En tant que développeur :**

```bash
git clone https://github.com/sebastiankoukoui/open-mcp-cad
cd open-mcp-cad
pip install -e .
pip install -e .[stubs]     # facultatif : aide API (type stubs cwapi3d)
```

Copier le dossier `cad_plugin/Open MCP CAD/` dans le profil utilisateur de
Cadwork :

```
C:\Users\Public\Documents\cadwork\userprofil_<ANNÉE>\3d\API.x64\Open MCP CAD\
```

> Seulement dans le profil utilisateur, **pas** en plus dans
> `ProgramData`, sinon le plugin apparaît deux fois dans Cadwork.
>
> Seulement **ce dossier-là**, pas tout `cad_plugin/` : `Open MCP CAD A` à
> `F` sont des dossiers de test (ports fixes, sans fenêtre). Dans le menu
> de Cadwork, ils ressemblent au plugin, mais un clic n'ouvre aucune
> fenêtre.

Vérifier que le dépôt et le profil utilisateur correspondent :

```bash
python scripts/deployment_pruefen.py
```

Configuration de l'hôte (exemple Claude Desktop ; sous Windows `pythonw`
au lieu de `python`, sinon une fenêtre de console s'affiche brièvement à
chaque démarrage) :

```json
{
  "mcpServers": {
    "open-mcp-cad": { "command": "pythonw", "args": ["-m", "open_mcp_cad.server"] }
  }
}
```

Sans `env`, le serveur prend la fenêtre Cadwork connectée (s'il y en a
plusieurs, voir plus haut). Une entrée fixée sur un port ou un document :
`"env": { "OPEN_MCP_CAD_PORT": "53128" }` ou `"env": { "OPEN_MCP_CAD_DOC": "Seeblick" }`.

**Protection contre les confusions :** définir `OPEN_MCP_CAD_EXPECT_DOC`
sur une partie du nom de fichier. Le serveur vérifie alors avant
**chaque** appel que le document attendu est bien ouvert, au lieu
d'exécuter du code dans la mauvaise instance.

## Tests

Tout sans installation de CAO, Cadwork n'est jamais lancé :

```bash
python tests/test_offline.py       # états, pause, arrêt, licence d'écriture, protection du document
python tests/test_wissen.py        # chargeur de savoir-faire
python tests/test_a_prototyp.py    # tableau de bord et chat sans Qt
python tests/test_registry.py      # registre et ports (occupe de vrais ports 53127–53199)
python tests/test_bootstrap.py     # amorçage de fichiers
python tests/test_paket.py         # paquet de distribution
python tests/test_erfahrungen.py   # expériences : nettoyées, limitées, uniquement locales
python scripts/plugins_generieren.py --pruefen
```

Avec PyQt6 s'ajoute `tests/test_a_live.py` : il construit réellement
l'interface et l'utilise, avec des substituts à la place de Cadwork.

## État et limites

**Ce qui fonctionne :** le pont, un nombre quelconque de fenêtres Cadwork
via une seule entrée de menu, le tableau de bord avec connexions,
historique, remarques de contrôle et boîte aux lettres, le chat dans la
même fenêtre, l'amorçage de fichiers, tous les tests. Le panneau et les
messages de l'installateur sont pour l'instant en allemand.

**Une seule fenêtre pour tout :** Claude Code (abonnement), Codex
(abonnement ChatGPT, nécessite la CLI Codex `irm https://chatgpt.com/codex/install.ps1 | iex` ou `npm i -g @openai/codex`) ou
toute interface compatible OpenAI : OpenAI, Anthropic, OpenRouter avec une
clé API (enregistrée dans le gestionnaire d'identification de Windows, le
panneau n'affiche que les quatre derniers caractères), Ollama et LM Studio
en local (le panneau les détecte, les démarre et les installe via winget
après confirmation), ou votre propre adresse (aussi pour Ollama sur un autre
ordinateur). Le clic affiche une petite barre en haut à
droite, au-dessus de la zone de dessin (état, bouton « Chat », « Trennen »,
ancrage ; sans connexion un « × » qui ferme la fenêtre) ; « Chat » ouvre la
même fenêtre, jamais modale, vers le bas ; ancrée, elle forme sa propre
colonne à droite du dessin. Un commutateur « Chat | Briefkasten » (boîte aux
lettres) sépare le chat du plugin du travail avec un programme d'IA
extérieur (tâche en cours, dernières tâches, notes pour l'IA) ; annuler,
rétablir, redessiner et les notes de contrôle sont dans les deux, les
réglages sous « ⋯ ». Pendant que l'IA travaille, un petit affichage
au-dessus de Cadwork montre ce qu'elle fait (« KI zeichnet » avec la
progression, « KI denkt nach », « Wartet auf deine Freigabe », « Cadwork
rechnet »), avec « Anhalten » (arrêter). Des icônes au trait
(Lucide, ISC, voir `THIRD_PARTY_NOTICES.md`) au lieu d'emoji. En haut à
gauche le dossier de travail (les derniers choisis, « Ordner » avec un plus
pour d'autres), sous la saisie une barre comme dans les applis de chat : « + »
pour fichiers et photos (aussi coller et déposer ; images à tous les
fournisseurs), le mode, le modèle et le niveau de réflexion dans une petite
carte (les modèles au-dessus, un curseur en dessous) et, dès la moitié, une
barre qui montre à quel point le contexte est plein. Dans l'historique,
les réponses ont leur propre bulle, les appels d'outils tiennent sur une
ligne dépliable avec des noms lisibles, les heures sont approximatives et
relatives. Le chat commence avec le premier message ; les chats Claude Code
se poursuivent depuis une liste. Le panneau demande les modèles au
fournisseur, les cartes d'autorisation restent les mêmes.

**Limites :**

- **Modèles locaux : avec réserve.** `execute_cadwork_command` fait
  **générer** du Python par le modèle. Les petits modèles (7B/8B) n'y
  arrivent généralement pas, ni à des appels d'outils fiables. La
  connexion fonctionnera, des résultats utiles demandent un modèle
  puissant.
- **Cadwork 3D uniquement.** L'architecture (file d'attente, contrainte du
  thread principal, autorisations) pourrait être transposée à d'autres
  CAO dotées d'une API Python. Cela n'a pas été fait.
- Les type stubs proviennent de Cadwork 2025. `get_cadwork_api_help` peut
  ne pas connaître les fonctions plus récentes. Les vrais appels passent
  par les modules intégrés de la CAO et n'en sont pas affectés.

## Sécurité

- Le pont écoute exclusivement sur `127.0.0.1` et n'est pas accessible de
  l'extérieur.
- Le code exécuté est filtré contre l'import de `os`, `subprocess`,
  `shutil`, `socket`, `urllib`, `requests` et `__import__`. C'est une
  liste de blocage faite au mieux, **pas un bac à sable** : donner au
  modèle l'accès à sa CAO, c'est lui donner l'accès à sa CAO.
- Le chat connaît quatre modes : « Nur lesen » (lecture seule)
  refuse sans demander tout ce qui modifie quelque chose, « Fragen »
  (demander, par défaut) affiche une carte avant chaque modification (une
  fois par type jusqu'au message suivant), « Cadwork frei » (Cadwork libre)
  laisse Cadwork travailler sans carte et demande pour tout ce qui est à
  l'extérieur comme « Fragen », « Alles automatisch » (tout automatique)
  ne demande rien et
  ne survit jamais à un redémarrage. Dans chaque mode, chaque appel figure
  dans l'historique : un automatisme qui ne laisse aucune trace serait pire
  que toutes les questions.
- Si l'autorisation tombe en panne, rien n'est exécuté. La barrière se
  ferme, elle ne s'ouvre pas.

## Licence

[AGPL-3.0](LICENSE). Quiconque distribue une version modifiée
d'open-mcp-cad ou l'exploite comme service transmet les modifications sous
la même licence.

Les contributions nécessitent un [CLA](CLA.md) (en allemand).

**Le nom et le logo ne font pas partie de la licence.** Forker est
expressément autorisé, appeler le fork « Open MCP CAD » ne l'est pas.

*Cadwork est une marque de cadwork informatik AG. Open MCP CAD est un
projet indépendant et n'a aucun lien avec cadwork.*

Le [README](README.md) allemand fait foi.
