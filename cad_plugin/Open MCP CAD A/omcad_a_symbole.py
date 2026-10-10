# -*- coding: utf-8 -*-
"""Strich-Symbole fuer Dock und Chatfenster (Rueckmeldung 2026-09-28).

Die Emoji im Dock wirkten "KI-haft", und das ✎ fuer "Neuer Chat" war kaum
zu erkennen. Statt ihrer Strich-Symbole aus Lucide (https://lucide.dev),
Fassung 1.8.0, die Pfade unveraendert aus den ESM-Dateien des Pakets
`lucide` uebernommen (nur die Knoten, die Huelle setzt `svg()`).

Gezeichnet ueber QtSvg (PyQt6 oder, in Cadwork 2025, PyQt5 — ueber die
Qt-Schicht `omcad_qt`, seit 2026-10-10) in der Farbe des Themas. Ob QtSvg in
Cadworks PyQt6 6.8.1 bzw. im PyQt5 von Cadwork 2025 vorhanden ist, ist NICHT
gemessen — fehlt es (oder scheitert
irgendetwas beim Zeichnen), liefert `symbol()` None und der Aufrufer zeigt
seinen Text (`knopf_setzen`). Nichts hier wirft.

Kein Zustand ausser einem Zwischenspeicher der fertigen Bilder: das
Dashboard laedt dieses Modul mit jedem Klick frisch (wie omcad_a_lokal).

Lizenz der Symbole (Lucide, ISC; einige Symbole stammen aus Feather, MIT).
Der Text steht hier, weil diese Datei mit dem Plugin weitergegeben wird;
dieselben Texte stehen in THIRD_PARTY_NOTICES.md im Repo.

    ISC License

    Copyright (c) 2026 Lucide Icons and Contributors

    Permission to use, copy, modify, and/or distribute this software for any
    purpose with or without fee is hereby granted, provided that the above
    copyright notice and this permission notice appear in all copies.

    THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
    WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
    MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
    ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
    WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
    ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
    OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

    ---

    The following Lucide icons are derived from the Feather project
    (of those used here: arrow-down, arrow-up, check, chevron-down,
    chevron-right, chevron-up, minus, plus, search, square, terminal,
    triangle-alert (there: alert-triangle), x, arrow-left, ellipsis
    (there: more-horizontal), minimize-2; the full list is in the
    LICENSE file of the lucide package):

    The MIT License (MIT) (for the icons listed above)

    Copyright (c) 2013-present Cole Bemis

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the
    "Software"), to deal in the Software without restriction, including
    without limitation the rights to use, copy, modify, merge, publish,
    distribute, sublicense, and/or sell copies of the Software, and to
    permit persons to whom the Software is furnished to do so, subject to
    the following conditions:

    The above copyright notice and this permission notice shall be included
    in all copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
    OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
    IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY
    CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
    TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
    SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

SCHNITTSTELLE = 1

#: Die Huelle jedes Symbols (wie `defaultAttributes` von lucide 1.8.0);
#: `%(farbe)s` ist die Strichfarbe, `%(strich)s` die Strichbreite,
#: `%(fuellung)s` sonst "none" (gefuellt nur auf Wunsch, `fuellen`).
HUELLE = ('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
          'viewBox="0 0 24 24" fill="%(fuellung)s" stroke="%(farbe)s" '
          'stroke-width="%(strich)s" stroke-linecap="round" '
          'stroke-linejoin="round">%(knoten)s</svg>')

#: Name (wie bei lucide) -> die Knoten des Symbols.
SYMBOLE = {
    'square-pen':
        '<path d="M12 3H5a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-'
        '7"/><path d="M18.375 2.625a1 1 0 0 1 3 3l-9.013 9.014a2 2 0 0 1-.8'
        '53.505l-2.873.84a.5.5 0 0 1-.62-.62l.84-2.873a2 2 0 0 1 .506-.852z'
        '"/>',
    'circle-stop':
        '<circle cx="12" cy="12" r="10"/><rect x="9" y="9" width="6" height'
        '="6" rx="1"/>',
    'square':
        '<rect width="18" height="18" x="3" y="3" rx="2"/>',
    'settings':
        '<path d="M9.671 4.136a2.34 2.34 0 0 1 4.659 0 2.34 2.34 0 0 0 3.31'
        '9 1.915 2.34 2.34 0 0 1 2.33 4.033 2.34 2.34 0 0 0 0 3.831 2.34 2.'
        '34 0 0 1-2.33 4.033 2.34 2.34 0 0 0-3.319 1.915 2.34 2.34 0 0 1-4.'
        '659 0 2.34 2.34 0 0 0-3.32-1.915 2.34 2.34 0 0 1-2.33-4.033 2.34 2'
        '.34 0 0 0 0-3.831A2.34 2.34 0 0 1 6.35 6.051a2.34 2.34 0 0 0 3.319'
        '-1.915"/><circle cx="12" cy="12" r="3"/>',
    'folder':
        '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-'
        '.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    'folder-open':
        '<path d="m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.'
        '54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 '
        '0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
    'folder-plus':
        '<path d="M12 10v6"/><path d="M9 13h6"/><path d="M20 20a2 2 0 0 0 2'
        '-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3'
        'H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    'plus':
        '<path d="M5 12h14"/><path d="M12 5v14"/>',
    'paperclip':
        '<path d="m16 6-8.414 8.586a2 2 0 0 0 2.829 2.829l8.414-8.586a4 4 0'
        ' 1 0-5.657-5.657l-8.379 8.551a6 6 0 1 0 8.485 8.485l8.379-8.551"/>',
    'clipboard-paste':
        '<path d="M11 14h10"/><path d="M16 4h2a2 2 0 0 1 2 2v1.344"/><path '
        'd="m17 18 4-4-4-4"/><path d="M8 4H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2'
        'h12a2 2 0 0 0 1.793-1.113"/><rect x="8" y="2" width="8" height="4"'
        ' rx="1"/>',
    'eye':
        '<path d="M2.062 12.348a1 1 0 0 1 0-.696 10.75 10.75 0 0 1 19.876 0'
        ' 1 1 0 0 1 0 .696 10.75 10.75 0 0 1-19.876 0"/><circle cx="12" cy='
        '"12" r="3"/>',
    'hand':
        '<path d="M18 11V6a2 2 0 0 0-2-2a2 2 0 0 0-2 2"/><path d="M14 10V4a'
        '2 2 0 0 0-2-2a2 2 0 0 0-2 2v2"/><path d="M10 10.5V6a2 2 0 0 0-2-2a'
        '2 2 0 0 0-2 2v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c'
        '-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>',
    'hammer':
        '<path d="m15 12-9.373 9.373a1 1 0 0 1-3.001-3L12 9"/><path d="m18 '
        '15 4-4"/><path d="m21.5 11.5-1.914-1.914A2 2 0 0 1 19 8.172v-.344a'
        '2 2 0 0 0-.586-1.414l-1.657-1.657A6 6 0 0 0 12.516 3H9l1.243 1.243'
        'A6 6 0 0 1 12 8.485V10l2 2h1.172a2 2 0 0 1 1.414.586L18.5 14.5"/>',
    'zap':
        '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92'
        ' 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.8'
        '6-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
    'arrow-up':
        '<path d="m5 12 7-7 7 7"/><path d="M12 19V5"/>',
    'arrow-down':
        '<path d="M12 5v14"/><path d="m19 12-7 7-7-7"/>',
    'message-square':
        '<path d="M22 17a2 2 0 0 1-2 2H6.828a2 2 0 0 0-1.414.586l-2.202 2.2'
        '02A.71.71 0 0 1 2 21.286V5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2z"/>',
    'chevron-right':
        '<path d="m9 18 6-6-6-6"/>',
    'chevron-down':
        '<path d="m6 9 6 6 6-6"/>',
    'chevron-up':
        '<path d="m18 15-6-6-6 6"/>',
    'triangle-alert':
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2'
        ' 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    'ban':
        '<circle cx="12" cy="12" r="10"/><path d="M4.929 4.929 19.07 19.071'
        '"/>',
    'minus':
        '<path d="M5 12h14"/>',
    'x':
        '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    'maximize-2':
        '<path d="M15 3h6v6"/><path d="m21 3-7 7"/><path d="m3 21 7-7"/><pa'
        'th d="M9 21H3v-6"/>',
    'panel-right':
        '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18'
        '"/>',
    'grip-vertical':
        '<circle cx="9" cy="12" r="1"/><circle cx="9" cy="5" r="1"/><circle'
        ' cx="9" cy="19" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="'
        '15" cy="5" r="1"/><circle cx="15" cy="19" r="1"/>',
    'sparkles':
        '<path d="M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.5'
        '94 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.59'
        '4 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.59'
        '4-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594'
        '-1.594z"/><path d="M20 2v4"/><path d="M22 4h-4"/><circle cx="4" cy'
        '="20" r="2"/>',
    'check':
        '<path d="M20 6 9 17l-5-5"/>',
    'image':
        '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx'
        '="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6'
        ' 21"/>',
    'file-text':
        '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704'
        '.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M'
        '14 2v5a1 1 0 0 0 1 1h5"/><path d="M10 9H8"/><path d="M16 13H8"/><p'
        'ath d="M16 17H8"/>',
    'refresh-cw':
        '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><pat'
        'h d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.'
        '74-2.74L3 16"/><path d="M8 16H3v5"/>',
    'plug':
        '<path d="M12 22v-5"/><path d="M15 8V2"/><path d="M17 8a1 1 0 0 1 1'
        ' 1v4a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V9a1 1 0 0 1 1-1z"/><path d="M9'
        ' 8V2"/>',
    'pin':
        '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A'
        '2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0'
        '-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0'
        '-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
    'eraser':
        '<path d="M21 21H8a2 2 0 0 1-1.42-.587l-3.994-3.999a2 2 0 0 1 0-2.8'
        '28l10-10a2 2 0 0 1 2.829 0l5.999 6a2 2 0 0 1 0 2.828L12.834 21"/><'
        'path d="m5.082 11.09 8.828 8.828"/>',
    'inbox':
        '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.'
        '45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 '
        '0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    'mail':
        '<path d="m22 7-8.991 5.727a2 2 0 0 1-2.009 0L2 7"/><rect x="2" y="'
        '4" width="20" height="16" rx="2"/>',
    'layers':
        '<path d="M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.'
        '58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z"/><path d="M2 '
        '12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 2'
        '2 12"/><path d="M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8'
        '.58-3.9A1 1 0 0 0 22 17"/>',
    'undo-2':
        '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5a'
        '5.5 5.5 0 0 1-5.5 5.5H11"/>',
    'redo-2':
        '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5A5.5 5.5 0 0 0 4 14.5A'
        '5.5 5.5 0 0 0 9.5 20H13"/>',
    'book-open':
        '<path d="M12 7v14"/><path d="M3 18a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h5'
        'a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5a1 1 0 0 1 1 1v13a1 1 0 0 1-1 1h-6a3'
        ' 3 0 0 0-3 3 3 3 0 0 0-3-3z"/>',
    'ruler':
        '<path d="M21.3 15.3a2.4 2.4 0 0 1 0 3.4l-2.6 2.6a2.4 2.4 0 0 1-3.4'
        ' 0L2.7 8.7a2.41 2.41 0 0 1 0-3.4l2.6-2.6a2.41 2.41 0 0 1 3.4 0Z"/>'
        '<path d="m14.5 12.5 2-2"/><path d="m11.5 9.5 2-2"/><path d="m8.5 6'
        '.5 2-2"/><path d="m17.5 15.5 2-2"/>',
    'archive':
        '<rect width="20" height="5" x="2" y="3" rx="1"/><path d="M4 8v11a2'
        ' 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
    'lightbulb':
        '<path d="M15 14c.2-1 .7-1.7 1.5-2.5 1-.9 1.5-2.2 1.5-3.5A6 6 0 0 0'
        ' 6 8c0 1 .2 2.2 1.5 3.5.7.7 1.3 1.5 1.5 2.5"/><path d="M9 18h6"/><'
        'path d="M10 22h4"/>',
    'file-plus':
        '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704'
        '.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M'
        '14 2v5a1 1 0 0 0 1 1h5"/><path d="M9 15h6"/><path d="M12 18v-6"/>',
    'hourglass':
        '<path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 '
        '0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path '
        'd="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 '
        '6.172V2"/>',
    'bolt':
        '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0'
        ' 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/'
        '><circle cx="12" cy="12" r="4"/>',
    'search':
        '<path d="m21 21-4.34-4.34"/><circle cx="11" cy="11" r="8"/>',
    'rotate-ccw':
        '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path'
        ' d="M3 3v5h5"/>',
    'terminal':
        '<path d="M12 19h8"/><path d="m4 17 6-6-6-6"/>',
    'globe':
        '<circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 2'
        '0 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/>',
    'pencil':
        '<path d="M21.174 6.812a1 1 0 0 0-3.986-3.987L3.842 16.174a2 2 0 0 '
        '0-.5.83l-1.321 4.352a.5.5 0 0 0 .623.622l4.353-1.32a2 2 0 0 0 .83-'
        '.497z"/><path d="m15 5 4 4"/>',
    'list-checks':
        '<path d="M13 5h8"/><path d="M13 12h8"/><path d="M13 19h8"/><path d'
        '="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/>',
    'wrench':
        '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.106-3'
        '.105c.32-.322.863-.22.983.218a6 6 0 0 1-8.259 7.057l-7.91 7.91a1 1'
        ' 0 0 1-2.999-3l7.91-7.91a6 6 0 0 1 7.057-8.259c.438.12.54.662.219.'
        '984z"/>',
    'pause':
        '<rect x="14" y="3" width="5" height="18" rx="1"/><rect x="5" y="3"'
        ' width="5" height="18" rx="1"/>',
    'play':
        '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.'
        '458l-12 7A2 2 0 0 1 5 19z"/>',
    'unplug':
        '<path d="m19 5 3-3"/><path d="m2 22 3-3"/><path d="M6.3 20.3a2.4 2'
        '.4 0 0 0 3.4 0L12 18l-6-6-2.3 2.3a2.4 2.4 0 0 0 0 3.4Z"/><path d="'
        'M7.5 13.5 10 11"/><path d="M10.5 16.5 13 14"/><path d="m12 6 6 6 2'
        '.3-2.3a2.4 2.4 0 0 0 0-3.4l-2.6-2.6a2.4 2.4 0 0 0-3.4 0Z"/>',
    # K12 (2026-10-07): Kopf, Hinweise, Menue "Mehr", Denkstufe, Zurueck
    'flag':
        '<path d="M4 22V4a1 1 0 0 1 .4-.8A6 6 0 0 1 8 2c3 0 5 2 7.333 2q2 0'
        ' 3.067-.8A1 1 0 0 1 20 4v10a1 1 0 0 1-.4.8A6 6 0 0 1 16 16c-3 0-5-'
        '2-8-2a6 6 0 0 0-4 1.528"/>',
    'ellipsis':
        '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><cir'
        'cle cx="5" cy="12" r="1"/>',
    'brain':
        '<path d="M12 18V5"/><path d="M15 13a4.17 4.17 0 0 1-3-4 4.17 4.17 '
        '0 0 1-3 4"/><path d="M17.598 6.5A3 3 0 1 0 12 5a3 3 0 1 0-5.598 1.'
        '5"/><path d="M17.997 5.125a4 4 0 0 1 2.526 5.77"/><path d="M18 18a'
        '4 4 0 0 0 2-7.464"/><path d="M19.967 17.483A4 4 0 1 1 12 18a4 4 0 '
        '1 1-7.967-.517"/><path d="M6 18a4 4 0 0 1-2-7.464"/><path d="M6.00'
        '3 5.125a4 4 0 0 0-2.526 5.77"/>',
    'panel-right-close':
        '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M15 3v18'
        '"/><path d="m8 9 3 3-3 3"/>',
    'arrow-left':
        '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    # Gegenpruefung Laien-Sicht K12: Abdocken (Gegenstueck zu maximize-2)
    'minimize-2':
        '<path d="m14 10 7-7"/><path d="M20 10h-6V4"/><path d="m3 21 7-7"/>'
        '<path d="M4 14h6v6"/>',
}

_CACHE = {}
_SVG = []          # [Modul QtSvg] oder [None], einmal je Laden gefragt


def svg(name, farbe="#1d1d1f", strich=2, fuellen=False):
    """Das ganze SVG eines Symbols als Text — None, wenn es das Symbol nicht
    gibt."""
    knoten = SYMBOLE.get(name)
    if knoten is None:
        return None
    return HUELLE % {"farbe": farbe, "strich": strich, "knoten": knoten,
                     "fuellung": farbe if fuellen else "none"}


def qtsvg():
    """QtSvg der Qt-Schicht — oder None, wenn es fehlt (in Cadwork nicht
    gemessen)."""
    if not _SVG:
        try:
            from omcad_qt import QtSvg
            _SVG.append(QtSvg)
        except Exception:                               # noqa: BLE001
            _SVG.append(None)
    return _SVG[0]


def aufloesung():
    """Wie fein ein Symbol gezeichnet wird: mindestens doppelt, sonst die
    HOECHSTE Pixeldichte aller Bildschirme (ein Fenster kann auf einen
    zweiten Bildschirm mit 250 % wandern, dort waere ein Bild fuer den
    Hauptbildschirm weich). Wirft nie."""
    dpr = 2.0
    try:
        from omcad_qt.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        if app is not None:
            for schirm in app.screens():
                dpr = max(dpr, float(schirm.devicePixelRatio()))
    except Exception:                                   # noqa: BLE001
        pass
    return min(dpr, 4.0)


def pixmap(name, farbe="#1d1d1f", groesse=16, strich=2, fuellen=False):
    """Das Symbol als QPixmap (scharf auch bei 150/200 %) — oder None."""
    schluessel = ("p", name, farbe, groesse, strich, fuellen)
    if schluessel in _CACHE:
        return _CACHE[schluessel]
    bild = None
    try:
        Q = qtsvg()
        text = svg(name, farbe, strich, fuellen)
        if Q is not None and text is not None:
            from omcad_qt.QtCore import QByteArray, QRectF, Qt
            from omcad_qt.QtGui import QPainter, QPixmap
            dpr = aufloesung()
            leser = Q.QSvgRenderer(QByteArray(text.encode("utf-8")))
            if leser.isValid():
                seite = int(round(groesse * dpr))
                pm = QPixmap(seite, seite)
                pm.fill(Qt.GlobalColor.transparent)
                maler = QPainter(pm)
                try:
                    maler.setRenderHint(QPainter.RenderHint.Antialiasing)
                    leser.render(maler, QRectF(0, 0, seite, seite))
                finally:
                    maler.end()
                pm.setDevicePixelRatio(dpr)
                bild = pm
    except Exception:                                   # noqa: BLE001
        bild = None
    _CACHE[schluessel] = bild
    return bild


def symbol(name, farbe="#1d1d1f", groesse=16, strich=2, fuellen=False):
    """Das Symbol als QIcon — oder None (dann Text zeigen)."""
    schluessel = ("i", name, farbe, groesse, strich, fuellen)
    if schluessel in _CACHE:
        return _CACHE[schluessel]
    ikone = None
    try:
        pm = pixmap(name, farbe, groesse, strich, fuellen)
        if pm is not None:
            from omcad_qt.QtGui import QIcon
            ikone = QIcon(pm)
            # Ein ausgeschalteter Knopf zeichnet sein Symbol grau.
            grau = pixmap(name, "#b0b0b5", groesse, strich, fuellen)
            if grau is not None:
                ikone.addPixmap(grau, QIcon.Mode.Disabled)
    except Exception:                                   # noqa: BLE001
        ikone = None
    _CACHE[schluessel] = ikone
    return ikone


def knopf_setzen(knopf, name, ersatz="", text=None, farbe="#1d1d1f",
                 groesse=16, fuellen=False):
    """`knopf` bekommt das Symbol `name` (und `text`, wenn angegeben). Gibt
    es kein Symbol (QtSvg fehlt, Name unbekannt), steht `ersatz` als Text da
    (bzw. `text`, wenn es einen gibt). -> True, wenn das Symbol steht. Wirft
    nie."""
    try:
        ikone = symbol(name, farbe, groesse, fuellen=fuellen)
        if ikone is not None:
            from omcad_qt.QtCore import QSize
            knopf.setIcon(ikone)
            knopf.setIconSize(QSize(groesse, groesse))
            knopf.setText(text or "")
            return True
        knopf.setText(text or ersatz)
    except Exception:                                   # noqa: BLE001
        try:
            knopf.setText(text or ersatz)
        except Exception:                               # noqa: BLE001
            pass
    return False


def label_setzen(label, name, ersatz="", farbe="#1d1d1f", groesse=16):
    """Ein QLabel zeigt das Symbol — sonst `ersatz` als Text. -> True, wenn
    das Symbol steht. Wirft nie."""
    try:
        pm = pixmap(name, farbe, groesse)
        if pm is not None:
            label.setPixmap(pm)
            return True
        label.setText(ersatz)
    except Exception:                                   # noqa: BLE001
        try:
            label.setText(ersatz)
        except Exception:                               # noqa: BLE001
            pass
    return False
