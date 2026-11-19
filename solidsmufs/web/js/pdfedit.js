// Acrobat's tools on the PDF page view: comments and markups, filling in forms and signing, editing the pages'
// own text and pictures, organizing pages, and redacting. The document's worker makes every change with MuPDF
// (kernel/pdfedit.py) and draws the pages again; this draws only what's being worked on over them: the selected
// comment's handles, the form's fields to type in, and shapes while they're dragged out.
// Places are in the page's points as shown (the page view's _pagePoint and _rectStyle), whatever the view's turn.
import { api } from './api.js';
import { h, toast, menu, modal, closeMenus, menuOpen, copyText, typingKey } from './ui.js';
import { PRODUCT } from './consts.js';

const POINT = 96 / 72;
const I = (d) => `<svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const ICON = {
  select: I('<path d="M5 3l10 6-4.5 1.3L13 15l-2 1-2.4-4.7L5 14z"/>'),
  note: I('<path d="M3.5 4h13v9.5H9L5.5 16.5v-3h-2z"/>'),
  text: I('<rect x="3" y="4" width="14" height="12" rx="1"/><path d="M7 8h6M10 8v5"/>'),
  typewriter: I('<path d="M5 5h10M10 5v10"/><path d="M3 17.5h14" stroke-dasharray="2 2"/>'),
  highlight: I('<path d="M3 17h14" stroke="#e8b800" stroke-width="3"/><path d="M6.5 13l5.5-9 3 2-5.5 9h-3z"/>'),
  underline: I('<path d="M6 3.5v5.5a4 4 0 008 0V3.5M4.5 16.5h11"/>'),
  strikeout: I('<path d="M3.5 10h13M13.5 6.2C13 4.7 11.7 3.8 10 3.8 8 3.8 6.5 4.9 6.5 6.6M6.5 13.6c.5 1.5 1.9 2.6 3.5 2.6 2 0 3.6-1.1 3.6-2.9"/>'),
  squiggly: I('<path d="M3 15l2-2 2 2 2-2 2 2 2-2 2 2 2-2M7 11V4h6"/>'),
  pen: I('<path d="M3 16c3-1 2.2-5 5-6s3 3 7.5-2"/><path d="M14 3.5l2.5 2.5"/>'),
  rect: I('<rect x="3.5" y="5" width="13" height="10" rx="1"/>'),
  ellipse: I('<ellipse cx="10" cy="10" rx="7" ry="5"/>'),
  cloud: I('<path d="M5.5 15.5a2.6 2.6 0 01-.3-5.2 3.4 3.4 0 016.5-1.6 2.9 2.9 0 013.9 2.7 2.1 2.1 0 01-.6 4.1z"/>'),
  line: I('<path d="M4 16L16 4"/>'),
  arrow: I('<path d="M4 16L16 4M9.5 4H16v6.5"/>'),
  stamp: I('<path d="M8 3h4v5.5l2.5 2V13h-9v-2.5l2.5-2zM4.5 16h11"/>'),
  check: I('<path d="M4 10.5l4 4 8-9"/>'),
  cross: I('<path d="M5 5l10 10M15 5L5 15"/>'),
  dot: '<svg viewBox="0 0 20 20" width="18" height="18"><circle cx="10" cy="10" r="3.5" fill="currentColor"/></svg>',
  date: I('<rect x="3.5" y="5" width="13" height="11" rx="1"/><path d="M3.5 8.5h13M7 3v3.5M13 3v3.5"/>'),
  sign: I('<path d="M3 13.5c2-6 4.2-8.2 5-6.2s-2 6.2.2 6.2 3-5 5-4 .8 3 3.8 2M3 17h14"/>'),
  flatten: I('<path d="M3 13l7 3.5 7-3.5M3 9.5L10 6l7 3.5-7 3.5z"/>'),
  editText: I('<path d="M3.5 5h8M7.5 5v11"/><path d="M11.5 16.5l.8-2.8 4.5-4.5 2 2-4.5 4.5z"/>'),
  addText: I('<path d="M3.5 5h9M8 5v11M14.5 12v6M11.5 15h6"/>'),
  editImage: I('<rect x="2.5" y="4" width="15" height="12" rx="1"/><path d="M2.5 13l4-4 3 3 2-2 6 6"/><circle cx="13" cy="8" r="1.3"/>'),
  addImage: I('<rect x="2.5" y="4" width="11" height="9" rx="1"/><path d="M2.5 11l3-3 3 3M15.5 11.5v6M12.5 14.5h6"/>'),
  crop: I('<path d="M6 2.5V14h11.5M2.5 6H14v11.5"/>'),
  redact: I('<rect x="3" y="7" width="14" height="6" fill="currentColor"/>'),
  redactText: I('<path d="M3 6.5h14"/><rect x="3" y="10" width="14" height="5" fill="currentColor"/>'),
  undo: I('<path d="M7.5 5L4 8.5 7.5 12"/><path d="M4 8.5h8a4 4 0 010 8H9"/>'),
  redo: I('<path d="M12.5 5L16 8.5 12.5 12"/><path d="M16 8.5H8a4 4 0 000 8h3"/>'),
  save: I('<path d="M4 3.5h10l2.5 2.5v10.5H4z"/><path d="M7 3.5v4h6v-4M7 16.5v-5h6v5"/>'),
  comments: I('<path d="M3 4h10v7H7.5L4.5 13.5V11H3zM14.5 7.5H17v7h-1.5v2.5L12.5 14.5H8.5V13"/>'),
};
ICON.trash = I('<path d="M4.5 6h11M8 6V4h4v2M6 6l.7 10h6.6L14 6M8.5 8.5v5M11.5 8.5v5"/>');
ICON.copy = I('<rect x="7" y="7" width="9" height="9" rx="1"/><path d="M13 7V4.5H4.5V13H7"/>');
// one key picks a comment tool, as in Acrobat (R turns the pages, so the rectangle is B for box)
const KEYS = { v: 'select', n: 'note', t: 'text', h: 'highlight', u: 'underline', k: 'strikeout', x: 'strikeText', d: 'pen', b: 'rect', e: 'ellipse', c: 'cloud', l: 'line', a: 'arrow' };
const KEY_TABS = new Set(['comment', 'fill', 'edit', 'redact']); // the tabs where those keys work
const KEY_OF = Object.fromEntries(Object.entries(KEYS).map(([k, v]) => [v, k.toUpperCase()]));
const QUICK = ['#e02020', '#ffd400', '#2bb24c', '#2858cf', '#000000']; // the colors on a selected comment's own bar: five of COLORS, and a swatch there opens the rest
const PLACE = { stamp: [160, 52], sign: [150, 50], initials: [60, 36], addImage: [150, 100] }; // placed by a click: points
const CLONABLE = new Set(['ink', 'line', 'polygon', 'polyline', 'strikeout', 'rect', 'ellipse', 'text', 'note', 'stamp']);
// A mark on words (highlight, underline, squiggly, strikethrough) belongs to those words: it's clicked to select it
// (to recolor, note or delete), and never dragged, sized, nudged or copied off them. A cross-out line is the one
// kind that may lie anywhere, so it moves like a drawn line.
const MARKS = new Set(['highlight', 'underline', 'squiggly', 'strikeout']);
const pinned = (a) => !!a && MARKS.has(a.kind) && a.subject !== 'Strike through';
const canClone = (a) => CLONABLE.has(a.kind) && !pinned(a);
// a comment as a record of the selection, and a test for "the same thing" among such records
const selOf = (a) => ({ type: 'annot', page: a.page, id: a.id, rect: a.rect, a });
const same = (x) => (s) => s.type === (x.type || 'annot') && s.page === x.page && s.id === x.id;
// What Copy and Cut keep: the comments themselves, as the worker hands them over (annot_copy), so they paste after the
// ones they came from are gone, on any page, and into another document (which is why it's kept here and not with
// an editor's document). { clips, doc, page, n }: n counts the pastes, each a step on from the last
let CLIP = null;
// a highlighter's colors: light ones, that words still read through (black would hide them, white would show nothing)
const HILITE = ['#ffd400', '#7be07b', '#7fd3ff', '#ff9ad5', '#ffb347', '#c9a7ff'];
Object.assign(ICON, {
  fText: I('<rect x="2.5" y="6" width="15" height="8" rx="1"/><path d="M5.5 8.5v3M4.5 8.5h2M4.5 11.5h2"/>'),
  fMulti: I('<rect x="2.5" y="3.5" width="15" height="13" rx="1"/><path d="M5 7h10M5 10h10M5 13h6"/>'),
  fCheck: I('<rect x="4" y="4" width="12" height="12" rx="1.5"/><path d="M7 10.2l2.2 2.3L13.2 7.6"/>'),
  fCombo: I('<rect x="2.5" y="6" width="15" height="8" rx="1"/><path d="M12 6v8M13.6 9.3l1.2 1.4 1.2-1.4"/>'),
  fProps: I('<path d="M4 6h7M14 6h2M4 10h2M9 10h7M4 14h9M16 14h0"/><circle cx="12.5" cy="6" r="1.5"/><circle cx="7.5" cy="10" r="1.5"/><circle cx="14.5" cy="14" r="1.5"/>'),
  fDelete: I('<path d="M4.5 6h11M8 6V4.5h4V6M6 6l.7 9.5h6.6L14 6M8.5 8.5v5M11.5 8.5v5"/>'),
  // each tool its own picture: initials aren't a signature, finding the blanks isn't a text field, and so on
  initials: I('<path d="M5.5 5.5h3v6a2 2 0 01-4 0"/><path d="M15.2 6.6c-.6-.8-1.5-1.3-2.6-1.3-1.4 0-2.3.8-2.3 1.9 0 2.6 5 1.4 5 4.2 0 1.2-1 2-2.5 2-1.2 0-2.1-.5-2.7-1.3"/><path d="M3 17h14"/>'),
  formAuto: I('<path d="M4 16.5l9-9M11.5 6l3 3"/><path d="M15.5 2.5v3M14 4h3M6 3v2M5 4h2M16.5 11.5v2M15.5 12.5h2"/>'),
  redactFind: I('<circle cx="8.5" cy="8.5" r="4.8"/><path d="M12 12l4.5 4.5"/><path d="M6.3 8.5h4.4" stroke-width="2.6" stroke-linecap="butt"/>'),
  strikeText: I('<rect x="3.5" y="6" width="13" height="8" rx="1" stroke-dasharray="2 2"/><path d="M1.8 10h16.4" stroke-width="2"/>'),
  rotateLeft: I('<rect x="8" y="8" width="8.5" height="9" rx="1"/><path d="M10.5 3H10a6 6 0 00-6 6"/><path d="M1.6 6.8L4 9.3l2.6-2.2"/>'),
  rotateRight: I('<rect x="3.5" y="8" width="8.5" height="9" rx="1"/><path d="M9.5 3h.5a6 6 0 016 6"/><path d="M18.4 6.8L16 9.3l-2.6-2.2"/>'),
  turnView: I('<path d="M15.6 10a5.6 5.6 0 11-1.7-4"/><path d="M14.3 2.6v3.6h-3.6"/><circle cx="10" cy="10" r="1.3" fill="currentColor"/>'),
  panelLeft: I('<rect x="3" y="4" width="14" height="12" rx="1.5"/><path d="M8 4v12M5 7h1.2M5 9.5h1.2"/>'),
  print: I('<path d="M6 7V3.5h8V7"/><rect x="3.5" y="7" width="13" height="6.5" rx="1"/><path d="M6 11.5h8v5H6z"/>'),
  up: I('<path d="M5.5 12.5L10 8l4.5 4.5"/>'),
  down: I('<path d="M5.5 8l4.5 4.5L14.5 8"/>'),
});
export { ICON }; // (the page view's Document bar draws its buttons with these too)
// The tabs of the tool bar, in the order a shop reaches for them. tools: the buttons, left to right ('|' is a gap).
// more: the tab's rare commands, under "More tools" at the bar's right end. Balloon is a tab like the rest, but its
// row of tools is the inspection list's own (balloons.js); Pages' buttons come from PAGE_CMDS.
const SETS = [
  { id: 'comment', label: 'Comment', tools: ['select', '|', 'highlight', 'strikeText', 'strikeout', 'underline', '|', 'text', 'note', '|', 'pen', 'arrow', 'line', 'rect', 'ellipse', 'cloud', '|', 'stamp'], more: ['squiggly'] },
  { id: 'balloon', label: 'Balloon', tools: [], more: [] },
  { id: 'pages', label: 'Pages', tools: [], more: ['enhance'] },
  { id: 'fill', label: 'Fill & Sign', tools: ['select', '|', 'typewriter', 'check', 'cross', 'dot', 'date', '|', 'sign', 'initials'], more: ['flatten'] },
  { id: 'edit', label: 'Edit', tools: ['select', '|', 'editText', 'addText', 'editImage', 'addImage'], more: ['watermark'] },
  { id: 'form', label: 'Forms', tools: ['select', '|', 'formAuto', '|', 'fText', 'fMulti', 'fCheck', 'fCombo', '|', 'fProps', 'fDelete'], more: ['formClear'] },
  { id: 'redact', label: 'Redact', tools: ['select', '|', 'redactText', 'redact', 'redactFind', '|', 'redactLeaves', 'redactApply'], more: ['scrub'] },
];
const SET_TIP = { comment: 'Mark up the print: highlight, cross out, notes, shapes and stamps', balloon: 'Number what there is to inspect on the print, list it with its limits, and write the inspection report',
  pages: 'Rotate, add, take out, extract and crop pages', fill: 'Fill in a form that has no fields, and sign it', edit: "Change the pages' own words and pictures",
  form: 'Make the document fillable: fields to type in and tick', redact: 'Take words and pictures out of the pages for good' };
// what acts on the whole document: the last section of every tab's "More tools" menu, always the same four
const WHOLE_DOC = ['enhance', 'watermark', 'flatten', 'scrub'];
// label: its name everywhere. short: how to use it, in one line (the options strip and the status bar). tip: the
// whole story, in its tooltip. text: its button shows the name beside the icon. action: it does something at once.
const TOOLS = {
  select: { label: 'Select', short: 'Drag across words to select them, click a comment to select it, drag paper to pan',
    tip: 'Drag across text to select it (Ctrl+C copies; right-click for more; in the Edit tab, Delete takes it out of the page). Click a comment to select it: drag it to move it, its handles to size it, double-click to edit it. Shift+click adds a comment to the ones selected, and Ctrl+drag over paper takes every comment in the box: they move, recolor and delete together. Tab goes to the next comment. Drag bare paper to pan.' },
  note: { label: 'Sticky note', short: 'Click where the note goes', tip: 'Click to add a note', text: true },
  text: { label: 'Text box', short: 'Drag a box (or click), then type', tip: 'Drag (or click) to add a text box', text: true },
  typewriter: { label: 'Type on page', short: 'Click and type, right on the page', tip: 'Click and type: fill in a form that has no fields', icon: 'typewriter', text: true },
  highlight: { label: 'Highlight', short: 'Drag across words to highlight them', tip: 'Drag across text to highlight it; double-click a word to highlight just that word. On a scanned page with no words, drag over the area', markup: true, text: true },
  underline: { label: 'Underline', short: 'Drag across words to underline them', tip: 'Drag across text to underline it; double-click a word to underline just that word', markup: true, text: true },
  strikeout: { label: 'Strikethrough', short: 'Drag across words to strike them out', tip: 'Drag across text to strike it out; double-click a word to strike just that word', markup: true, text: true },
  squiggly: { label: 'Squiggly underline', short: 'Drag across words to put a squiggly line under them', tip: 'Drag across text to mark it', markup: true },
  pen: { label: 'Draw', short: 'Draw freehand; a tap leaves a dot', tip: 'Draw freehand. Strokes made one after another are one drawing; a tap leaves a dot' },
  rect: { label: 'Rectangle', short: 'Drag to draw a rectangle (Shift: a square)', tip: 'Drag to draw a rectangle. Hold Shift for a square' },
  ellipse: { label: 'Oval', short: 'Drag to draw an oval (Shift: a circle)', tip: 'Drag to draw an oval. Hold Shift for a circle' },
  cloud: { label: 'Cloud', short: 'Drag to draw a revision cloud', tip: 'Drag to draw a revision cloud' },
  line: { label: 'Line', short: 'Drag to draw a line (Shift: level, upright or 45 degrees)', tip: 'Drag to draw a line. Hold Shift to keep it level, upright or at 45 degrees' },
  arrow: { label: 'Arrow', short: 'Drag from the tail to the point (Shift: level, upright or 45 degrees)', tip: 'Drag to draw an arrow, from its tail to its point. Hold Shift to keep it level, upright or at 45 degrees' },
  stamp: { label: 'Stamp', short: 'Click (or drag a size) where the stamp goes', tip: 'Choose a stamp, then click or drag where it goes', menu: true, text: true },
  check: { label: 'Check mark', short: 'Click where the check mark goes', tip: 'Click to add a check mark' },
  cross: { label: 'X mark', short: 'Click where the X goes', tip: 'Click to add an X' },
  dot: { label: 'Dot', short: 'Click where the dot goes', tip: 'Click to add a dot' },
  date: { label: 'Date', short: "Click where today's date goes", tip: "Click to add today's date" },
  sign: { label: 'Sign', short: 'Click (or drag a size) where your signature goes', tip: 'Add your signature: draw or type it once, then click where it goes', menu: true, text: true },
  initials: { label: 'Initials', short: 'Click (or drag a size) where your initials go', tip: 'Add your initials', menu: true, text: true },
  flatten: { label: 'Flatten…', short: 'Makes comments, signatures and filled-in fields part of the pages', tip: 'Make comments, signatures and filled-in fields part of the pages, so nobody can change them', action: true, text: true },
  editText: { label: 'Edit text', short: "Click a line of the page's own words to change it", tip: "Click a line of the page's own text to change it", text: true },
  addText: { label: 'Add page text', short: 'Click and type new words into the page itself', tip: 'Click to put new words into the page itself (not a comment)', text: true },
  editImage: { label: 'Edit pictures', short: 'Click a picture, then drag it or its handles', tip: 'Click a picture to select it: drag to move it, its handles to size it, Delete to remove it', text: true },
  addImage: { label: 'Add picture…', short: 'Click (or drag a size) where the picture goes', tip: 'Choose a picture, then click or drag where it goes', text: true },
  watermark: { label: 'Remove watermark…', short: 'Finds the watermarks and takes them out of every page', tip: 'Find the watermarks (marked as one by Acrobat or Word, a watermark layer or comment, or large tilted words repeated on the pages), see them before and after, and take them out of every page', action: true, text: true },
  formAuto: { label: 'Detect fields', short: 'Finds the blanks and puts a field on each', tip: 'Make this fillable: find the blanks (lines, boxes, table cells, check boxes) and put a field on each', action: true, text: true },
  fText: { label: 'Text field', short: 'Drag (or click) where a line of typing goes', tip: 'Drag (or click) where a line of typing goes' },
  fMulti: { label: 'Multi-line field', short: 'Drag (or click) where several lines of typing go', tip: 'Drag (or click) where several lines of typing go' },
  fCheck: { label: 'Check box', short: 'Click where a box to tick goes', tip: 'Click where a box to tick goes' },
  fCombo: { label: 'Drop-down list', short: 'Drag (or click) where a list of choices goes', tip: 'Drag (or click) where a list of choices goes, then double-click it to set the choices' },
  fProps: { label: 'Field properties', short: "The selected field's name, tip, text size and choices", tip: "The selected field's name, tip, text size, choices, required or read-only (or double-click the field)", action: true, text: true },
  fDelete: { label: 'Delete field', short: 'Takes out the selected field', tip: 'Take out the selected field (Delete)', action: true, text: true },
  formClear: { label: 'Remove all fields…', short: 'Takes every field out of the document', tip: 'Take every field out of the document', action: true, text: true },
  crop: { label: 'Crop', short: 'Drag the part of the page to keep, then say which pages to crop', tip: 'Drag the part of the page to keep, then choose which pages to crop (in the strip under this bar)', text: true },
  enhance: { label: 'Enhance scan…', short: 'Cleans up scanned pages', tip: 'Clean up scanned pages: white paper, solid black lines, specks taken off, straightened,\nwith hidden text from OCR to search, select and balloon. What is printed is never retyped.', action: true, text: true },
  redactText: { label: 'Mark text', short: 'Drag across words to mark them for redaction', tip: 'Drag across text to mark it for redaction' },
  redact: { label: 'Mark area', short: 'Drag a box to mark it for redaction', tip: 'Drag a box to mark it for redaction' },
  redactFind: { label: 'Mark all found', short: 'Marks every place the Find box found', tip: 'Mark every place the Find box finds', action: true, text: true },
  strikeText: { label: 'Cross out', short: 'Click a line of text or a symbol, or drag, to put a single line through it', tip: 'Click a line of text or a symbol to put a single line through it (one of two stacked limits, a tolerance, a GD&T symbol);\nShift+click for the whole dimension with its tolerance; drag across text to cross out those words,\nor drag from anywhere else to put the line where you drag, across anything (lines, symbols, pictures, scans).\nClick a line you put there to take it: drag it, or press Delete. The words stay readable.', text: true },
  redactApply: { label: 'Apply redactions', short: 'Takes everything marked out of the pages for good', tip: 'Take everything marked for redaction out of the pages for good. A cross-out needs no Apply: it stays a mark you can select and delete later', action: true, text: true },
  scrub: { label: 'Remove hidden info…', short: "Takes out the document's details, attachments, scripts and hidden text", tip: "Take out the document's details, attachments, scripts, hidden text and comments", action: true, text: true },
};
// tools that place one thing, then hand back to Select (the rest stay on, for marking up a run of things)
const ONE_OFF = new Set(['note', 'text', 'rect', 'ellipse', 'cloud', 'line', 'arrow', 'stamp', 'fText', 'fMulti', 'fCheck', 'fCombo']);
// ...unless "Keep tool on" is ticked for it (a signature and initials too; kept apart, as a click on a comment with
// one of those still signs there rather than taking the comment)
const PLACE_ONCE = new Set([...ONE_OFF, 'sign', 'initials']);
const FIELD_TOOLS = { fText: ['text', 150, 18], fMulti: ['text', 220, 60], fCheck: ['checkbox', 12, 12], fCombo: ['combo', 120, 18] };
// What can be done to pages, once: the Pages tab, its "More tools" and a thumbnail's right-click menu are all drawn
// from this list, so they agree on names and order. bar: its place in the tab (the whole number is its group);
// rare: under "More tools" there; whole: a whole-document command (More tools' last section). The right-click menu
// lists them all in this order, a line between groups. They act on the picked pages, or the page in view (_which).
const PAGE_CMDS = [
  { id: 'rotateLeft', group: 1, bar: 1.1, label: 'Rotate left', icon: 'rotateLeft', tip: 'Rotate the pages a quarter turn left: saved in the file (Turn view, in the bar above, only turns how you look at them)',
    run: (ed) => ed.run('pages_rotate', { pages: ed._which(), by: 270 }) },
  { id: 'rotateRight', group: 1, bar: 1.2, label: 'Rotate right', icon: 'rotateRight', tip: 'Rotate the pages a quarter turn right: saved in the file',
    run: (ed) => ed.run('pages_rotate', { pages: ed._which(), by: 90 }) },
  { id: 'insert', group: 2, bar: 2.1, label: 'Insert', tip: 'Add a blank page, or the pages of other PDFs and pictures (combine files)', sub: [
    { label: 'Blank page after', run: (ed) => ed.run('pages_blank', { at: Math.max(...ed._which()) + 1 }) },
    { label: 'Blank page before', run: (ed) => ed.run('pages_blank', { at: Math.min(...ed._which()) }) },
    { label: 'From files…', run: (ed) => ed._insertFiles(Math.max(...ed._which()) + 1) },
  ] },
  { id: 'duplicate', group: 3, rare: true, label: 'Duplicate', tip: 'Copy the pages, each after itself', run: (ed) => ed.run('pages_duplicate', { pages: ed._which() }) },
  { id: 'replace', group: 3, rare: true, label: 'Replace…', tip: "Swap the pages for another file's", run: (ed) => ed._replace() },
  { id: 'extract', group: 3, bar: 2.3, label: 'Extract…', tip: 'Save the pages as a new PDF', run: (ed) => ed._extract() },
  { id: 'split', group: 3, rare: true, label: 'Split…', tip: 'Split the document into several PDFs', run: (ed) => ed._split() },
  { id: 'crop', group: 4, bar: 3.1, label: 'Crop', tool: 'crop', run: (ed) => ed.setTool('crop') },
  { id: 'uncrop', group: 4, rare: true, label: 'Remove crop', tip: 'Show the whole of the pages again', run: (ed) => ed.run('pages_uncrop', { pages: ed._which() }) },
  { id: 'enhance', group: 5, whole: true, label: 'Enhance scan…', run: (ed) => ed._enhance() },
  { id: 'delete', group: 6, bar: 2.2, label: 'Delete', icon: 'trash', tip: 'Take the pages out',
    menuLabel: (n) => (n === 1 ? 'Delete page' : `Delete ${n} pages`), run: (ed) => ed._pagesDelete() },
];
// The page commands by name, for the title bar's menus and "Search commands" (a list for Insert: one for each of its
// choices), and the names things went by before, which the search still finds them by
const PAGE_NAMES = { rotateLeft: 'Rotate pages left', rotateRight: 'Rotate pages right', insert: ['Insert blank page after', 'Insert blank page before', 'Insert pages from files…'],
  duplicate: 'Duplicate pages', replace: 'Replace pages…', extract: 'Extract pages…', split: 'Split document…', uncrop: 'Remove crop', delete: 'Delete pages' };
const ALSO = { form: 'Prepare Form', balloon: 'Balloon mode, Ballooning, inspection', typewriter: 'Add text', addText: 'Add text', cross: 'Cross', fMulti: 'Text box of several lines',
  strikeText: 'Strike through', redactFind: 'Mark found', redactApply: 'Apply', scrub: 'Remove hidden information, sanitize', formAuto: 'Make fillable', enhance: 'OCR, clean up a scan',
  pen: 'Pen, freehand, sketch', rect: 'Box', ellipse: 'Ellipse, circle', note: 'Comment', fCombo: 'Combo box', rotateLeft: 'Turn left', rotateRight: 'Turn right', uncrop: 'Uncrop',
  insert: 'Combine files, merge, add page', extract: 'Save pages as', sign: 'Signature', crop: 'Trim' };
// page numbers as people write them: [2, 4, 5, 6] is "3, 5-7"
const pageList = (pages) => {
  const out = [];
  for (let i = 0; i < pages.length; i++) {
    let j = i;
    while (j + 1 < pages.length && pages[j + 1] === pages[j] + 1) j++;
    out.push(j > i ? `${pages[i] + 1}-${pages[j] + 1}` : `${pages[i] + 1}`);
    i = j;
  }
  return out.join(', ');
};
// what the options strip says once selected words have been marked
const MARKED = { highlight: 'Highlighted the selection', underline: 'Underlined the selection', strikeout: 'Struck through the selection', squiggly: 'Underlined the selection',
  strikeText: 'Crossed out the selection', redact: 'Marked the selection for redaction' };
// ...or when those very words already had that mark (nothing is added: the one there is shown instead)
const MARKED_ALREADY = { highlight: 'Those words are already highlighted', underline: 'Those words are already underlined', strikeout: 'Those words are already struck through',
  squiggly: 'Those words are already underlined', strikeText: 'Those words are already crossed out' };
const segDist = (p, a, b) => { // from a point to a line segment
  const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
  const t = L ? clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L, 0, 1) : 0;
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
};
const COLORS = ['#e02020', '#f08a00', '#ffd400', '#2bb24c', '#1f9bd7', '#2858cf', '#8b3fd9', '#e84d9c', '#000000', '#6b7280', '#ffffff'];
const KIND_LABEL = { note: 'Note', text: 'Text', highlight: 'Highlight', underline: 'Underline', strikeout: 'Strikethrough',
  squiggly: 'Squiggly', rect: 'Rectangle', ellipse: 'Oval', line: 'Line', ink: 'Drawing', polygon: 'Polygon', polyline: 'Polyline',
  stamp: 'Stamp', redact: 'Redaction', caret: 'Insert', file: 'Attachment' };
const STAMP_LABEL = { Approved: 'Approved', NotApproved: 'Not Approved', Draft: 'Draft', Final: 'Final', ForComment: 'For Comment',
  Confidential: 'Confidential', Experimental: 'Experimental', AsIs: 'As Is', Expired: 'Expired', Departmental: 'Departmental',
  ForPublicRelease: 'For Public Release', NotForPublicRelease: 'Not For Public Release', Sold: 'Sold', TopSecret: 'Top Secret' };
const DEFAULT_STYLE = { colors: { strikeText: '#000000', highlight: '#ffd400', underline: '#2bb24c', strikeout: '#e02020', squiggly: '#e02020', note: '#ffd400',
  text: '#000000', typewriter: '#000000', pen: '#e02020', rect: '#e02020', ellipse: '#e02020', cloud: '#e02020', line: '#e02020',
  arrow: '#e02020', check: '#000000', cross: '#000000', dot: '#000000', date: '#000000', addText: '#000000' },
fills: { text: '#fff9c4' }, // what's inside a text box, rectangle, oval or cloud: none unless set
widths: {}, opacities: {}, // line width and opacity, each tool its own (so a faint highlighter never fades what's typed or drawn next)
width: 1.5, opacity: 1, fontsize: 12 }; // (width, opacity: what a tool has until it's given its own)
const CHECK = [[0.1, 0.55], [0.4, 0.85], [0.9, 0.15]];
const CROSS = [[[0.15, 0.15], [0.85, 0.85]], [[0.85, 0.15], [0.15, 0.85]]];
const clamp = (x, a, b) => Math.min(Math.max(x, a), b);
const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } };
const keep = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage off */ } };
const rectOf = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])];
const onPagePt = (p, q) => [clamp(q[0], 0, p.info.w), clamp(q[1], 0, p.info.h)]; // a point kept on its page (p: a page of the view)
// a picture's shape (asp: its width over its height) as large as fits in a box, in its middle: where the worker puts a
// signature, a stamp or a picture dragged out to a size
const fitIn = (r, asp) => { const w = Math.min(r[2], r[3] * asp), hh = w / asp; return [r[0] + (r[2] - w) / 2, r[1] + (r[3] - hh) / 2, w, hh]; };
// the outline of a revision cloud round a box: scallops about 9 points long, bulging outward (as the page shows it)
const cloudPath = (x, y, w, hh) => {
  const at = [[x, y], [x + w, y], [x + w, y + hh], [x, y + hh], [x, y]];
  let d = `M${x} ${y}`;
  for (let i = 0; i < 4; i++) {
    const [x0, y0] = at[i], [x1, y1] = at[i + 1], len = Math.hypot(x1 - x0, y1 - y0), n = Math.max(1, Math.round(len / 9)), r = len / n * 0.6;
    for (let k = 1; k <= n; k++) d += `A${r} ${r} 0 0 1 ${x0 + (x1 - x0) * k / n} ${y0 + (y1 - y0) * k / n}`;
  }
  return `${d}Z`;
};
const inRect = (r, [x, y], pad = 0) => x >= r[0] - pad && x <= r[0] + r[2] + pad && y >= r[1] - pad && y <= r[1] + r[3] + pad;
// is a point in a mark's run of words? q: its corners [upper left, upper right, lower left, lower right], at any angle
const inQuad = (q, pt, pad = 0) => {
  const ring = [q[0], q[1], q[3], q[2]];
  let inside = false;
  for (let i = 0, j = 3; i < 4; j = i++) {
    const a = ring[i], b = ring[j];
    if ((a[1] > pt[1]) !== (b[1] > pt[1]) && pt[0] < (b[0] - a[0]) * (pt[1] - a[1]) / (b[1] - a[1]) + a[0]) inside = !inside;
  }
  return inside || ring.some((a, i) => segDist(pt, a, ring[(i + 1) % 4]) <= pad);
};

function pdfDate(s) {
  const m = /D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?/.exec(s || '');
  if (!m) return '';
  const d = new Date(+m[1], (+m[2] || 1) - 1, +m[3] || 1, +m[4] || 0, +m[5] || 0);
  return d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
}

export class PdfEditor {
  constructor(view) {
    this.v = view;
    this.doc = null;
    this.set = load('pe:set', 'comment');
    this.tool = 'select';
    const saved = load('pe:style', {});
    this.style = { ...DEFAULT_STYLE, ...saved, colors: { ...DEFAULT_STYLE.colors, ...(saved.colors || {}) }, fills: { ...DEFAULT_STYLE.fills, ...(saved.fills || {}) },
      widths: { ...(saved.widths || {}) }, opacities: { ...(saved.opacities || {}) } };
    // (an older version kept one line width for every tool: the tools that draw lines start from it; opacity starts solid)
    if (saved.width && !saved.widths) for (const k of ['pen', 'rect', 'ellipse', 'cloud', 'line', 'arrow']) this.style.widths[k] = saved.width;
    this.keepOn = load('pe:keep', {}) || {}; // tool -> true: stays on after placing one ("Keep tool on")
    this.sel = null; // {type: 'annot' | 'image', page, id, rect, a}
    this.group = []; // the other comments selected along with it (Shift+click, Ctrl+drag over paper): see _sels
    this.annots = [];
    this.fields = [];
    this.images = {};
    this.words = {}; // page -> word boxes as shown, for the Select tool (null while asked for)
    this.fieldEls = new Map();
    this.picked = new Set(); // thumbnails picked for the Pages tools
    this.row = h('div', { class: 'pe-row', hidden: true });
    view.el.insertBefore(this.row, view.body);
    this.opts = h('div', { class: 'pe-opts', hidden: true }); // the options strip: the tool in hand, and its settings
    view.el.insertBefore(this.opts, view.body);
    // while a box on the page is typed in, its settings here change it as it is: the typing keeps the keyboard
    this.opts.addEventListener('mousedown', (e) => { if (this.inline && !e.target.closest('input')) e.preventDefault(); });
    window.addEventListener('focus', () => { if (this.inline && document.activeElement !== this.inline.ta) this.inline.ta.focus(); });
    this._fileGroup();
    new ResizeObserver(() => this._compact()).observe(this.row);
    this.panel = h('div', { class: 'pe-panel', hidden: true });
    view.body.append(this.panel);
    this.showPanel = load('pe:panel', false);
    view.scroller.addEventListener('dblclick', (e) => this._dbl(e));
    view.scroller.addEventListener('pointermove', (e) => this._hover(e));
    view.scroller.addEventListener('contextmenu', (e) => this._context(e));
    view.scroller.addEventListener('scroll', () => { this._prefetch(); this._scope(); });
    view.scroller.addEventListener('pointerleave', (e) => {
      this._follow?.remove();
      this._setHover(null);
      if (e.buttons) return; // (a drag that has left the pages for a moment: its cursor stays)
      view.scroller.classList.remove('pe-over-annot', 'pe-over-text', 'pe-over-area'); // (what it was over: nothing now)
      view.scroller.dataset.over = '';
    });
    document.addEventListener('keyup', (e) => { if (e.key === ' ') this._hand(false); });
    window.addEventListener('blur', () => this._hand(false));
    const show = view._showSelection.bind(view); // selected text gets its bar of things to do with it
    view._showSelection = () => { show(); this._textBar(); };
  }

  get editable() { return !!this.doc && !this.doc.meta.pdf.picture; }

  // ================================================================== opening and closing
  async open(doc) {
    this._inkLeave();
    this._nudgeLeave();
    this._pop?.shut(false);
    this._resetTool(); // (every document starts on Select: nothing in hand from the one before)
    this._imgs = null;
    this.doc = doc;
    this.sel = null;
    this.group = [];
    this.annots = [];
    this.fields = [];
    this.images = {};
    this.words = {};
    this._wordsAsked = {};
    this.fieldEls.clear();
    this.picked.clear();
    this.cropAsk = null;
    this.flash = null;
    this._sideWas = undefined;
    this._stepping = false;
    this.state = null; // (the last document's: this one's is asked for below)
    this.row.hidden = !this.editable;
    this.panel.hidden = !this.editable || !this.showPanel;
    this._syncFile();
    this._optsBar();
    if (!this.editable) return;
    this._bar();
    this._ready = (async () => {
      try {
        this.state = await this._ask('state');
        this.doc.pdfDirty = this.state.dirty;
        await this.refresh();
        this._bar();
      } catch (e) { console.warn('PDF editor:', e.message); }
    })();
    await this._ready;
  }

  close() {
    if (this.doc) {
      // What's still being typed (a field, a box on the page, a note) goes in as it is: to this document's worker,
      // which is still there when the document is only put aside for another. Nothing typed is dropped by a tab click
      for (const el of this.fieldEls.values()) if (el.timer || document.activeElement === el) el.commit();
      this._endInline(true);
      this._pop?.shut(true);
    }
    this._dragOff?.(); // (a drag still on is let go of)
    this.v.selectOff?.();
    this._inkLeave();
    this._nudgeLeave();
    this._resetTool();
    this.doc = null;
    this.sel = null;
    this.group = [];
    this.cropAsk = null;
    this.flash = null;
    this.row.hidden = true;
    this.opts.hidden = true;
    this._syncFile();
    this.panel.hidden = true;
    this.panel.replaceChildren();
    this.fieldEls.clear();
  }

  // The tool in hand is put down without a word to anyone (its document is being left, or another is opening): the
  // cursor, the fields and the keys are Select's again, and nothing chosen for the last document (a stamp, a
  // selected field, the hand) is carried into the next
  _resetTool() {
    const s = this.v.scroller;
    this._follow?.remove();
    this._follow = null;
    this._hov = '';
    this._selecting = false;
    this._hand(false);
    this.tool = 'select';
    this.payload = null;
    this.fsel = null;
    this._toolSeq = (this._toolSeq || 0) + 1; // (an answer still on its way for the tool that was in hand changes nothing here)
    this._barKey = null;
    clearTimeout(this._optsT);
    s.title = '';
    s.classList.remove('pe-drawing', 'pe-over-annot', 'pe-over-text', 'pe-over-area');
    s.dataset.over = '';
    s.dataset.tool = 'select';
  }

  // the view was laid out again (zoom, resize, new pages): what's drawn over the pages follows
  layout() {
    if (!this.editable) return;
    this._drawFields();
    this._drawSel();
    this._textBar(); // (placed in pixels: put again where the words are now)
    if (this._ink && this._ink.turns !== this.v.state.turns) this._inkFlush(); // (strokes waiting were drawn for the view as it was turned)
    if (this.inline) this._placeInline();
  }

  // ================================================================== talking to the worker
  _ask(op, args = {}, doc = this.doc) { return api.pdfEdit(doc.id, op, args); }

  // Edits go to the worker one at a time, in the order they're made (a save waits for the edits before it). Each
  // belongs to the document it was made on: it waits in that document's own line and goes to that document's
  // worker, whichever document is in front by the time its turn comes
  run(op, args = {}, busyText) {
    const doc = this.doc;
    if (!doc) return Promise.resolve(null);
    if (this._ink) this._inkFlush(); // (strokes drawn and not sent yet go in first, so every edit lands in the order it was made)
    // the tool in hand now, and which pick of it: by the time the worker answers, another may have been picked
    const tool = this.tool, seq = this._toolSeq;
    doc._peN = (doc._peN || 0) + 1; // (how many of its edits are still on their way)
    const go = (doc._peQ || Promise.resolve()).then(() => this._run(op, args, busyText, tool, seq, doc)).finally(() => { doc._peN -= 1; });
    doc._peQ = go.catch(() => {});
    return go;
  }

  async _run(op, args = {}, busyText, tool = this.tool, seq = this._toolSeq, doc = this.doc) {
    if (!doc) return null;
    const slow = busyText ? setTimeout(() => toast(busyText, 'info', 4000), 600) : null;
    try {
      const r = await this._ask(op, args, doc);
      if (this.doc !== doc) { // its document was put aside meanwhile: only its tab hears of it
        if (r?.state) { doc.pdfDirty = r.state.dirty; this.v.app?.shell?.renderDocTabs(); }
        return r;
      }
      if (r?.state) await this._applied(r);
      // as Acrobat: a comment placed one at a time is left selected, back on the Select tool, to move or change
      // (not when another tool was picked meanwhile, or the same one is already drawing or typing its next: it stays in hand)
      if (this.doc === doc && op === 'annot_add' && r?.result?.id && this.tool === tool && this._toolSeq === seq && !this._staysOn(tool) && !this._dragOff && !this.inline) {
        const a = this.annots.find((x) => x.id === r.result.id && x.page === args.page);
        this.setTool('select');
        if (a) this.select({ type: 'annot', page: a.page, id: a.id, rect: a.rect, a });
      }
      return r;
    } catch (e) {
      if (this.doc !== doc && this.v.app?.docs && !this.v.app.docs.includes(doc)) return null; // (its document was closed: nobody to tell)
      // (Cross out clicked where there's nothing to cross out: the worker says what to click, which is help, not a failure)
      if (op === 'strike_at') toast(e.message, 'info', 4000); else toast(e.message, 'error');
      return null;
    } finally { clearTimeout(slow); }
  }

  // Something typed or drawn that the worker doesn't have yet shows as unsaved at once (the tab's dot, Save)...
  _touch() {
    const doc = this.doc;
    if (!doc || doc.pdfDirty) return;
    doc.pdfDirty = true;
    this.v.app?.shell?.renderDocTabs();
    this._syncFile();
  }

  // ...is anything of the kind still waiting?
  _waiting() {
    if (this.inline?.typed || this._pop?.typed || this._ink?.strokes.length) return true;
    for (const el of this.fieldEls.values()) if (el.timer) return true;
    return false;
  }

  // ...and once it's in, or was dropped, the document is as unsaved as the worker says it is
  _calm(doc = this.doc) {
    if (!doc || this.doc !== doc || !this.state || doc._peN || this._waiting()) return;
    const dirty = !!this.state.dirty;
    if (!!doc.pdfDirty === dirty) return;
    doc.pdfDirty = dirty;
    this.v.app?.shell?.renderDocTabs();
    this._syncFile();
  }

  async _applied(r) {
    this._cropEnd(); // (a crop still being asked about was for the pages as they were)
    this._edits = (this._edits || 0) + 1;
    this.state = r.state;
    this.doc.pdfDirty = r.state.dirty || this._waiting();
    this.images = {};
    this._imgs = null; // (the comments' pictures, carried when they're dragged: drawn again after any change)
    if (r.text || r.structure) { this.words = {}; this._wordsAsked = {}; }
    if (r.structure) { this.picked.clear(); this.v.reloadPages(r.pages); }
    else if (r.changed === null) this.v.redraw(null);
    else if (r.changed?.length) this.v.redraw(r.changed);
    if (r.text && !r.structure) { this.v.hints.close(); this.v.hints.open(this.doc); this.v.refind(); } // (what Find found stays, looked up again)
    await this.refresh();
    this._bar();
    this.v.balloons?.changed(r); // the inspection list is in the PDF too: an edit or an undo may have changed it
    this.v.app?.shell?.renderDocTabs();
  }

  async refresh() {
    if (!this.editable) return;
    const doc = this.doc;
    const [annots, fields] = await Promise.all([this._ask('annots'), this.state?.fields ? this._ask('fields') : []]);
    if (this.doc !== doc) return;
    this.annots = annots;
    this.fields = fields;
    if (this.sel?.type === 'annot') {
      // the selection follows its comments (their ids stay the same through a move, an undo, a redo). One on the move
      // (dragged, nudged, or put down and not yet drawn again) stays where the hand has it, with its picture
      const was = this._sels(), now = was.map((s) => {
        const a = annots.find((x) => x.id === s.id && x.page === s.page);
        if (!a) return null;
        const n = selOf(a);
        if (s.moved || s.held) Object.assign(n, { moved: s.moved, held: s.held, img: s.img });
        if (s.moved || s.held === 'sent') n.rect = s.rect; // (once the worker has answered for it, it's where the worker put it)
        return n;
      });
      for (const it of this._nudge?.items || []) { const i = was.indexOf(it.s); if (i >= 0 && now[i]) it.s = now[i]; }
      const live = now.filter(Boolean);
      this.sel = live[0] || null;
      this.group = live.slice(1);
      for (const s of live) if (!s.img) this._fetchImg(s);
    } else if (this.sel?.type === 'image') {
      // a picture of the page: still there, and where? (an undo may have put it back, or taken it away)
      const s = this.sel;
      await this._loadImages(s.page);
      if (this.doc !== doc) return;
      if (this.sel === s && !s.moved && !s.held) {
        const im = (this.images[s.page] || []).find((x) => x.id === s.id);
        this.sel = im ? { type: 'image', page: s.page, id: im.id, rect: im.rect } : null;
      }
    }
    if (this.tool === 'editImage') this._loadImages(); // (the pictures in view, known again before the next press on one)
    this._drawFields();
    this._drawSel();
    this._prefetch();
    if (this.showPanel) this._renderPanel();
  }

  // ================================================================== the toolbar
  // does a tool stay in hand after it has placed one thing? (the ones that mark up a run of things always do)
  _staysOn(tool) { return !PLACE_ONCE.has(tool) || !!this.keepOn[tool]; }

  // a tool's own opacity and line width (kind: a tool's id)
  _op(kind) { return this.style.opacities[kind] ?? DEFAULT_STYLE.opacity; }

  _wd(kind) { return this.style.widths[kind] ?? DEFAULT_STYLE.width; }

  // a tool's button. opts.off: it can't act now, so it's disabled, and opts.why (in its tooltip) says what it waits for
  _btn(id, opts = {}) {
    const t = TOOLS[id] || {};
    const lockable = !opts.run && ONE_OFF.has(id) && !t.menu; // (a tool with a menu is kept on from the options strip)
    const label = opts.label || t.label, caret = opts.caret ?? !!t.menu;
    const b = h('button', { class: `pv-btn pe-tool${this.tool === id ? ' on' : ''}${opts.cls ? ` ${opts.cls}` : ''}`, disabled: !!opts.off,
      title: `${label}${!opts.run && KEY_OF[id] ? ` (${KEY_OF[id]})` : ''}${opts.off && opts.why ? `\n${opts.why}` : `${opts.tip || t.tip ? `\n${opts.tip || t.tip}` : ''}${lockable ? '\nDouble-click to keep it on for several.' : ''}`}`,
      html: `${ICON[opts.icon || t.icon || id] || ''}${opts.text || t.text ? `<span>${label}</span>` : ''}${caret ? '<i class="pe-car">▾</i>' : ''}` });
    b.dataset.tool = id;
    b.addEventListener('click', (e) => {
      if (opts.run) { opts.run(b); return; }
      if (lockable && e.detail >= 2) { // the second click of a double-click: kept on for several (not put down again by it)
        this.keepOn[id] = true;
        keep('pe:keep', this.keepOn);
        if (this.tool !== id) this.setTool(id); else { this._optsBar(); this.v.app?.status?.(); }
        return;
      }
      this._pick(id, b);
    });
    return b;
  }

  // Save (with Save As and Print under its arrow), Print, Undo and Redo, and the comments list's button: built once
  // into the page view's Document bar, where they stay whatever the tab or the tool. _syncFile keeps them current.
  _fileGroup() {
    const b = (icon, tip, run, cls = '', label = '') => h('button', { class: `pv-btn${cls ? ` ${cls}` : ''}`, title: tip,
      html: `${ICON[icon] || ''}${label ? `<span>${label}</span>` : ''}`, onclick: run });
    const print = () => this.v.app?.run('print');
    this.saveBtn = b('save', 'Save (Ctrl+S)', () => this.save(), 'pe-save', 'Save');
    const more = h('button', { class: 'pv-btn pe-caret', text: '▾', title: 'Save As, Print' });
    more.addEventListener('click', () => menu(more, [
      { label: 'Save As…', kb: 'Ctrl+Shift+S', action: () => this.saveAs() },
      { label: 'Print…', kb: 'Ctrl+P', action: print },
    ]));
    this.printBtn = b('print', 'Print (Ctrl+P)', print, 'pe-print');
    this.undoBtn = b('undo', 'Undo (Ctrl+Z)', () => this.undo());
    this.redoBtn = b('redo', 'Redo (Ctrl+Y)', () => this.redo());
    this.v.fileSlot.append(this.saveBtn, more, this.printBtn, this.undoBtn, this.redoBtn, h('span', { class: 'pv-sep' }));
    this.panelLabel = h('span', { text: 'Comments' });
    this.panelBtn = h('button', { class: 'pv-btn pv-toggle pe-cbtn', html: ICON.comments, onclick: () => this.togglePanel() });
    this.panelBtn.append(this.panelLabel);
    this.v.panelSlot.append(h('span', { class: 'pv-sep' }), this.panelBtn);
    this.v.fileSlot.hidden = this.v.panelSlot.hidden = true;
  }

  _syncFile() {
    const on = this.editable;
    this.v.fileSlot.hidden = this.v.panelSlot.hidden = !on;
    if (on) {
      const st = this.state || {}, dirty = !!(st.dirty || this.doc.pdfDirty), must = !!this.doc.meta.pdf.saveAs; // (must: it has no file of its own yet)
      this.saveBtn.disabled = !dirty && !must;
      this.saveBtn.classList.toggle('pe-dirty', dirty);
      this.saveBtn.title = dirty || must ? 'Save (Ctrl+S)' : 'All changes saved';
      this.undoBtn.disabled = !st.undo && !this._ink?.strokes.length; // (a stroke not sent yet can be taken back too)
      this.redoBtn.disabled = !st.redo;
      const away = !!this.v.balloons?.on, n = this._top().length; // (the list is put away while ballooning)
      this.panelLabel.textContent = `Comments${n ? ` (${n})` : ''}`;
      this.panelBtn.disabled = away;
      this.panelBtn.classList.toggle('on', this.showPanel && !away);
      this.panelBtn.title = away ? 'The comments list is put away while ballooning' : `${this.showPanel ? 'Close' : 'Open'} the comments list (F6)`;
    }
    this.v._fitBar();
  }

  // The tool bar, in three parts: the tabs (pinned left), this tab's tools (the only part that scrolls, and only
  // once their names have stepped aside), and "More tools" (pinned right).
  // It's built when a document opens or the tab changes. Any other time (a tool picked, something selected, an
  // answer from the worker) the buttons there only change state, each staying the very button it was: a click
  // that began on one still lands on it, and a menu hanging from one keeps its place.
  _bar() {
    if (!this.editable) return;
    if (!SETS.some((s) => s.id === this.set && s.id !== 'balloon')) this.set = 'comment'; // (a tab kept from an older version)
    const set = SETS.find((s) => s.id === this.set), kids = this._tools(), key = `${this.doc.id}:${this.set}`;
    if (this._barKey !== key || !this.tools?.isConnected || !this._syncTools(this.tools, kids)) {
      const zone = this.tools = h('div', { class: 'pe-tools' }, ...kids);
      const more = this.moreBtn = h('button', { class: 'pv-btn pe-more', html: '<span>More tools</span><i class="pe-car">▾</i>',
        title: "More tools: this tab's commands used now and then, and what acts on the whole document" });
      more.addEventListener('click', () => this._more(more));
      this.row.replaceChildren(this._tabs(), h('span', { class: 'pv-sep' }), zone, more);
      this._barKey = key;
    }
    this.moreBtn.classList.toggle('on', set.more.includes(this.tool));
    this._compact();
    this._syncFile();
    this._optsBar();
  }

  // The buttons in the bar take on what they would be if drawn afresh (kids: those): lit, greyed, renamed, each in
  // place. What isn't a tool's button (a setting, the pages the commands act on) is swapped only if it changed.
  // False: it isn't the same row of buttons, and has to be built
  _syncTools(zone, kids) {
    const old = [...zone.children];
    if (old.length !== kids.length || old.some((o, i) => o.tagName !== kids[i].tagName || (o.dataset.tool || '') !== (kids[i].dataset.tool || ''))) return false;
    old.forEach((o, i) => {
      const n = kids[i];
      if (o.classList.contains('open')) n.classList.add('open'); // (a menu hangs from it)
      if (!o.dataset.tool) { if (!o.isEqualNode(n)) o.replaceWith(n); return; }
      if (o.className !== n.className) o.className = n.className;
      if (o.title !== n.title) o.title = n.title;
      if (o.disabled !== n.disabled) o.disabled = n.disabled;
      if (o.innerHTML !== n.innerHTML) o.innerHTML = n.innerHTML;
    });
    const scope = zone.querySelector('.pe-scope > span');
    if (scope) this.scopeText = scope; // (the one on show, which scrolling keeps current)
    return true;
  }

  // the tabs: the same strip starts the Balloon row (balloons.js), where Balloon is the lit one
  _tabs(active = this.set) {
    return h('div', { class: 'pe-sets' }, ...SETS.map((s) => h('button', { class: `pe-set${s.id === active ? ' on' : ''}`, title: SET_TIP[s.id], onclick: () => this._tab(s.id) },
      s.id === 'balloon' ? h('i', { class: 'pe-bdot' }) : null, s.label)));
  }

  // a tab is clicked: its tools come forward and the tool in hand is put down. Balloon is entered here and left by
  // clicking any other tab (the zoom and the place on the page stay as they are)
  _tab(id) {
    const bl = this.v.balloons;
    if (id === 'balloon') { if (bl && !bl.on) bl.toggle(); return; }
    if (bl?.on) bl._show(false);
    if (id === 'pages' && id === this.set) this._sideOn();
    this._goSet(id);
    this.setTool('select');
  }

  // another tab's tools (drawn by the caller). Pages opens the thumbnails, to pick pages in; leaving it puts them
  // away again if they were closed before
  _goSet(id) {
    if (id === this.set) return;
    if (this.set === 'pages' && this._sideWas === false && this.v.state?.side && this.v.pages.length) this.v._toggleSide();
    this._sideWas = undefined;
    if (id === 'pages') { this._sideWas = !!this.v.state.side; this._sideOn(); }
    this.set = id;
    this.fsel = null;
    keep('pe:set', id);
    if (this.sel) this.select(null); // (what was selected in the tab that's left can't be seen to be: Delete and the arrows must not reach it)
  }

  // this tab's buttons, left to right
  _tools() {
    const set = SETS.find((s) => s.id === this.set);
    if (set.id === 'pages') return this._pagesTools();
    return set.tools.map((id) => {
      if (id === '|') return h('span', { class: 'pv-sep' });
      if (id === 'redactLeaves') { // what a redaction leaves behind: a setting of Apply, right beside it
        const fill = load('pe:redact', 'black');
        const b = h('button', { class: 'pv-btn', title: 'What an applied redaction leaves on the page', html: `<span>Leaves: ${fill === 'white' ? 'Blank paper' : 'Black'}</span><i class="pe-car">▾</i>` });
        b.addEventListener('click', () => menu(b, [['black', 'Black: shows that something was removed'], ['white', 'Blank paper: nothing shows']].map(([c, label]) => (
          { label, check: c === fill, action: () => { keep('pe:redact', c); this._bar(); } }))));
        return b;
      }
      if (id === 'redactApply') {
        const n = this.annots.filter((a) => a.kind === 'redact').length;
        return this._btn(id, { label: `Apply redactions (${n})`, cls: 'pe-accent', off: !n, why: 'Nothing is marked for redaction yet: use Mark text, Mark area or Mark all found.\nA cross-out needs no Apply.' });
      }
      if (id === 'redactFind') return this._btn(id, { off: !this.v.hits?.length, why: 'Type in Find first (the box at the top right): this marks every place it found.' });
      if (id === 'fProps' || id === 'fDelete') return this._btn(id, { off: !this._fselField(), why: 'Click a field on the page first.' });
      if (id === 'formAuto') return this._btn(id, { caret: (this.v.pages?.length || 0) > 1 });
      return this._btn(id);
    });
  }

  // "More tools", always the last thing in the bar: this tab's commands used now and then, then the ones that act
  // on the whole document (the same four in every tab; this tab's own comes first)
  _more(anchor) {
    const set = SETS.find((s) => s.id === this.set);
    const rare = set.id === 'pages' ? PAGE_CMDS.filter((c) => c.rare).map((c) => ({ label: c.label, action: () => c.run(this) }))
      : set.more.filter((id) => !WHOLE_DOC.includes(id)).map((id) => this._moreItem(id));
    menu(anchor, [...rare, ...this._wholeItems(set.more)], { align: 'right' });
  }

  _moreItem(id) {
    const t = TOOLS[id];
    if (t.action) return { label: t.label, disabled: id === 'formClear' && !this.fields.length, action: () => this._pick(id) };
    return { label: `${t.label}${KEY_OF[id] ? ` (${KEY_OF[id]})` : ''}`, check: this.tool === id, action: () => this._pick(id) }; // (a tool: ticked while it's in hand)
  }

  // the whole-document section of a "More tools" menu (first: the ones to list first, the tab's own)
  _wholeItems(first = []) {
    const ids = [...WHOLE_DOC.filter((id) => first.includes(id)), ...WHOLE_DOC.filter((id) => !first.includes(id))];
    return [{ head: 'Whole document' }, ...ids.map((id) => ({ label: TOOLS[id].label, action: () => this._pick(id) }))];
  }

  // Find found something, or was cleared: "Mark all found" waits on it
  findChanged() { if (this.editable && this.set === 'redact' && !this.v.balloons?.on) this._bar(); }

  // when the tools don't all fit, their names step aside (the icons and tooltips stay) before their part of the bar
  // has to scroll; the tabs and More tools never move
  _compact() {
    const r = this.row, z = this.tools;
    if (!z || !r.clientWidth) return;
    r.classList.remove('compact');
    if (z.scrollWidth > z.clientWidth + 1) r.classList.add('compact');
  }

  // ================================================================== commands by name
  // Every tab, tool and page command, for the title bar's menus and "Search commands" (main.js registers them, so they
  // are found by name there). also: the names they went by before.
  commands() {
    const out = [];
    const bl = () => !!this.v.balloons?.on;
    for (const s of SETS) {
      out.push({ id: `tab-${s.id}`, label: s.id === 'balloon' ? 'Balloon' : `${s.label} tab`, tip: SET_TIP[s.id], also: ALSO[s.id],
        toggle: () => (s.id === 'balloon' ? bl() : !bl() && this.set === s.id), run: () => this._tab(s.id) }); // (toggle: it's the open one, ticked in the Tools menu)
    }
    out.push({ id: 'leaveBalloon', label: 'Leave Balloon', tip: 'Back to the tab that was open before Balloon', also: 'Exit Ballooning', run: () => { if (this.v.balloons?.on) this._tab(this.set); } });
    for (const [id, t] of Object.entries(TOOLS)) {
      out.push({ id: `tool-${id}`, label: id === 'select' ? 'Select tool' : t.label, kb: KEY_OF[id], tip: t.short || t.tip, also: ALSO[id], run: () => this.useTool(id) });
    }
    for (const c of PAGE_CMDS) {
      if (c.tool || c.whole) continue; // (Crop and Enhance scan are among the tools above)
      const names = [].concat(PAGE_NAMES[c.id] || c.label);
      (c.sub || [c]).forEach((x, i) => out.push({ id: `page-${c.id}${c.sub ? i : ''}`, label: names[i] || x.label, tip: c.tip, also: ALSO[c.id],
        run: () => { if (!this.editable) return; this._showTab('pages'); x.run(this); } }));
    }
    return out;
  }

  // a tab comes forward without a click on it (Balloon is left if it's on); the tool in hand is put down if the tab changes
  _showTab(id) {
    const bl = this.v.balloons, was = this.set;
    if (bl?.on) bl._show(false);
    this._goSet(id);
    if (was !== id && this.tool !== 'select') this.setTool('select'); else this._bar();
  }

  // a tool or action by name, from a menu or the command search: its tab comes forward (so its button is there to
  // see, and to hang its menu on), then it's picked as a click on its button would pick it
  useTool(id) {
    const t = TOOLS[id];
    if (!t || !this.editable) return;
    if (id === 'select') { this.setTool('select'); return; }
    if (!WHOLE_DOC.includes(id)) { // (what acts on the whole document needs no tab: it's under More tools in all of them)
      const tab = PAGE_CMDS.some((c) => c.tool === id) ? 'pages' : SETS.find((s) => s.tools.includes(id) || s.more.includes(id))?.id;
      if (tab) this._showTab(tab);
    }
    if ((id === 'fProps' || id === 'fDelete') && !this._fselField()) { toast('Click a field on the page first.', 'info'); return; }
    if (id === 'redactFind' && !this.v.hits?.length) toast('Type what to mark in Find first: this marks every place it found.', 'info', 4000);
    if (this.tool === id) return; // (already in hand: a second pick would put it down)
    this._pick(id, this.row.querySelector(`[data-tool="${id}"]`) || this.row);
  }

  // once, the first time a PDF's pages show after the tools were moved: where the things people reach for went
  moved() {
    if (!this.editable || load('pe:moved', 0)) return;
    keep('pe:moved', 1);
    toast('Things moved. Save, Print, Undo and Redo are now at the top left, the same in every tab. Balloon is now a tab, beside Comment. Anything else: Search commands (top right) finds it by name.', 'info', 20000);
  }

  // a line in the options strip that says what was just done, for a moment
  _say(text, ms = 1500) {
    clearTimeout(this._sayT);
    this.flash = text;
    this._optsBar();
    this._sayT = setTimeout(() => { this.flash = null; this._optsBar(); }, ms);
  }

  // The options strip, under the toolbar: the tool in hand (or the selected comment) by name, how to use it in one
  // line, then its settings. Always there and always the same height; a setting that doesn't apply is only hidden
  // (its slot stays), so nothing in the strip ever moves.
  _optsBar() {
    const on = this.editable;
    this.opts.hidden = !on;
    clearTimeout(this._optsT);
    if (!on) return;
    // a menu hangs from one of the strip's own buttons: the strip waits until it's closed (drawn again now, the
    // button would be gone from under its menu)
    if (menuOpen() && this.opts.querySelector('.open')) { this._optsT = setTimeout(() => this._optsBar(), 250); return; }
    const away = !!this.v.balloons?.on, tool = this.tool, t = TOOLS[tool] || {};
    const a = this.sel?.type === 'annot' ? this.sel.a : null;
    let name = t.label || '', hint = t.short || '', esc = tool !== 'select';
    const bl = away ? this.v.balloons.hint() : null; // (Balloon is on: the strip is the inspection list's)
    if (bl) { name = bl.name; hint = bl.hint; esc = !!bl.esc; }
    else if (a && this.group.length) { name = `${this.group.length + 1} comments (selected)`; hint = 'Drag one to move them all, the arrow keys nudge them, Delete removes them; Shift+click takes one out or adds one'; }
    else if (a && pinned(a)) { name = `${this._label(a)} (selected)`; hint = 'It stays on its words: pick its color here, double-click it to add a note, Delete to remove it'; }
    else if (a) { name = `${this._label(a)} (selected)`; hint = `Drag to move it${a.kind === 'note' ? '' : ', its handles to size it'}, double-click to change its words, Delete to remove it`; }
    else if (this.sel) { name = 'Picture (selected)'; hint = 'Drag to move it, its handles to size it, Delete to remove it'; }
    const typing = !away && this.inline;
    if (typing) { // the rule in force for Enter, while a box on the page is being typed in
      hint = typing.enter === 'line' ? 'Enter starts a new line · Ctrl+Enter or a click away finishes · Esc cancels' : 'Enter or a click away finishes · Esc cancels';
    }
    const said = !typing && !!this.flash; // what was just done, for a moment
    if (said) hint = this.flash;
    if (!away && !typing && this.cropAsk) { this._cropBar(); return; }
    // "Keep tool on": for a tool that places one thing and hands back (Balloon's Add balloon is one such: bl.keep)
    const keepId = away ? bl?.keep || null : !this.sel && PLACE_ONCE.has(tool) ? tool : null, keepable = !!keepId;
    const tick = h('input', { type: 'checkbox' });
    tick.checked = !!this.keepOn[keepId];
    tick.addEventListener('change', () => {
      this.keepOn[keepId] = tick.checked;
      keep('pe:keep', this.keepOn);
      this.v.scroller.focus({ preventScroll: true }); // (the keyboard goes back to the pages: Esc and the tool keys)
      this.v.app?.status?.();
    });
    const hide = { visibility: 'hidden' };
    this.opts.replaceChildren(
      h('b', { class: 'pe-oname', text: name }),
      h('span', { class: `pe-ohint${said ? ' pe-said' : ''}`, text: hint, title: hint }),
      ...this._props(away),
      h('label', { class: 'pe-keep', title: 'Leave this tool on after each one placed, to add several. Esc puts it down.', style: keepable ? null : hide }, tick, 'Keep tool on'),
      h('span', { class: 'pe-esc', text: typing || bl ? 'Esc to cancel' : 'Esc to finish', style: esc || typing ? null : hide }));
  }

  // a crop has been dragged out: the strip asks which pages get it (the dashed box stays on the page meanwhile)
  _cropBar() {
    const { p, r, pages } = this.cropAsk, all = [...this.v.pagesInfo.keys()];
    const go = (list) => { this._cropEnd(); this.run('pages_crop', { pages: [p.i, ...list.filter((i) => i !== p.i)], rect: r }); };
    const b = (text, tip, run, cls = '') => h('button', { class: `pv-btn pe-obtn${cls}`, text, title: tip, onclick: run });
    this.opts.replaceChildren(
      h('b', { class: 'pe-oname', text: 'Crop' }),
      h('span', { class: 'pe-ohint', text: 'Which pages get this crop? What is outside the box is hidden, not thrown away: Remove crop brings it back.' }),
      b(pages.length > 1 ? `Crop the ${pages.length} picked pages` : `Crop this page (${p.i + 1})`, pages.length > 1 ? `Pages ${pageList(pages)}` : '', () => go(pages), ' main'),
      ...(all.length > 1 ? [b('Crop every page the same', `All ${all.length} pages`, () => go(all))] : []),
      b('Cancel', 'Leave the pages as they are (Esc)', () => this._cropEnd()));
  }

  _cropEnd() {
    if (!this.cropAsk) return;
    this.cropAsk.svg.remove();
    this.cropAsk = null;
    this._optsBar();
  }

  // color, fill, line width, text size and opacity: for the selected comment, or the next one drawn. Always the
  // same five slots in the same order (off: all of them hidden)
  _props(off = false) {
    const it = off ? null : this.inline || null; // typing in a box on the page: these are that box's, and change it as it is
    const sel = !it && this.sel?.type === 'annot' ? this.sel.a : null, tool = this.tool;
    const kind = it ? it.styleKey : sel ? (sel.kind === 'ink' ? 'pen' : sel.kind === 'line' && sel.arrow ? 'arrow' : sel.kind) : tool;
    const slot = (cls, label, show, make) => h('span', { class: `pe-slot ${cls}`, style: show && !off ? null : { visibility: 'hidden' } },
      h('span', { class: 'pe-sl', text: label }), show && !off ? make() : null);
    const swatch = (title, now, pick, none) => {
      const sw = h('button', { class: 'pv-btn pe-swatch', title }, h('span', { class: now ? '' : 'none', style: now ? { background: now } : null }));
      sw.addEventListener('click', () => menu(sw, [{ el: this._colorGrid(now, pick, none, !none && kind === 'highlight' ? HILITE : COLORS) }]));
      return sw;
    };
    const pickList = (title, text, list, label, now, change) => {
      const b = h('button', { class: 'pv-btn', title, text: `${text} ▾` });
      b.addEventListener('click', () => menu(b, list.map((x) => ({ label: label(x), check: now(x), action: () => this._setStyle(sel, kind, change(x)) }))));
      return b;
    };
    const colorable = it ? true : sel ? !['stamp', 'redact', 'file'].includes(sel.kind) : DEFAULT_STYLE.colors[tool] !== undefined;
    const color = it ? it.color : sel ? (sel.kind === 'text' ? sel.textColor : sel.color) || '#000000' : this.style.colors[kind] || '#000000';
    // what's inside a text box or a closed shape (text typed straight onto the page has no box to fill)
    const fillable = it ? it.boxed : sel ? (sel.kind === 'text' ? !sel.fitted : ['rect', 'ellipse', 'polygon'].includes(sel.kind)) : ['text', 'rect', 'ellipse', 'cloud'].includes(tool);
    const fill = (it ? it.fill : sel ? sel.fill : this.style.fills[tool]) || null;
    const lined = it ? false : sel ? ['rect', 'ellipse', 'line', 'ink', 'polygon', 'polyline'].includes(sel.kind) : ['pen', 'rect', 'ellipse', 'cloud', 'line', 'arrow'].includes(tool);
    const w = sel ? sel.width : this._wd(kind);
    const sized = it ? true : sel ? sel.kind === 'text' : ['text', 'typewriter', 'date', 'addText'].includes(tool);
    const fs = it ? it.size : sel ? sel.fontsize : this.style.fontsize;
    const faded = it ? false : sel ? !(sel.kind === 'strikeout' && sel.subject === 'Strike through') && (colorable || sel.kind === 'stamp') && !(sel.kind === 'text' && sel.fitted)
      : colorable && !['typewriter', 'date', 'addText', 'check', 'cross', 'dot', 'strikeText'].includes(tool);
    const op = sel ? sel.opacity ?? 1 : this._op(kind);
    return [
      slot('s-color', 'Color', colorable, () => swatch(it || sel?.kind === 'text' || sized ? 'Color of the words' : 'Color', color,
        (c) => this._setStyle(sel, kind, sel?.kind === 'text' ? { textColor: c } : { color: c }))),
      slot('s-fill', 'Fill', fillable, () => swatch('Fill: the color inside (None leaves it clear)', fill, (c) => this._setStyle(sel, kind, { fill: c }), true)),
      slot('s-line', 'Line', lined, () => pickList('Line width', `${w > 0 ? w : 1} pt`, [0.5, 1, 1.5, 2, 3, 4, 6, 8], (x) => `${x} pt`, (x) => x === w, (x) => ({ width: x }))),
      slot('s-size', 'Size', sized, () => pickList('Text size', `${Math.round(fs * 10) / 10} pt`, [8, 9, 10, 11, 12, 14, 16, 18, 24, 32, 48], (x) => `${x} pt`, (x) => x === fs, (x) => ({ fontsize: x }))),
      slot('s-op', 'Opacity', faded, () => pickList('Opacity', `${Math.round(op * 100)}%`, [1, 0.8, 0.6, 0.4, 0.2], (x) => `${x * 100}%`, (x) => Math.abs(x - op) < 0.01, (x) => ({ opacity: x }))),
    ];
  }

  // the whole palette, to pick one from (none: with a "None" cell first). The one palette, wherever a color is picked
  _colorGrid(now, pick, none = false, list = COLORS) {
    const cell = (c) => h('button', { class: `pe-c${c === now ? ' on' : ''}${c ? '' : ' none'}`, style: c ? { background: c } : null, title: c || 'None',
      onclick: () => { closeMenus(); pick(c); } });
    return h('div', { class: 'pe-colors' }, ...(none ? [cell(null)] : []), ...list.map(cell));
  }

  _setStyle(sel, kind, change) {
    const it = this.inline;
    if (it) { // typing: the box being typed in takes it now (and, a new one, its tool keeps it for the next)
      if (change.color || change.textColor) it.color = change.color || change.textColor;
      if ('fill' in change) it.fill = change.fill;
      if (change.fontsize) {
        it.size = change.fontsize;
        if (it.base != null) it.rect[1] = it.base - it.size * 0.85; // (typed onto the page: its first line stays where it was clicked)
      }
      this._paintInline();
      this._placeInline();
      it.ta.focus();
      if (!kind) { this._optsBar(); return; } // (words already on the page: theirs alone)
    } else if (sel && this.group.length) { // several selected: each takes what it can of the change, in one step to undo
      const items = this._sels().map((s) => { const o = this._lookFor(s.a, change); return o && { page: s.page, id: s.id, ...o }; }).filter(Boolean);
      if (items.length) this.run('annot_set_many', { items });
      return;
    } else if (sel) { this.run('annot_set', { page: sel.page, id: sel.id, ...change }); return; } // (fill: null says "none")
    if (change.color || change.textColor) this.style.colors[kind] = change.color || change.textColor;
    if ('fill' in change) this.style.fills[kind] = change.fill;
    if (change.width) this.style.widths[kind] = change.width;
    if (change.opacity) this.style.opacities[kind] = change.opacity;
    if (change.fontsize) this.style.fontsize = change.fontsize;
    keep('pe:style', this.style);
    if (it) this._optsBar(); else this._bar(); // (typing: only the strip, so the keyboard stays in the box)
  }

  // a change of look as one comment takes it: its own name for the color, and only what its kind has (null: none of it)
  _lookFor(a, change) {
    const o = {}, c = change.color || change.textColor;
    if (c && !['stamp', 'redact', 'file'].includes(a.kind)) o[a.kind === 'text' ? 'textColor' : 'color'] = c;
    if ('fill' in change && (a.kind === 'text' ? !a.fitted : ['rect', 'ellipse', 'polygon'].includes(a.kind))) o.fill = change.fill;
    if (change.width && ['rect', 'ellipse', 'line', 'ink', 'polygon', 'polyline'].includes(a.kind)) o.width = change.width;
    if (change.fontsize && a.kind === 'text') o.fontsize = change.fontsize;
    if (change.opacity && !(a.kind === 'text' && a.fitted) && !['redact', 'file'].includes(a.kind)) o.opacity = change.opacity;
    return Object.keys(o).length ? o : null;
  }

  // a tool button: pick the tool, or do what it does
  async _pick(id, b) {
    const t = TOOLS[id];
    if (id === 'stamp') { this._stampMenu(b); return; }
    if (id === 'sign' || id === 'initials') { this._signMenu(b, id); return; }
    if (id === 'flatten') { this._flatten(); return; }
    if (id === 'redactFind') { this._redactFound(); return; }
    if (id === 'redactApply') { this._redactApply(); return; }
    if (id === 'scrub') { this._scrub(); return; }
    if (id === 'watermark') { this._watermark(); return; }
    if (id === 'formAuto') { this._formAuto(b); return; }
    if (id === 'formClear') { this._formClear(); return; }
    if (id === 'enhance') { this._enhance(); return; }
    if (id === 'fProps' || id === 'fDelete') { // (their buttons are off until a field is selected)
      const f = this._fselField();
      if (f && id === 'fProps') this._fieldProps(f); else if (f) this._fieldDelete();
      return;
    }
    if (id === 'addImage') {
      const r = await api.openFiles('image', 'Choose a picture to add').catch((e) => { toast(e.message, 'error'); return null; });
      if (!r?.files?.length) return;
      this.setTool('addImage', { image: r.files[0].data });
      return;
    }
    if ((t?.markup || id === 'strikeText') && this.v.selection?.rects?.length) {
      if (this._selShown()) { this._markSel(id); return; } // words already selected, and in sight: marked at once
      this.v.selection = null; // (selected a while back and scrolled away from: let go of, and the tool is taken in hand)
      this.v._showSelection();
    }
    this.setTool(this.tool === id && id !== 'select' ? 'select' : id);
  }

  // The selected words get a mark at once: from a tool's button or key, the bar by the words or the right-click menu,
  // all the same. The tool in hand stays, and with Select the new mark is left selected, so the options strip shows
  // its color to change. kind: a markup tool, 'strikeText' (Cross out) or 'redact'
  async _markSel(kind, extra = {}) {
    const s = this.v.selection;
    if (!s?.rects?.length || !this.editable) return null;
    const r = await this.run('annot_add', this._markArgs(kind, s, extra));
    if (this.v.selection === s) { this.v.selection = null; this.v._showSelection(); }
    if (!r) return null;
    const a = r.result?.id != null && this.tool === 'select' ? this.annots.find((x) => x.id === r.result.id && x.page === s.page) : null;
    if (a) this.select({ type: 'annot', page: a.page, id: a.id, rect: a.rect, a });
    this._say((r.result?.existing && MARKED_ALREADY[kind]) || MARKED[kind] || 'Marked the selection');
    return r;
  }

  // what annot_add is sent to mark selected words (s: a selection, as the page view keeps it). Each line goes as its
  // four corners the way its words read, so an underline lies under them on a turned page and along a dimension
  // that reads up the sheet; the words themselves go as the mark's quote, and its note starts empty
  _markArgs(kind, s, extra = {}) {
    const where = s.quads?.length === s.rects.length ? { quads: s.quads } : { rects: s.rects };
    if (kind === 'redact' || kind === 'redactText') return { page: s.page, kind: 'redact', rects: s.rects };
    if (kind === 'strikeText') return { page: s.page, kind: 'strike', ...where, quote: s.text || '', color: this.style.colors.strikeText || '#000000' };
    return { page: s.page, kind, ...where, quote: s.text || '', color: this.style.colors[kind], opacity: this._op(kind), ...extra };
  }

  // is any of the selected text where it can be seen now? (a tool's button marks it at once only then)
  _selShown() {
    const s = this.v.selection, p = s && this.v.pages?.[s.page];
    if (!p || !s.rects?.length) return false;
    const box = this.v.scroller.getBoundingClientRect();
    return s.rects.some((r) => { const q = this._screen(p, r); return q.right > box.left && q.left < box.right && q.bottom > box.top && q.top < box.bottom; });
  }

  // a rectangle of a page (its own points) where it is on the screen now, in pixels, however the view is turned
  _screen(p, r) {
    const b = p.el.getBoundingClientRect(), [sw, sh] = this.v._size(p);
    const A = this._view(p, [r[0], r[1]]), B = this._view(p, [r[0] + r[2], r[1] + r[3]]);
    const kx = b.width / sw, ky = b.height / sh;
    const left = b.left + Math.min(A[0], B[0]) * kx, top = b.top + Math.min(A[1], B[1]) * ky;
    return { left, top, right: left + Math.abs(A[0] - B[0]) * kx, bottom: top + Math.abs(A[1] - B[1]) * ky };
  }

  // so many pixels of the screen, in a page's points at the zoom it's shown at: what counts as "on" a thing is a
  // matter of the hand and the screen, the same at any zoom
  _px(page, n) {
    const p = this.v.pages?.[page];
    return p?.cssW ? n * this.v._size(p)[0] / p.cssW : n * 0.75;
  }

  setTool(id, payload = null) {
    this._inkFlush(); // (what was drawn with the pen so far is one drawing, and done)
    this._flushNudge(); // (and what the arrow keys moved is put down)
    this._toolSeq = (this._toolSeq || 0) + 1;
    this._endInline(true);
    this._cropEnd();
    this._follow?.remove();
    this._follow = null;
    this._setHover(null);
    this.tool = id;
    this.payload = payload;
    this._drawFields(); // (fields are boxes to arrange under Forms, and to type into everywhere else)
    if (id !== 'select') this.select(null);
    this.v.scroller.classList.toggle('pe-drawing', id !== 'select');
    this.v.scroller.classList.remove('pe-over-annot', 'pe-over-text', 'pe-over-area'); // (what the last tool's pointer was over)
    this.v.scroller.dataset.over = '';
    this.v.scroller.dataset.tool = id;
    this._bar();
    this._textBar();
    this.v.app?.status?.();
    if (id === 'editImage') this._loadImages();
  }

  // what the status bar says while a tool is on
  hint() {
    if (!this.editable) return null;
    const bl = this.v.balloons;
    if (bl?.on) { // (Balloon: what a drag on the print makes now, while its Add balloon or a view is being drawn)
      const x = bl.hint();
      return x.esc ? `<b>${x.name}</b> - ${x.hint}${x.keep && this.keepOn[x.keep] ? ' (kept on)' : ''}` : null;
    }
    if (this.tool === 'select') return null;
    const t = TOOLS[this.tool];
    return t ? `<b>${t.label}</b> - ${t.short || t.tip}${PLACE_ONCE.has(this.tool) && this.keepOn[this.tool] ? ' (kept on)' : ''}` : null;
  }

  _hand(on) {
    if (!!this.space === on) return;
    this.space = on;
    this.v.scroller.classList.toggle('pe-hand', on);
  }

  // Duplicate (Ctrl+D): a copy of each selected comment a step down and right of it, left selected
  async _duplicate(list = this._sels()) {
    this._flushNudge();
    const ok = list.filter((x) => x.type === 'annot' && canClone(x.a));
    if (!ok.length) { this._cantCopy(list); return; }
    const doc = this.doc, made = [];
    for (const x of ok) {
      const r = await this.run('annot_clone', { page: x.page, id: x.id, to: x.page });
      if (this.doc !== doc) return;
      if (r?.result) made.push(r.result);
    }
    this._selectMade(made);
  }

  _cantCopy(list) {
    toast(list.some((x) => x.type === 'annot' && pinned(x.a)) ? 'A mark on words stays on them: select the other words and mark those.' : "That kind of comment can't be copied: place a new one instead.", 'info');
  }

  // what was just pasted or duplicated is left selected, on Select, and brought into sight
  _selectMade(made) {
    const now = made.map((m) => this.annots.find((x) => x.id === m.id && x.page === m.page)).filter(Boolean).map(selOf);
    if (!now.length) return;
    if (this.tool !== 'select') this.setTool('select');
    this.select(now[0], now.slice(1));
    this._showSel();
  }

  // Copy (Ctrl+C) and Cut (Ctrl+X): the selected comments are kept to paste. The worker hands each over whole, so the
  // copy outlives the comment it came from (a cut then deletes them, in one step to undo)
  async _copy(list = this._sels(), cut = false) {
    this._flushNudge();
    const ok = list.filter((x) => x.type === 'annot' && canClone(x.a));
    if (!ok.length) { this._cantCopy(list); return false; }
    const doc = this.doc, clips = [];
    for (const x of ok) {
      const r = await this.run('annot_copy', { page: x.page, id: x.id });
      if (this.doc !== doc) return false;
      if (r?.clip) clips.push(r.clip);
    }
    if (!clips.length) return false;
    CLIP = { clips, doc: doc.id, page: ok[0].page, n: 0 };
    const some = clips.length > 1;
    if (!cut) { toast(`Copied${some ? ` ${clips.length} comments` : ''}. Ctrl+V pastes on the page in view; right-click a page to paste there.`, 'info', 2500); return true; }
    const by = new Map();
    for (const x of ok) by.set(x.page, [...(by.get(x.page) || []), x.id]);
    if (ok.some((x) => this._sels().some(same(x)))) this.select(null);
    const r = await this.run('annot_delete_many', { items: [...by].map(([page, ids]) => ({ page, ids })) });
    if (r) this._gone(`${some ? `${clips.length} comments` : this._label(ok[0].a)} cut. Ctrl+V pastes ${some ? 'them' : 'it'}.`);
    return true;
  }

  // Paste (Ctrl+V, or the page's right-click menu) on a page: with its middle at a point (at: where the pointer was),
  // or else a step on from where it was copied while that place is in sight, or in the middle of what's in sight of
  // the page. So it always lands where it can be seen, and it's left selected
  async _paste(page, at = null) {
    const c = CLIP, p = this.v.pages?.[page];
    if (!this.editable || !p) return;
    if (!c) { toast('Nothing to paste yet: select a comment and press Ctrl+C.', 'info'); return; }
    this._flushNudge();
    const x0 = Math.min(...c.clips.map((k) => k.rect[0])), y0 = Math.min(...c.clips.map((k) => k.rect[1]));
    const x1 = Math.max(...c.clips.map((k) => k.rect[0] + k.rect[2])), y1 = Math.max(...c.clips.map((k) => k.rect[1] + k.rect[3]));
    c.n += 1;
    let d = null;
    if (!at && c.doc === this.doc.id && c.page === page) { // beside the one it came from, if that place can be seen
      const step = 12 * c.n, box = this.v.scroller.getBoundingClientRect(), q = this._screen(p, this._onPage(p, [x0 + step, y0 + step, x1 - x0, y1 - y0]));
      if (!(box.width > 0) || (q.right > box.left && q.left < box.right && q.bottom > box.top && q.top < box.bottom)) d = [step, step];
    }
    if (!d) {
      const m = at || this._midSeen(p), step = at ? 0 : 12 * (c.n - 1);
      d = [m[0] - (x0 + x1) / 2 + step, m[1] - (y0 + y1) / 2 + step];
    }
    const doc = this.doc, made = [];
    for (const clip of c.clips) {
      const r = await this.run('annot_paste', { page, clip, dx: d[0], dy: d[1] });
      if (this.doc !== doc) return;
      if (r?.result) made.push({ ...r.result, page });
    }
    this._selectMade(made);
  }

  // the middle of the part of a page that's in sight, in its points
  _midSeen(p) {
    const b = p.el.getBoundingClientRect(), s = this.v.scroller.getBoundingClientRect();
    const mid = (lo, hi, a, z) => clamp((Math.max(lo, a) + Math.min(hi, z)) / 2, lo, hi);
    return onPagePt(p, this.v._pagePoint(p, { clientX: mid(b.left, b.right, s.left, s.right), clientY: mid(b.top, b.bottom, s.top, s.bottom) }));
  }

  // Edit > Copy: the selected words to the clipboard, or the selected comments kept to paste
  async copy() {
    const s = this.v.selection;
    if (s?.text) { await copyText(s.text); toast('Copied.', 'ok', 1200); }
    else if (this.sel?.type === 'annot') this._copy();
    else toast('Select some words or a comment first.', 'info');
  }

  // Edit > Cut and Paste, for comments (the page's own words are only taken out in the Edit tab)
  cut() { if (this.sel?.type === 'annot') this._copy(this._sels(), true); else toast('Select a comment first.', 'info'); }

  paste() { this._paste(this.v.current || 0); }

  get canPaste() { return !!CLIP; }

  // something was just taken out: say so, with Undo on the toast (it undoes only while that is still the last change)
  _gone(msg) {
    const at = this._edits, doc = this.doc, t = toast(msg, 'info', 6000);
    t.append(h('button', { class: 'btn', text: 'Undo', onclick: () => {
      t.remove();
      if (this.doc !== doc) return;
      if (this._edits === at) this.undo(); else toast('Other changes were made since: Ctrl+Z steps back through them.', 'info', 4000);
    } }));
  }

  // ================================================================== keys
  // (the page view calls this, and only while no dialog or menu is open: see its _key)
  key(e) {
    if (!this.editable) return false;
    const ctrl = e.ctrlKey || e.metaKey, lk = e.key.toLowerCase();
    const done = () => { e.preventDefault(); e.stopPropagation(); return true; };
    if (ctrl && lk === 's') { if (!e.repeat) { if (e.shiftKey) this.saveAs(); else this.save(); } return done(); } // (held down: one save)
    // typing somewhere: the keys are its. A ticked box or a list on a form keeps only the keys that work it, so
    // Ctrl+Z, Esc, Delete and the page keys go on working after one is ticked
    if (typingKey(e)) return false;
    const at = document.activeElement;
    if (e.key === 'Escape' && at && /^(INPUT|SELECT)$/.test(at.tagName) && this.v.scroller.contains(at)) this.v.scroller.focus({ preventScroll: true }); // (and Esc gives the keyboard back to the pages)
    if (this.inline) { this.inline.ta.focus(); return false; } // a box on the page is still being typed in: the keys are its (never a tool's)
    // Something is being dragged: Esc lets go of it, and no other key acts until the button is up (Delete would take
    // what's in the hand, R would turn the page under it)
    if (this._dragOff && e.key !== 'Escape') { if (!['Shift', 'Control', 'Alt', 'Meta'].includes(e.key)) done(); return true; }
    const comment = this.sel?.type === 'annot' ? this.sel : null, asleep = !!this.v.balloons?.on; // (asleep: Balloon is on)
    if (ctrl && lk === 'a') { // every comment on its page while a comment is what's selected, else every word on the page in view
      if (comment && !asleep) this.select(comment, this._top().filter((a) => a.page === comment.page).map(selOf));
      else this._selectPage(this.v.current || 0);
      return done();
    }
    if (e.key === ' ') { this._hand(true); return done(); } // held: drag pans, whatever tool is on
    if (ctrl && lk === 'c' && comment && !this.v.selection?.text) { this._copy(); return done(); }
    if (ctrl && lk === 'x' && comment && !asleep) { this._copy(this._sels(), true); return done(); }
    if (ctrl && lk === 'v' && CLIP && !asleep) { this._paste(this.v.current || 0); return done(); }
    if (ctrl && lk === 'd' && comment) { this._duplicate(); return done(); }
    // Tab steps through the comments in their order (Shift+Tab: back), each brought into sight, while the keyboard
    // is with the pages (on a button or in a list it moves on to the next one, as anywhere)
    if (e.key === 'Tab' && !ctrl && !e.altKey && this.tool === 'select' && !asleep) {
      const f = document.activeElement, list = this._top();
      if (list.length && (!f || f === document.body || this.v.scroller.contains(f))) {
        const cur = this.v.current || 0, n = list.length, back = e.shiftKey;
        let i = comment ? list.findIndex((a) => a.id === comment.id && a.page === comment.page) : -1;
        if (i >= 0) i = (i + (back ? n - 1 : 1)) % n;
        else if (back) { i = n - 1; while (i > 0 && list[i].page > cur) i--; }
        else { i = list.findIndex((a) => a.page >= cur); if (i < 0) i = 0; }
        this.select(selOf(list[i]));
        this._showSel();
        return done();
      }
    }
    // one key picks a tool, in the tabs that have those tools (Forms and Pages have none of them, and a slip of
    // the finger there shouldn't change tab; in Balloon this bar is put away)
    if (!ctrl && !e.altKey && e.key.length === 1 && KEYS[lk] && !asleep && KEY_TABS.has(this.set)) {
      const id = KEYS[lk];
      if (e.repeat) return done(); // (held down: it picks once, it doesn't flick the tool on and off)
      if (id !== 'select' && !SETS.find((s) => s.id === this.set)?.tools.includes(id)) { // its own tab comes forward, so its button is there to see
        this._goSet((SETS.find((s) => s.tools.includes(id)) || SETS[0]).id);
        if (this.tool !== 'select') this.setTool('select'); // (the other tab's tool is put down: words selected are marked at once, below)
      }
      if (id === 'select') this.setTool('select'); else this._pick(id);
      return done();
    }
    if (ctrl && lk === 'z' && !e.shiftKey) { this.undo(); return done(); }
    if (ctrl && (lk === 'y' || (lk === 'z' && e.shiftKey))) { this.redo(); return done(); }
    // Delete, by what was clicked last: the picked pages when that was the thumbnails (it asks first); else the
    // selected field, comment or picture. The page's own words go only in the Edit tab, and never by Backspace
    const del = e.key === 'Delete', back = e.key === 'Backspace';
    if (del && this.v.lastRegion === 'side' && this.picked.size) { this._pagesDelete(); return done(); }
    if ((del || back) && this.set === 'form' && !asleep && this._fselField()) { this._fieldDelete(); return done(); }
    if ((del || back) && this.sel) {
      if (!this._selSeen()) { // never what can't be seen: it's shown first, and the next press takes it
        const many = this.group.length + 1;
        this._showSel();
        toast(`${many > 1 ? `${many} comments are` : `${this.sel.type === 'image' ? 'A picture' : this._label(this.sel.a)} is`} selected: press Delete again to remove ${many > 1 ? 'them' : 'it'}.`, 'info', 3500);
        return done();
      }
      this.deleteSel();
      return done();
    }
    if (back && this.v.selection?.rects?.length) return done(); // (never the page's words, and never a step back in the window either)
    if (del && this.v.selection?.rects?.length && !asleep) {
      if (this.set === 'edit') this.deleteText();
      else {
        const doc = this.doc, t = toast('Open Edit to remove words from the page (Delete takes words out only there).', 'info', 5000);
        t.append(h('button', { class: 'btn', text: 'Open Edit', onclick: () => { t.remove(); if (this.doc === doc && this.editable) this._tab('edit'); } }));
      }
      return done();
    }
    if (e.key === 'Escape') { // one step back for each press
      if (this._cancelDrag() || this.v.selectOff()) return done(); // (a drag across words too: nothing is selected or marked)
      if (this.cropAsk) { this._cropEnd(); return done(); }
      if (this.tool !== 'select') { this.setTool('select'); return done(); }
      if (this.sel) { this.select(null); return done(); }
      if (this.fsel) { this.fsel = null; this._drawFields(); this._bar(); return done(); }
      if (this.v.selection) { this.v.selection = null; this.v._showSelection(); return done(); }
      if (this.v.lastRegion === 'side' && this.picked.size) { this.picked.clear(); this._pickedChanged(); return done(); }
      if (this.v.findQuery || this.v.findIn.value) { this.v._findOff(); return done(); }
      return false;
    }
    if (this.sel && e.key.startsWith('Arrow') && !ctrl) { // nudge what's selected: moved at once, saved once it stops
      const items = this._sels().filter((s) => !(s.type === 'annot' && pinned(s.a)) && this.v.pages?.[s.page]); // (a mark stays on its words)
      if (!items.length || !this._selSeen()) return false; // (nothing to move, or it's out of sight: the arrows scroll the pages)
      const d = e.shiftKey ? 10 : 1, t = this.v.state.turns;
      const [dx, dy] = e.key === 'ArrowLeft' ? [-d, 0] : e.key === 'ArrowRight' ? [d, 0] : e.key === 'ArrowUp' ? [0, -d] : [0, d];
      // (the way the key points on the screen, however the view is turned)
      const [px, py] = t === 1 ? [dy, -dx] : t === 2 ? [-dx, -dy] : t === 3 ? [-dy, dx] : [dx, dy];
      const n = this._nudge ||= { items: items.map((s) => ({ s, r0: [...s.rect] })), timer: null };
      const [mx, my] = this._roomFor(items.map((s) => s.rect), items.map((s) => s.page), px, py); // (together, and none of them off its page)
      for (const s of items) {
        s.rect = [s.rect[0] + mx, s.rect[1] + my, s.rect[2], s.rect[3]];
        s.moved = true; // (a line shows as a box while it's on the move, and its picture goes along)
      }
      this._drawSel();
      clearTimeout(n.timer);
      n.timer = setTimeout(() => this._flushNudge(), 800); // (a run of presses is one move, and one step to undo)
      return done();
    }
    return false;
  }

  // ================================================================== the mouse on the pages
  down(e) {
    if (!this.editable) return false;
    // Space held, or the middle button: the page view pans, whatever is under the pointer (a field, a field's box, a
    // handle). Not in a box being typed in, where Space is a space
    if ((e.button === 1 || (e.button === 0 && this.space)) && !e.target.closest('.pe-inline')) return false;
    if (e.target.closest('.pe-field, .pe-fbox, .pe-inline, .pe-bar')) return true; // theirs: focus, typing, ticking, their buttons
    if (e.button !== 0) return false;
    if (this.inline) { // a click away finishes the typing; only a tool that stays in hand goes on to start its next with the same click
      const it = this.inline, more = this.tool !== 'select' && this._staysOn(this.tool);
      this._endInline(true);
      if (!more) {
        // With Select the same click goes on to what it landed on (another comment to take, words, paper): not on the
        // box just typed in, whose change is still on its way to the worker. A tool that places one thing is done
        const b = this.tool === 'select' ? e.target.closest('.pv-pagebox') : null;
        if (!b || (+b.dataset.page === it.p.i && inRect(it.rect, this.v._pagePoint(it.p, e), this._px(it.p.i, 4)))) return true;
      }
    }
    if (this._popAte === e) { // the same goes for a note's words: this click finished them
      this._popAte = null;
      if (!(this.tool !== 'select' && this._staysOn(this.tool))) return true;
    }
    const handle = e.target.closest('.pe-h');
    if (handle && this.sel) {
      e.preventDefault();
      if (handle.dataset.pt !== undefined) this._pointDrag(e, +handle.dataset.pt);
      else this._sizeDrag(e, +handle.dataset.mx, +handle.dataset.my);
      return true;
    }
    const box = e.target.closest('.pv-pagebox');
    if (!box) { if (this.tool === 'select') this.select(null); return false; }
    const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e), tool = this.tool;
    this.v.scroller.focus({ preventScroll: true });
    if (this.fsel && !FIELD_TOOLS[tool]) { this.fsel = null; this._drawFields(); this._bar(); }
    if (tool === 'select') {
      // as Acrobat: a comment is grabbed, a drag across words selects them, a drag over bare paper pans
      const asleep = !!this.v.balloons?.on, hits = asleep ? [] : this._hitsAt(p.i, pt); // (Balloon is on: comments are left alone)
      if (e.shiftKey || e.ctrlKey || e.metaKey) {
        // Shift or Ctrl + click: the comment joins the ones selected, or leaves them. Ctrl + drag over paper: every
        // comment the box touches. (Shift + drag over paper selects words: the page view's own)
        if (hits.length) { e.preventDefault(); this._toggle(hits[0]); return true; }
        if (asleep || e.shiftKey) return false;
        e.preventDefault();
        this._marquee(e, p, pt);
        return true;
      }
      // One already selected stays the one taken, even with another over it. A click on it (not a drag, and not the
      // second click of a double-click, which opens it) goes on to the next one under the pointer, so comments lying
      // one on another can each be reached. With several selected, a drag from any of them moves them all, and a
      // click on one leaves just that one selected
      const all = this._sels(), many = all.length > 1;
      const cur = hits.find((x) => all.some(same(x))) || null;
      const a = cur || hits[0], now = performance.now(), again = !!cur && !many && hits.length > 1 && now - (this._downAt || 0) > 500;
      this._downAt = now;
      const take = (x) => this.select(selOf(x));
      const next = many && cur ? () => take(cur) : again ? () => take(hits[(hits.indexOf(cur) + 1) % hits.length]) : null;
      if (a) {
        e.preventDefault();
        if (!cur) take(a);
        if (pinned(a) && !(many && cur)) this._tapOrSelect(e, p, next); // a mark on words: selected by the click, and a drag from it selects words as anywhere else
        else this._moveDrag(e, p, pt, next);
        return true;
      }
      this.select(null);
      const bl = this.v.balloons?.near(p.i, pt); // a balloon, with the Balloon tab closed: say what it is, and how to change it
      if (bl) { e.preventDefault(); this.v.balloons.point(bl); return true; }
      // (words not in from the worker yet: the drag is taken as one across words, and it selects only if it starts on some)
      if (!this._onWord(p.i, pt) && this.words[p.i] !== null) return false;
      e.preventDefault();
      this.v.selection = null;
      this.v._showSelection();
      this._selecting = true; // (its bar waits for the drag to end)
      this.v._selectDrag(p, e, () => { this._selecting = false; this._textBar(); });
      return true;
    }
    e.preventDefault();
    if (tool === 'typewriter') { // Add text on words it added before: change them, as Acrobat's Fill & Sign does
      const hit = this._hitAnnot(p.i, pt);
      if (hit?.kind === 'text') { this._editAnnotText(hit); return true; }
    }
    // A tool that adds one comment, pressed on a comment that's there already: a drag still draws (an arrow starts on
    // the text box it points from, a cloud goes round a stamp); only a click takes that comment instead of adding
    // another, back on Select (_take)
    // (kept on to add several: it only ever adds)
    const over = ONE_OFF.has(tool) && !this.keepOn[tool] ? this._hitAnnot(p.i, pt) : null;
    const t = TOOLS[tool] || {};
    if (tool === 'redactText') { // on a form field: the whole field, and what's filled into it
      const f = this.fields.find((x) => x.page === p.i && inRect(x.rect, pt));
      if (f) { this.run('annot_add', { page: p.i, kind: 'redact', rects: [f.rect] }); return true; }
    }
    if (FIELD_TOOLS[tool]) { this._fieldDrag(e, p, pt, over); return true; }
    let held = null; // a strike-through the press landed on, with a tool that makes them
    if (tool === 'strikeText' || tool === 'strikeout') {
      // A click on a strike-through takes it, to Delete or recolor (the tool stays). A drag from it goes on to mark
      // more words like any other drag; only a line that lies off the words is dragged to where it belongs
      const hit = this._hitAnnot(p.i, pt);
      if (hit?.kind === 'strikeout') {
        this.select({ type: 'annot', page: p.i, id: hit.id, rect: hit.rect, a: hit });
        if (!pinned(hit) && !this._onWord(p.i, pt)) { this._moveDrag(e, p, pt); return true; }
        held = hit;
      } else if (this.sel) this.select(null);
    }
    if (tool === 'strikeText' && !held && !this._onWord(p.i, pt) && !e.shiftKey) { // off the words: a drag draws the line where it goes
      this._strikeLine(e, p, pt);
      return true;
    }
    if (t.markup || tool === 'redactText' || tool === 'strikeText') {
      // Only a drag marks: a click selects nothing, so it marks nothing (Cross out alone acts on a click: the
      // dimension or note under it, whole). Whatever was selected before is let go of first: it isn't this drag's
      let moved = false, end = pt;
      const x0 = e.clientX, y0 = e.clientY;
      const watch = (m) => { end = this.v._pagePoint(p, m); if (Math.hypot(m.clientX - x0, m.clientY - y0) > 4) moved = true; };
      const unwatch = () => { window.removeEventListener('pointermove', watch); window.removeEventListener('pointerup', unwatch); window.removeEventListener('pointercancel', unwatch); };
      window.addEventListener('pointermove', watch);
      window.addEventListener('pointerup', unwatch);
      window.addEventListener('pointercancel', unwatch); // (a touch the system took over to scroll: no pointerup ever comes)
      if (this.v.selection) { this.v.selection = null; this.v._showSelection(); }
      this.v._selectDrag(p, e, async (s, off) => {
        if (off) return; // (Esc during the drag: nothing is marked)
        const clear = () => { if (s && this.v.selection === s) { this.v.selection = null; this.v._showSelection(); } };
        if (!moved) {
          clear();
          if (tool === 'strikeText' && !held) await this.run('strike_at', { page: p.i, at: pt, whole: e.shiftKey, color: this.style.colors.strikeText || '#000000' });
          return;
        }
        if (held && this.sel?.id === held.id) this.select(null);
        if (!s?.rects?.length || s.page !== p.i) { clear(); await this._markArea(tool, p, pt, end); return; }
        const r = await this.run('annot_add', this._markArgs(tool, s)); // (the blue selection stays until the mark is there)
        clear();
        if (r?.result?.existing && MARKED_ALREADY[tool]) this._say(MARKED_ALREADY[tool]);
      });
      return true;
    }
    if (tool === 'editImage') { this._imageDown(e, p, pt); return true; }
    if (tool === 'editText') { this._editTextAt(p, pt); return true; }
    if (tool === 'pen') { this._penDrag(e, p, pt); return true; }
    if (tool === 'note' && over?.kind === 'note') { this._take(over); return true; } // (on anything else the note is added: a tool in hand adds)
    if (['note', 'typewriter', 'check', 'cross', 'dot', 'date', 'addText'].includes(tool)) { this._click(p, pt); return true; }
    // everything else is dragged out (a click makes one of a standard size)
    this._shapeDrag(e, p, pt, over);
    return true;
  }

  // a comment clicked with a tool that would have added another: that one is taken, on Select
  _take(a) {
    this.setTool('select');
    this.select(selOf(a));
  }

  // everything selected: the one (a comment, or a picture of the page) and the comments selected along with it
  _sels() { return this.sel ? [this.sel, ...this.group] : []; }

  // the record now standing for something selected a moment ago (the worker's answers make new records)
  _live(x) { return this._sels().find(same(x)) || null; }

  // Shift or Ctrl + click on a comment: it joins the ones selected (and is the one the options strip shows), or leaves
  _toggle(a) {
    const all = this._sels().filter((s) => s.type === 'annot'), i = all.findIndex(same(a));
    if (i >= 0) all.splice(i, 1); else all.unshift(selOf(a));
    this.select(all[0] || null, all.slice(1));
  }

  // Ctrl + drag over paper: a box, and every comment it touches joins the ones selected
  _marquee(e, p, from) {
    const svg = this._ghost(p);
    this._drag(e, p, from, (a, b) => this._ghostShape(svg, p, 'crop', a, b), (a, b, moved) => {
      svg.remove();
      if (!moved) { this.select(null); return; }
      const r = rectOf(a, b), all = this._sels().filter((s) => s.type === 'annot');
      const inBox = this._top().filter((x) => x.page === p.i && x.rect[0] <= r[0] + r[2] && x.rect[0] + x.rect[2] >= r[0] && x.rect[1] <= r[1] + r[3] && x.rect[1] + x.rect[3] >= r[1]);
      for (const x of inBox) if (!all.some(same(x))) all.push(selOf(x));
      this.select(all[0] || null, all.slice(1));
      if (!inBox.length) this._say('No comments in that box', 2000);
    }, () => svg.remove(), { onPage: true });
  }

  // is anything selected where it can be seen now? (Delete and the arrow keys act only on what is)
  _selSeen() {
    const box = this.v.scroller.getBoundingClientRect();
    if (!(box.width > 0 && box.height > 0)) return true;
    return this._sels().some((s) => {
      const p = this.v.pages?.[s.page];
      if (!p) return false;
      const q = this._screen(p, s.rect);
      return q.right >= box.left && q.left <= box.right && q.bottom >= box.top && q.top <= box.bottom;
    });
  }

  // the selected one is brought into sight (moved no further than it takes)
  _showSel() { if (!this._selSeen()) this.sel?.box?.scrollIntoView?.({ block: 'center', inline: 'nearest' }); }

  // is a point on one of a page's words? (the boxes come from the worker once, on the first look)
  _onWord(page, pt, pad = this._px(page, 2)) {
    const w = this.words[page];
    if (w === undefined) this._wordsFor(page);
    return !!w && w.some((r) => inRect(r, pt, pad));
  }

  // A markup tool dragged where no words were selected. On a page with no words at all (a scan, a picture) the drag
  // itself is marked, as Acrobat does: a highlight fills the box dragged, a line goes along the drag. On any other
  // page the options strip says why nothing happened
  async _markArea(tool, p, a, b) {
    const w = await this._wordsFor(p.i);
    if (this.tool !== tool || !this.v.pages?.includes(p)) return;
    if (w?.length) { this._say('No words there to mark: start the drag on the words', 2500); return; }
    if (!MARKS.has(tool)) { this._say('This page has no words to select: use Mark area, and drag a box', 3500); return; }
    const dx = Math.abs(b[0] - a[0]), dy = Math.abs(b[1] - a[1]), thick = 12;
    if (Math.hypot(dx, dy) < this._px(p.i, 6)) return;
    let r = rectOf(a, b);
    if (tool === 'highlight') { // (a drag straight along a line of print: as thick as a line of words)
      if (r[2] < 4) r = [r[0] - thick / 2, r[1], thick, r[3]];
      if (r[3] < 4) r = [r[0], r[1] - thick / 2, r[2], thick];
    } else if (dx >= dy) r = [r[0], tool === 'strikeout' ? a[1] - thick / 2 : a[1] - thick, dx, thick]; // the drag is where the underline goes (a strike: its middle)
    else r = [a[0] - thick / 2, r[1], thick, dy];
    const res = await this.run('annot_add', { page: p.i, kind: tool, rects: [r], quote: '', color: this.style.colors[tool], opacity: this._op(tool) });
    if (res) this._say('No words on this page to select: marked where you dragged', 3500);
  }

  // the words of the pages in view, asked for ahead, so the first drag across text already selects
  _prefetch() {
    if (!this.editable || !this.v.pages?.length || this.v.el.hidden) return;
    for (const p of this.v._visible()) this._wordsFor(p.i);
  }

  _wordsFor(page) {
    if (this.words[page]) return Promise.resolve(this.words[page]);
    if (!this.editable) return Promise.resolve([]);
    this._wordsAsked ||= {};
    if (this.words[page] === null && this._wordsAsked[page]) return this._wordsAsked[page];
    this.words[page] = null;
    const doc = this.doc;
    return (this._wordsAsked[page] = this._ask('words', { page }).then((r) => {
      if (this.doc === doc) this.words[page] = r;
      return r;
    }).catch(() => { if (this.doc === doc) this.words[page] = []; return []; })); // (not to be had: the page is taken as having none, so a drag on it still pans)
  }

  // What a press here would do, shown by the cursor before it. Select: the I-beam over words, a pointer over
  // comments. A tool that marks words: the I-beam only over words, an arrow over paper (a drag from there marks
  // nothing), cross-hairs on a page with no words at all (a drag marks its area), a hand on a strike it would take
  _hover(e) {
    const s = this.v.scroller, tool = this.tool, marks = MARKS.has(tool);
    if (!this.editable || e.buttons) return;
    if (PLACE[tool]) { this._followAt(e); return; }
    if (tool !== 'select' && !marks) return;
    const box = e.target.closest?.('.pv-pagebox');
    let cls = '', over = null;
    if (box && !e.target.closest('.pe-field, .pe-inline, .pe-h, .pe-bar')) {
      const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e);
      if (marks) {
        const hit = tool === 'strikeout' ? this._hitAnnot(p.i, pt) : null;
        if (hit?.kind === 'strikeout') { over = hit; cls = 'pe-over-annot'; }
        else if (this._onWord(p.i, pt, this._px(p.i, 6))) cls = 'pe-over-text';
        else if (this.words[p.i]?.length === 0) cls = 'pe-over-area';
      } else {
        over = this.v.balloons?.on ? null : this._hitAnnot(p.i, pt); // (asleep while Balloon is on: words still select)
        if (over) cls = 'pe-over-annot';
        else if (this._onWord(p.i, pt)) cls = 'pe-over-text';
      }
    }
    this._setHover(over);
    if (s.dataset.over !== cls) {
      s.classList.remove('pe-over-annot', 'pe-over-text', 'pe-over-area');
      if (cls) s.classList.add(cls);
      s.dataset.over = cls;
    }
  }

  // the comment under the pointer: outlined, with who wrote it and what it says
  _setHover(a) {
    const key = a ? `${a.page}:${a.id}` : '';
    if (key === (this._hov || '')) return;
    this._hov = key;
    this.v.sheet.querySelectorAll('.pe-hover').forEach((n) => n.remove());
    this.v.scroller.title = '';
    if (!a) return;
    const p = this.v.pages?.[a.page];
    if (!p) return;
    if (!(this.sel?.type === 'annot' && this.sel.id === a.id && this.sel.page === a.page)) p.edit.append(h('div', { class: 'pe-hover', style: this.v._rectStyle(p, a.rect) }));
    if (this.tool === 'select') this._img(a.page, a.id); // (its picture, asked for ahead: a press and drag in one go carries it from the start)
    const says = a.contents || (a.quote ? `“${a.quote}”` : ''); // its note, or else the words it marks
    this.v.scroller.title = `${this._label(a)}${a.author ? ` · ${a.author}` : ''}${says ? `\n${says}` : ''}`;
  }

  // a signature, stamp or picture about to be placed rides under the pointer, at the size a click gives it
  _placeSize(tool) {
    const [w, hh] = PLACE[tool];
    return [w, this.payload?.aspect ? w / this.payload.aspect : hh];
  }

  _followAt(e) {
    const box = e.target.closest?.('.pv-pagebox');
    if (!box) { this._follow?.remove(); return; }
    const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e), [w, hh] = this._placeSize(this.tool);
    if (!this._follow) {
      this._follow = h('div', { class: 'pe-follow' });
      if (this.payload?.image) this._follow.append(h('img', { src: this.payload.image }));
      else this._follow.append(h('span', { text: STAMP_LABEL[this.payload?.stamp] || '' }));
    }
    if (this._follow.parentNode !== p.edit) p.edit.append(this._follow);
    this._follow.style.cssText = this.v._rectStyle(p, this._onPage(p, [pt[0], pt[1], w, hh])); // (where a click would put it: never over the page's edge)
  }

  // is a point on a comment? A shape with no fill, a line or a drawing is only on its lines (as Acrobat), so the
  // words and paper inside a revision cloud can still be selected and panned
  _onAnnot(a, pt) {
    const tol = this._px(a.page, 5) + Math.max(a.width > 0 ? a.width : 1, 1) / 2; // (5 pixels of the screen, whatever the zoom)
    if (!inRect(a.rect, pt, tol)) return false;
    // a mark on words is only on the words it marks, line by line: the words between and beside them (inside the
    // box round the whole mark) are still the page's, to click and select
    if (MARKS.has(a.kind) && !(a.kind === 'strikeout' && a.segs?.length)) {
      const pad = this._px(a.page, 2);
      if (a.quads?.length) return a.quads.some((q) => inQuad(q, pt, pad));
      if (a.parts?.length) return a.parts.some((r) => inRect(r, pt, pad));
      return true;
    }
    const [x, y, w, hh] = a.rect, thin = w < 3 * tol || hh < 3 * tol;
    if (a.kind === 'rect' && !a.fill) return thin || !inRect([x + tol, y + tol, w - 2 * tol, hh - 2 * tol], pt);
    if (a.kind === 'ellipse' && !a.fill) {
      if (thin) return true;
      const d = Math.hypot((pt[0] - x - w / 2) / (w / 2), (pt[1] - y - hh / 2) / (hh / 2));
      return Math.abs(d - 1) * Math.min(w, hh) / 2 <= tol;
    }
    if (a.kind === 'line' && a.points?.length >= 2) return segDist(pt, a.points[0], a.points[1]) <= tol;
    if (a.kind === 'strikeout' && a.segs?.length) return a.segs.some(([q0, q1, half]) => segDist(pt, q0, q1) <= Math.max(half, this._px(a.page, 3)) + this._px(a.page, 2));
    if (a.kind === 'ink' && a.points?.length) return a.points.some((s) => s.some((q, i) => (i ? segDist(pt, s[i - 1], q) : Math.hypot(pt[0] - q[0], pt[1] - q[1])) <= tol));
    if ((a.kind === 'polygon' || a.kind === 'polyline') && !a.fill && a.points?.length > 1) {
      const ring = a.kind === 'polygon' ? [...a.points, a.points[0]] : a.points;
      return ring.some((q, i) => i && segDist(pt, ring[i - 1], q) <= tol);
    }
    return true;
  }

  // Every comment under a point, the likeliest first: one that is all line (a line, an arrow, a drawing, a shape with
  // no fill) is only hit on its line, so it's the one meant where it crosses something with an inside; then the
  // smallest (it would be out of reach under a larger one), and of two the same size the one on top. A click on
  // the one taken goes on to the next (see down)
  _hitsAt(page, pt) {
    const out = [];
    const lines = (a) => ['line', 'ink', 'polyline'].includes(a.kind) || (a.kind === 'strikeout' && !!a.segs?.length) || (['rect', 'ellipse', 'polygon'].includes(a.kind) && !a.fill);
    this.annots.forEach((a, i) => { if (a.page === page && !a.replyTo && this._onAnnot(a, pt)) out.push([lines(a) ? 0 : 1, a.rect[2] * a.rect[3], -i, a]); });
    return out.sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2]).map((x) => x[3]);
  }

  _hitAnnot(page, pt) { return this._hitsAt(page, pt)[0] || null; }

  // A press on a mark that stays on its words (it's selected already): nothing is dragged. A click leaves it selected
  // (tap: or goes on to the next comment under it); a drag selects words from where it started, as on bare words
  _tapOrSelect(e, p, tap) {
    const x0 = e.clientX, y0 = e.clientY;
    const off = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', off); };
    const mv = (m) => {
      if (Math.hypot(m.clientX - x0, m.clientY - y0) < 4) return;
      off();
      this.select(null);
      this._selecting = true; // (the words' bar waits for the drag to end)
      this.v._selectDrag(p, e, () => { this._selecting = false; this._textBar(); });
    };
    const up = () => { off(); tap?.(); };
    window.addEventListener('pointermove', mv);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', off);
  }

  // follow a drag in page points: move(from, now), then up(from, now, moved). Esc while it's on lets go of it with
  // nothing done: cancel() puts back whatever the drag had changed on the screen
  // The callbacks also get the pointer's event (move(from, now, m), up(from, now, moved, u)): Shift, and a pen's
  // samples between two moves. opts.onPage: the point stays on the page the drag began on (something being drawn;
  // a comment being moved is kept on the page by its own rectangle).
  // Only the pointer that began it counts (a second finger doesn't end it), it holds the pointer once it has moved (so
  // it goes on outside the window), a gesture the system takes over (pointercancel: a touch it scrolls with, a pen
  // out of range) lets go of it like Esc, and held by the edge of what's in sight it scrolls the pages along.
  _drag(e, p, from, move, up, cancel, opts = {}) {
    const s = this.v.scroller, id = e.pointerId;
    const at = (m) => { const q = this.v._pagePoint(p, m); return opts.onPage ? onPagePt(p, q) : q; };
    let now = from, moved = false, last = e, creep = null, armed = false;
    const mine = (m) => id == null || m.pointerId == null || m.pointerId === id;
    const edge = () => { // the pointer is at (or past) an edge of the pages in sight: they scroll, and the drag goes on
      const b = s.getBoundingClientRect(), zone = 10;
      const past = (v, lo, hi) => (v < lo + zone ? v - lo - zone : v > hi - zone ? v - hi + zone : 0);
      const dx = past(last.clientX, b.left, b.left + (s.clientWidth || b.width)), dy = past(last.clientY, b.top, b.top + (s.clientHeight || b.height));
      if (!dx && !dy) { armed = true; return; } // (a drag begun right at an edge scrolls only once it has been away from it, or gone past it)
      if (!armed && Math.abs(dx) <= zone && Math.abs(dy) <= zone) return;
      armed = true;
      const l0 = s.scrollLeft, t0 = s.scrollTop;
      s.scrollLeft += clamp(dx * 0.6, -24, 24);
      s.scrollTop += clamp(dy * 0.6, -24, 24);
      if (s.scrollLeft === l0 && s.scrollTop === t0) return;
      now = at(last);
      move?.(from, now, last);
    };
    const mv = (m) => {
      if (!mine(m)) return;
      // (the button came up where it couldn't be seen, say while the worker was asked something: nothing is dragged
      // by a mouse with no button down)
      if (m.buttons === 0 && m.pointerType === 'mouse') { off(); cancel?.(); return; }
      last = m;
      now = at(m);
      if (!moved) {
        if (Math.hypot(m.clientX - e.clientX, m.clientY - e.clientY) < 3) return;
        moved = true;
        try { s.setPointerCapture(id); } catch { /* not a pointer that can be held */ }
        creep = setInterval(edge, 40);
      }
      move?.(from, now, m);
    };
    const off = () => {
      clearInterval(creep);
      window.removeEventListener('pointermove', mv);
      window.removeEventListener('pointerup', stop);
      window.removeEventListener('pointercancel', stop);
      try { if (moved) s.releasePointerCapture(id); } catch { /* let go of already */ }
      this._dragOff = null;
    };
    const stop = (u) => {
      if (!mine(u)) return;
      off();
      if (u.type === 'pointercancel') { cancel?.(); return; }
      this._lastX = u.clientX;
      this._lastY = u.clientY;
      up(from, now, moved, u);
    };
    this._dragOff?.(); // (one drag at a time)
    this._dragOff = () => { off(); cancel?.(); };
    window.addEventListener('pointermove', mv);
    window.addEventListener('pointerup', stop);
    window.addEventListener('pointercancel', stop);
  }

  // Esc during a drag: was there one to let go of?
  _cancelDrag() {
    if (!this._dragOff) return false;
    this._dragOff();
    return true;
  }

  // ------------------------------------------------------------------ drawing over a page
  // a point in the page's points to the page as shown (turned by the view), in points
  _view(p, [x, y]) {
    const W = p.info.w, H = p.info.h;
    switch (this.v.state.turns) {
      case 1: return [H - y, x];
      case 2: return [W - x, H - y];
      case 3: return [y, W - x];
      default: return [x, y];
    }
  }

  _ghost(p) {
    const [sw, sh] = this.v._size(p);
    p.edit.querySelector('.pe-ghost:not(.pe-ink)')?.remove(); // (pen strokes still on their way in stay where they are)
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'pe-ghost');
    svg.setAttribute('viewBox', `0 0 ${sw} ${sh}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    p.edit.append(svg);
    return svg;
  }

  // What a drag is drawing, as it will be once it's let go of: as thick at any zoom (the ghost is measured in the
  // page's points, as the worker draws), an arrow with its head, a cloud with its scallops, its fill and opacity, a
  // picture in the shape and place it will have. look: { color, width, fill, opacity, image, label }
  _ghostShape(svg, p, kind, a, b, look = {}) {
    const ns = 'http://www.w3.org/2000/svg';
    const el = (tag, attrs) => { const n = document.createElementNS(ns, tag); for (const k in attrs) if (attrs[k] != null) n.setAttribute(k, attrs[k]); return n; };
    svg.replaceChildren();
    const A = this._view(p, a), B = this._view(p, b);
    const x = Math.min(A[0], B[0]), y = Math.min(A[1], B[1]), ww = Math.abs(A[0] - B[0]), hh = Math.abs(A[1] - B[1]);
    const hair = { 'vector-effect': 'non-scaling-stroke' }; // (a guide, not the thing itself: as thin at any zoom)
    const guide = { fill: 'none', stroke: '#2a6ff0', 'stroke-width': 1, 'stroke-dasharray': '4 3', ...hair };
    const w = look.width > 0 ? look.width : 1;
    const drawn = { stroke: look.color || '#e02020', 'stroke-width': w, fill: look.fill || 'none', opacity: look.opacity ?? 1 };
    if (kind === 'ellipse') svg.append(el('ellipse', { cx: x + ww / 2, cy: y + hh / 2, rx: ww / 2, ry: hh / 2, ...drawn }));
    else if (kind === 'rect') svg.append(el('rect', { x, y, width: ww, height: hh, ...drawn }));
    else if (kind === 'cloud') svg.append(el('path', { d: cloudPath(x, y, ww, hh), ...drawn, 'stroke-linejoin': 'round' }));
    else if (kind === 'line' || kind === 'arrow') {
      let d = `M${A[0]} ${A[1]}L${B[0]} ${B[1]}`;
      const len = Math.hypot(B[0] - A[0], B[1] - A[1]);
      if (kind === 'arrow' && len > 0.01) { // an open head as the worker draws it: two strokes back from the point, 30 degrees to each side
        const r = 8.8 * Math.max(w, 1), ux = (A[0] - B[0]) / len, uy = (A[1] - B[1]) / len, c = Math.cos(Math.PI / 6), sn = Math.sin(Math.PI / 6);
        d += `M${B[0] + r * (ux * c - uy * sn)} ${B[1] + r * (uy * c + ux * sn)}L${B[0]} ${B[1]}L${B[0] + r * (ux * c + uy * sn)} ${B[1] + r * (uy * c - ux * sn)}`;
      }
      svg.append(el('path', { d, ...drawn, fill: 'none' }));
    } else if (kind === 'redact') svg.append(el('rect', { x, y, width: ww, height: hh, fill: 'rgba(0,0,0,.25)', stroke: '#c00', 'stroke-width': 1, ...hair }));
    else if (kind === 'crop') svg.append(el('rect', { x, y, width: ww, height: hh, fill: 'rgba(40,110,240,.08)', stroke: '#2a6ff0', 'stroke-dasharray': '5 4', 'stroke-width': 1.5, ...hair }));
    else if (kind === 'text') { // a text box has no outline of its own: what fills it, and a guide round where it will be
      svg.append(el('rect', { x, y, width: ww, height: hh, ...guide, fill: look.fill || 'none', 'fill-opacity': look.opacity ?? 1 }));
    } else { // a stamp, a signature, a picture: itself, turned as the view is turned
      const t = this.v.state.turns, cx = x + ww / 2, cy = y + hh / 2, iw = t % 2 ? hh : ww, ih = t % 2 ? ww : hh;
      const turn = t ? `rotate(${t * 90} ${cx} ${cy})` : null;
      if (look.image) {
        const im = el('image', { x: cx - iw / 2, y: cy - ih / 2, width: iw, height: ih, preserveAspectRatio: 'none', opacity: 0.8, transform: turn });
        im.setAttribute('href', look.image);
        svg.append(im);
      } else if (look.label) {
        const name = el('text', { x: cx, y: cy, 'text-anchor': 'middle', 'dominant-baseline': 'central', fill: '#c22', 'font-weight': 600, 'font-family': 'sans-serif',
          'font-size': Math.max(Math.min(ih * 0.45, iw / Math.max(look.label.length, 1) * 1.3), 0.1), transform: turn });
        name.textContent = look.label.toUpperCase();
        svg.append(name);
      }
      svg.append(el('rect', { x, y, width: ww, height: hh, ...guide }));
    }
  }

  // Shift held while it's dragged out: a rectangle is a square, an oval a circle, a cloud as wide as it's tall, and a
  // line or an arrow lies level, upright or at 45 degrees (from a: where it began, or a line's other end). The
  // result never leaves the page
  _constrain(p, tool, a, b, shift) {
    if (!shift) return b;
    const dx = b[0] - a[0], dy = b[1] - a[1], W = p.info.w, H = p.info.h;
    const room = (d, at, most) => (d > 0 ? most - at : d < 0 ? at : Infinity); // how far it can go that way
    if (tool === 'line' || tool === 'arrow') {
      const ang = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * Math.PI / 4;
      const c = Math.abs(Math.cos(ang)) < 1e-9 ? 0 : Math.cos(ang), sn = Math.abs(Math.sin(ang)) < 1e-9 ? 0 : Math.sin(ang);
      const len = Math.min(Math.hypot(dx, dy), c ? room(c, a[0], W) / Math.abs(c) : Infinity, sn ? room(sn, a[1], H) / Math.abs(sn) : Infinity);
      return [a[0] + len * c, a[1] + len * sn];
    }
    if (tool === 'rect' || tool === 'ellipse' || tool === 'cloud') {
      const side = Math.max(0, Math.min(Math.max(Math.abs(dx), Math.abs(dy)), room(dx || 1, a[0], W), room(dy || 1, a[1], H)));
      return [a[0] + (dx < 0 ? -side : side), a[1] + (dy < 0 ? -side : side)];
    }
    return b;
  }

  // Dragged out with a tool (a click makes one of a usual size). over: a comment the press landed on, which a click
  // takes instead (see down)
  _shapeDrag(e, p, from, over = null) {
    this._cropEnd();
    this._follow?.remove(); // (what rode under the pointer gives way to what's being dragged out)
    const tool = this.tool, st = this.style, svg = this._ghost(p), asp = PLACE[tool] ? this.payload?.aspect || 0 : 0;
    const drawn = ['rect', 'ellipse', 'cloud', 'line', 'arrow'].includes(tool), lined = tool === 'line' || tool === 'arrow';
    const look = drawn ? { color: st.colors[tool] || '#e02020', width: this._wd(tool), opacity: this._op(tool), fill: lined ? null : st.fills[tool] }
      : tool === 'text' ? { fill: st.fills.text, opacity: this._op('text') }
        : { image: this.payload?.image, label: tool === 'stamp' ? STAMP_LABEL[this.payload?.stamp] || '' : '' };
    this._drag(e, p, from, (a, b0, m) => {
      const b = this._constrain(p, tool, a, b0, m?.shiftKey);
      if (!asp) { this._ghostShape(svg, p, tool, a, b, look); return; }
      const r = fitIn(rectOf(a, b), asp); // (a picture keeps its shape: as large as fits the box dragged, in its middle)
      this._ghostShape(svg, p, tool, [r[0], r[1]], [r[0] + r[2], r[1] + r[3]], look);
    }, async (a, b0, moved, u) => {
      svg.remove();
      const b = this._constrain(p, tool, a, b0, u?.shiftKey);
      const px = this._px(p.i, 1), tiny = !moved || Math.hypot(b[0] - a[0], b[1] - a[1]) < 4 * px; // a click, or as good as one
      if (tiny && over) { this._take(over); return; }
      const color = st.colors[tool];
      if (lined) { // whichever way it's dragged: level and upright too
        if (tiny) { this._say('Drag to draw it: a click alone adds nothing', 2500); return; }
        await this.run('annot_add', { page: p.i, kind: tool, points: [a, b], color, width: this._wd(tool), opacity: this._op(tool) });
        return;
      }
      let r = rectOf(a, b);
      const thick = (least) => { const w = Math.max(r[2], least), hh = Math.max(r[3], least); return this._onPage(p, [r[0] - (w - r[2]) / 2, r[1] - (hh - r[3]) / 2, w, hh]); };
      if (tool === 'redact' || tool === 'crop') { // an area: a click marks none, and one dragged thin is given a little body
        if (tiny) { this._say(tool === 'crop' ? 'Drag a box round the part of the page to keep' : 'Drag a box over what to mark', 2500); return; }
        r = thick(tool === 'crop' ? 18 : 4);
      } else if (drawn && !tiny) r = thick(Math.max(this._wd(tool), 2)); // a shape is the size it's dragged to, however thin
      else if (tiny || r[2] < 4 * px || r[3] < 4 * px) { // a click: one of a usual size where it was clicked, moved in from the page's edge
        const sized = PLACE[tool] ? this._placeSize(tool) : { text: [200, 40], rect: [60, 40], ellipse: [60, 40], cloud: [80, 50] }[tool];
        if (!sized) return;
        r = this._onPage(p, [a[0], a[1], ...sized]);
      } else if (asp) r = fitIn(r, asp); // (as it was shown while dragged)
      if (drawn) await this.run('annot_add', { page: p.i, kind: tool, rect: r, color, ...(st.fills[tool] ? { fill: st.fills[tool] } : {}), width: this._wd(tool), opacity: this._op(tool) });
      else if (tool === 'text') this._typeInto(p, [...r], { kind: 'text', fill: st.fills.text || null });
      else if (tool === 'stamp') await this.run('annot_add', { page: p.i, kind: 'stamp', rect: r, ...(this.payload?.image ? { image: this.payload.image } : { stamp: this.payload?.stamp || 'Approved' }) });
      else if (tool === 'sign' || tool === 'initials') await this.run('annot_add', { page: p.i, kind: 'stamp', rect: r, image: this.payload.image, subject: tool === 'sign' ? 'Signature' : 'Initials' });
      else if (tool === 'addImage') { await this.run('image_add', { page: p.i, rect: r, image: this.payload.image }); this.setTool('editImage'); }
      else if (tool === 'redact') await this.run('annot_add', { page: p.i, kind: 'redact', rects: [r] });
      else if (tool === 'crop') this._cropAsk(p, r);
    }, () => svg.remove(), { onPage: true });
  }

  // Strike through, from off the words: a drag puts a strike line across anything (lines, symbols drawn as outlines,
  // pictures, scans) where it's dragged, kept straight when nearly level or upright; a click strikes the symbol there
  _strikeLine(e, p, from) {
    const color = this.style.colors.strikeText || '#000000', svg = this._ghost(p);
    const ns = 'http://www.w3.org/2000/svg', line = document.createElementNS(ns, 'line');
    Object.entries({ stroke: color, 'stroke-width': 2, 'vector-effect': 'non-scaling-stroke', 'stroke-linecap': 'butt' }).forEach(([k, v]) => line.setAttribute(k, v));
    svg.append(line);
    const level = (a, b) => { // within 4 degrees of level or upright: exactly so
      const dx = b[0] - a[0], dy = b[1] - a[1], ang = Math.abs(Math.atan2(dy, dx) * 180 / Math.PI);
      if (ang < 4 || ang > 176) return [b[0], a[1]];
      if (Math.abs(ang - 90) < 4) return [a[0], b[1]];
      return b;
    };
    this._drag(e, p, from, (a, b) => {
      const [x1, y1] = this._view(p, a), [x2, y2] = this._view(p, level(a, b));
      Object.entries({ x1, y1, x2, y2 }).forEach(([k, v]) => line.setAttribute(k, v));
    }, async (a, b, moved) => {
      svg.remove();
      if (!moved || Math.hypot(b[0] - a[0], b[1] - a[1]) < this._px(p.i, 4)) { // (as good as a click, at any zoom)
        await this.run('strike_at', { page: p.i, at: a, whole: false, color });
        return;
      }
      b = level(a, b);
      const len = Math.hypot(b[0] - a[0], b[1] - a[1]), h = 5, ux = (b[0] - a[0]) / len, uy = (b[1] - a[1]) / len;
      const up = [uy * h, -ux * h]; // (y runs down the page)
      const quad = [[a[0] + up[0], a[1] + up[1]], [b[0] + up[0], b[1] + up[1]], [a[0] - up[0], a[1] - up[1]], [b[0] - up[0], b[1] - up[1]]];
      await this.run('annot_add', { page: p.i, kind: 'strike', quads: [quad], free: true, text: '', color });
    }, () => svg.remove(), { onPage: true });
  }

  // Draw. Strokes made one after another are one drawing (a word, a check mark, a sketch): they wait on the page, as
  // drawn, until the pen has rested a moment or anything else is done (another tool, any other edit, Save), and go to
  // the worker together: one comment to select, move and delete, and one step of Undo. Until then Ctrl+Z takes back
  // the last stroke. A tap leaves a dot.
  _penDrag(e, p, from) {
    const look = { color: this.style.colors.pen, width: this._wd('pen'), opacity: this._op('pen') };
    let ink = this._ink;
    if (ink && (ink.p !== p || ink.color !== look.color || ink.width !== look.width || ink.opacity !== look.opacity)) { this._inkFlush(); ink = null; }
    ink ||= this._inkOpen(p, look);
    clearTimeout(ink.timer);
    const ns = 'http://www.w3.org/2000/svg', line = document.createElementNS(ns, 'polyline'), w = Math.max(look.width, 0.1);
    Object.entries({ fill: 'none', stroke: look.color, 'stroke-width': w, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }).forEach(([k, v]) => line.setAttribute(k, v));
    ink.svg.append(line);
    // points are taken as the pen gives them (every sample between two moves, not one a move), a pixel and a half
    // apart at least, and each is added to what's drawn so far (nothing is drawn over from the start)
    const pts = [from], gap = this._px(p.i, 1.5);
    let str = this._view(p, from).join(','), seen = null;
    const add = (q, always = false) => {
      const l = pts[pts.length - 1], d = Math.hypot(q[0] - l[0], q[1] - l[1]);
      if (d < gap && !(always && d > 0)) return;
      pts.push(q);
      str += ` ${this._view(p, q).join(',')}`;
    };
    this._drag(e, p, from, (a, b, m) => {
      const between = m && m !== seen && m.getCoalescedEvents ? m.getCoalescedEvents() : [];
      seen = m;
      for (const c of between) add(onPagePt(p, this.v._pagePoint(p, c)));
      add(b);
      line.setAttribute('points', str);
    }, (a, b, moved) => {
      let el = line;
      if (moved) { add(b, true); line.setAttribute('points', str); }
      if (pts.length < 2) { // a tap: a dot as wide as the pen
        const [cx, cy] = this._view(p, from);
        el = document.createElementNS(ns, 'circle');
        Object.entries({ cx, cy, r: w / 2, fill: look.color }).forEach(([k, v]) => el.setAttribute(k, v));
        line.remove();
        pts.length = 1;
      }
      if (this._ink !== ink) { ink = this._inkOpen(p, look); } // (what there was went in while this stroke was drawn: it starts the next drawing)
      ink.svg.append(el);
      ink.strokes.push(pts);
      ink.els.push(el);
      this._inkWait();
    }, () => { line.remove(); this._inkWait(); }, { onPage: true });
  }

  _inkOpen(p, look) {
    const svg = this._ghost(p);
    svg.classList.add('pe-ink');
    svg.style.opacity = look.opacity;
    return (this._ink = { ...look, p, svg, doc: this.doc, turns: this.v.state.turns, strokes: [], els: [], timer: null });
  }

  // the strokes wait a moment for the next one (none left: nothing is waiting)
  _inkWait() {
    const ink = this._ink;
    if (!ink) return;
    clearTimeout(ink.timer);
    if (ink.strokes.length) {
      ink.timer = setTimeout(() => this._inkFlush(), 1500);
      if (!this.doc.pdfDirty) { this.doc.pdfDirty = true; this.v.app?.shell?.renderDocTabs(); } // (drawn, if not in the file yet: it shows as unsaved at once)
    } else {
      ink.svg.remove();
      this._ink = null;
      if (this.doc && this.state) this.doc.pdfDirty = !!this.state.dirty;
    }
    this._syncFile();
  }

  _inkArgs(ink) { return { page: ink.p.i, kind: 'ink', points: ink.strokes, color: ink.color, width: ink.width, opacity: ink.opacity }; }

  // the strokes drawn so far go to the worker as one drawing (they stay on the page, as drawn, until it has them)
  _inkFlush() {
    const ink = this._ink;
    if (!ink) return null;
    this._ink = null;
    clearTimeout(ink.timer);
    if (!ink.strokes.length || this.doc !== ink.doc) { ink.svg.remove(); return null; }
    const go = this.run('annot_add', this._inkArgs(ink));
    go.then(() => ink.svg.remove());
    return go;
  }

  // Undo with strokes still waiting: the last one is taken back (was there one?)
  _inkBack() {
    const ink = this._ink;
    if (!ink?.strokes.length) return false;
    ink.strokes.pop();
    ink.els.pop().remove();
    this._inkWait();
    return true;
  }

  // The document is being left (put aside for another, or closed) with strokes still waiting: they go straight to
  // its worker, which is still there when it's only put aside
  _inkLeave() {
    const ink = this._ink;
    if (!ink) return;
    this._ink = null;
    clearTimeout(ink.timer);
    ink.svg.remove();
    if (ink.strokes.length && ink.doc) api.pdfEdit(ink.doc.id, 'annot_add', this._inkArgs(ink)).catch(() => {});
  }

  // a click with the note, check, cross, dot, date and text tools
  async _click(p, pt) {
    const st = this.style, tool = this.tool, color = st.colors[tool];
    if (tool === 'note') {
      this._noteAt(p, pt);
    } else if (tool === 'check' || tool === 'cross' || tool === 'dot') {
      const s = 12;
      const at = (q) => [pt[0] - s / 2 + q[0] * s, pt[1] - s / 2 + q[1] * s];
      if (tool === 'dot') {
        await this.run('annot_add', { page: p.i, kind: 'ellipse', rect: [pt[0] - 3, pt[1] - 3, 6, 6], color, fill: color, width: 0.5, subject: 'Dot' });
      } else {
        const strokes = tool === 'check' ? [CHECK.map(at)] : CROSS.map((s2) => s2.map(at));
        await this.run('annot_add', { page: p.i, kind: 'ink', points: strokes, color, width: 1.8, subject: tool === 'check' ? 'Check' : 'Cross' });
      }
    } else if (tool === 'date') {
      const text = new Date().toLocaleDateString();
      await this.run('annot_add', { page: p.i, kind: 'text', rect: [pt[0], pt[1] - st.fontsize * 0.85, 0, 0], fit: true, text, fontsize: st.fontsize, textColor: color, subject: 'Date' });
    } else if (tool === 'typewriter') {
      this._typeInto(p, [pt[0], pt[1] - st.fontsize * 0.85, 0, 0], { kind: 'text', grow: true });
    } else if (tool === 'addText') {
      this._typeInto(p, [pt[0], pt[1] - st.fontsize * 0.85, 0, 0], { kind: 'content', grow: true });
    }
  }

  // a sticky note at a point: its words are asked for first, and a note with none isn't added
  _noteAt(p, pt) {
    this._popup(p, [pt[0], pt[1], 0, 0], '', async (text) => {
      if (text.trim()) await this.run('annot_add', { page: p.i, kind: 'note', at: pt, contents: text, color: this.style.colors.note });
      else toast('Empty note not added.', 'info', 1800);
    }, 'Note');
  }

  // a box just big enough for some words at a size (the 14 standard fonts run about half an em a letter)
  _fit(at, text, size) {
    const lines = String(text).split('\n');
    const w = Math.max(...lines.map((l) => l.length), 1) * size * 0.56 + 6, hh = lines.length * size * 1.25 + 4;
    return [at[0], at[1], w, hh];
  }

  // ------------------------------------------------------------------ typing on the page
  // A box to type in over the page; done(text, it) when it's left (it: the box's record, with the size, color and
  // fill it ended with: the options strip changes them while it's typed in). enter: what Enter does. 'line' starts
  // a new line (Ctrl+Enter or a click away finishes); 'done' finishes (a single line of the page's own words). Esc
  // always cancels. The rule is printed under the box, and in the options strip.
  // kind: 'annot' (a text comment), 'content' (new words for the page itself) or 'line' (a line of the page's own).
  // grow: the box has no size of its own, it fits its words. boxed: it has an inside to fill. styleKey: the tool
  // whose settings a new box takes, and gives back. dir: which way its words run, as the page is shown. base: the
  // first line's baseline, for words typed where the page was clicked. back: what covers the old words under it.
  _inlineBox(p, rect, opts) {
    const { value = '', size = 12, color = '#000000', font = '', grow = false, fill = null, enter = 'line', kind = 'annot',
      boxed = false, styleKey = null, dir = null, base = null, back = null, annot = null, done } = opts;
    this._endInline(true);
    const ta = h('textarea', { class: `pe-inline${grow ? ' grow' : ''}${kind === 'line' ? ' pe-editline' : ''}${kind === 'content' ? ' pe-pagetext' : ''}`, spellcheck: 'true' });
    ta.value = value;
    ta.style.font = font || `${size}px Helvetica, Arial, sans-serif`;
    ta.style.lineHeight = '1.2'; // (the font shorthand resets it; the worker sets lines 1.2 apart)
    const says = h('div', { class: 'pe-inline-hint', text: enter === 'line' ? 'Enter: new line · Ctrl+Enter or click away: done · Esc: cancel' : 'Enter or click away: done · Esc: cancel' });
    // pad: the room the worker leaves inside a text comment's box, in points; a line of the page starts at its box's edge
    this.inline = { p, rect, ta, size, color, fill, grow, enter, says, done, kind, boxed, styleKey, dir, base, back, opts, value, annot,
      pad: kind === 'annot' ? [2, 1] : [0, 0] };
    p.edit.append(ta, says);
    if (annot) this._drawSel(); // (the selection's handles and bar step aside while its words are typed)
    this._paintInline();
    this._placeInline();
    this._optsBar(); // (says what Enter does in this box, and shows its settings)
    ta.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') {
        e.preventDefault();
        if (menuOpen()) closeMenus(); else this._endInline(false); // (one step for each press: an open menu first)
      } else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey || enter === 'done')) { e.preventDefault(); this._endInline(true); }
    });
    ta.addEventListener('input', () => {
      if (this.inline?.ta !== ta) return;
      this.inline.typed = true; // (words the worker doesn't have yet: the document shows as unsaved)
      this._touch();
      this._placeInline();
    });
    // Leaving the box finishes it. Not when it's only the window that was left (another program looked at: the
    // typing goes on when it's back), and not for the box's own settings in the options strip and their menus.
    ta.addEventListener('blur', (e) => {
      const to = e.relatedTarget;
      if (to && (this.opts.contains(to) || to.closest?.('.menu'))) return;
      setTimeout(() => { if (this.inline?.ta === ta && document.hasFocus() && document.activeElement !== ta) this._endInline(true); }, 0);
    });
    setTimeout(() => { // new words: ready to type; words there already: the caret after them (a key must not wipe them)
      ta.focus();
      ta.setSelectionRange(ta.value.length, ta.value.length);
      if (this.inline?.ta === ta) this._placeHint();
    }, 0);
  }

  // the box's color and what's behind its words, as they'll be on the page
  _paintInline() {
    const it = this.inline;
    it.ta.style.color = it.color || '#000000';
    it.ta.style.background = it.fill || it.back || ''; // (none: see through, or the faint white a growing box has)
  }

  // The box where its words will be: starting at the same place, running the same way (text up the side of a
  // drawing, a view that's turned), wrapping where the worker wraps, and kept on the page as it grows.
  _placeInline() {
    const it = this.inline, { p, rect, ta, grow, kind } = it;
    const [sw, sh] = this.v._size(p), k = p.cssW / sw; // css px per point
    const W = p.info.w, H = p.info.h, t = this.v.state.turns;
    let d = it.dir || [1, 0];
    const n = Math.hypot(d[0], d[1]) || 1;
    d = [d[0] / n, d[1] / n];
    // the box in the words' own frame: L along them, T across, C its corner where they start (the page as shown)
    const ax = Math.abs(d[0]), ay = Math.abs(d[1]);
    let L = rect[2], T = rect[3];
    if (ay > 0.01 && ax < 0.01) { L = rect[3]; T = rect[2]; }
    else if (ay > 0.01) { // on a slant: its box takes in more than the words
      T = Math.min(it.size * 1.38, rect[2], rect[3]);
      L = Math.max(ax >= ay ? (rect[2] - T * ay) / ax : (rect[3] - T * ax) / ay, T);
    }
    const C = [rect[0] - Math.min(0, L * d[0]) - Math.min(0, -T * d[1]), rect[1] - Math.min(0, L * d[1]) - Math.min(0, T * d[0])];
    const Cv = this._view(p, C);
    let dv = d;
    for (let i = 0; i < t; i++) dv = [-dv[1], dv[0]]; // (the view's turn, a quarter clockwise each)
    const ang = Math.atan2(dv[1], dv[0]) * 180 / Math.PI;
    // how far the words can run before the page's edge, and how far back the box can slide to stay on the page
    const square = ax < 0.01 || ay < 0.01;
    const room = !square ? Infinity : ax > ay ? (d[0] > 0 ? W - C[0] : C[0]) : (d[1] > 0 ? H - C[1] : C[1]);
    const behind = !square ? 0 : ax > ay ? (d[0] > 0 ? C[0] : W - C[0]) : (d[1] > 0 ? C[1] : H - C[1]);
    const st = ta.style;
    st.left = `${Cv[0] / sw * 100}%`;
    st.top = `${Cv[1] / sh * 100}%`;
    st.fontSize = `${it.size * k}px`;
    st.padding = `${it.pad[1] * k}px ${it.pad[0] * k}px`;
    st.transformOrigin = '0 0';
    st.minWidth = st.maxWidth = st.minHeight = '';
    if (grow) { // fits its words: a text comment wraps where the worker will wrap it, the page's own words don't wrap
      st.width = st.height = '';
      st.minWidth = `${Math.min(40, room + behind) * k}px`;
      st.maxWidth = `${(kind === 'annot' ? Math.max(room, Math.min(room + behind, 8 * it.size)) : room + behind) * k}px`;
    } else if (kind === 'line') { // one line: as long as it was, and longer as words are added
      st.width = '';
      st.height = `${T * k}px`;
      st.minWidth = `${L * k}px`;
    } else { // a box of a set width: its words wrap in it, and it grows down to hold them (as it will on the page)
      st.width = `${L * k}px`;
      st.height = `${T * k}px`;
      if (ta.scrollHeight > ta.clientHeight + 1) st.height = `${ta.scrollHeight}px`;
    }
    const slide = grow || kind === 'line' ? clamp(ta.offsetWidth - room * k, 0, behind * k) : 0;
    // (the page's own words: their baseline right on the click. A browser sets it a little lower in the line than the worker)
    const lift = kind === 'content' ? -0.09 * it.size * k : 0;
    st.transform = ang || slide || lift ? `rotate(${ang}deg) translate(${-slide}px, ${lift}px)` : '';
    this._placeHint();
  }

  // the line that says what Enter does: just under the box (above it when the box is at the foot of the page)
  _placeHint() {
    const { p, ta, says } = this.inline;
    const a = ta.getBoundingClientRect(), b = p.edit.getBoundingClientRect();
    const under = a.bottom - b.top + 3, room = b.height;
    says.style.left = `${Math.max(0, Math.min(a.left - b.left, b.width - says.offsetWidth))}px`;
    says.style.top = `${room && under + 18 > room ? Math.max(0, a.top - b.top - 20) : under}px`;
  }

  // commit: its words go in (done). Not: they're dropped, and (unless quiet) a toast offers them back, since
  // nothing reached the worker for Undo to bring back
  _endInline(commit, quiet = false) {
    const it = this.inline;
    if (!it) return;
    this.inline = null;
    it.ta.remove();
    it.says.remove();
    if (it.annot) this._drawSel();
    this._optsBar();
    const text = it.ta.value, doc = this.doc;
    if (commit) { Promise.resolve(it.done(text, it)).catch(() => {}).finally(() => this._calm(doc)); return; }
    if (!quiet && text.trim() && text !== it.value) {
      const t = toast('Typing canceled.', 'info', 6000);
      t.append(h('button', { class: 'btn', text: 'Put it back', onclick: () => { t.remove(); if (this.doc === doc) this._retype(it, text); } }));
    }
    this._calm(doc);
  }

  // the box open again with the words it had (they were canceled by mistake, or the worker couldn't take them)
  _retype(it, text) {
    if (!this.doc) return;
    const p = this.v.pages?.[it.p.i];
    if (this.inline || !p) { // (another box is open, or the page isn't there: offered back, never dropped)
      const doc = this.doc, t = toast('Your typing was not added.', 'info', 8000);
      t.append(h('button', { class: 'btn', text: 'Put it back', onclick: () => { t.remove(); if (this.doc === doc) this._retype(it, text); } }));
      return;
    }
    if (p !== it.p) it = { ...it, p };
    this._inlineBox(it.p, it.rect, { ...it.opts, value: text, size: it.size, color: it.color, fill: it.fill });
    this.inline.value = it.value; // (still measured against what was there first)
    this.inline.typed = true;
    this._touch();
  }

  // type a text box, text straight onto the page (grow), or words into the page itself (kind 'content')
  _typeInto(p, rect, { kind, fill = null, grow = false }) {
    const st = this.style, key = kind === 'content' ? 'addText' : this.tool === 'typewriter' ? 'typewriter' : 'text';
    this._inlineBox(p, rect, { size: st.fontsize, color: st.colors[key], grow, fill, kind: kind === 'content' ? 'content' : 'annot',
      styleKey: key, boxed: key === 'text', base: grow ? rect[1] + st.fontsize * 0.85 : null,
      done: async (text, it) => {
        if (!text.trim()) return;
        const { size, color } = it, at = it.rect;
        let r;
        if (kind === 'content') {
          r = await this.run('text_add', { page: p.i, at: [at[0], at[1] + size * 0.85], text, size, color });
          if (r) this._say('Now part of the page itself: Edit text changes it, a line at a time', 3500);
        } else {
          // (opacity: a text box's own; text typed straight onto a form is always solid)
          r = await this.run('annot_add', { page: p.i, kind: 'text', rect: grow ? this._fit([at[0], at[1]], text, size) : at, fit: grow, text,
            fontsize: size, textColor: color, fill: it.fill || null, ...(key === 'text' ? { opacity: this._op('text') } : {}),
            subject: key === 'typewriter' ? 'Typewriter' : 'Text Box' });
        }
        if (!r) this._retype(it, text); // (it couldn't be added, and the toast says why: the words are still there to change)
      } });
  }

  // A floating box for a comment's words (notes, and any comment double-clicked). What's typed is kept when the box
  // is left: OK, Ctrl+Enter, a press anywhere else, another one opened, a save. Cancel and Esc drop it. It stays by
  // its place on the page as the pages scroll, until it's dragged somewhere by its title.
  _popup(p, rect, value, done, title) {
    this._pop?.shut(true);
    const ta = h('textarea', { class: 'pe-pop-text', placeholder: 'Type a comment' });
    ta.value = value;
    const head = h('div', { class: 'pe-pop-head', text: title, title: 'Drag to move this out of the way' });
    let open = true, own = false; // (own: it was dragged to a place of its own)
    const shut = (commit) => { // (once: OK and the press that follows it can't both add the note)
      if (!open) return;
      open = false;
      pop.remove();
      document.removeEventListener('pointerdown', away, true);
      this.v.scroller.removeEventListener('scroll', place);
      if (this._pop === pop) this._pop = null;
      const doc = this.doc;
      if (commit) Promise.resolve(done(ta.value)).catch(() => {}).finally(() => this._calm(doc)); else this._calm(doc);
    };
    const pop = h('div', { class: 'pe-pop' },
      head, ta,
      h('div', { class: 'pe-pop-foot' }, h('span', { class: 'pv-of', text: 'Ctrl+Enter' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => shut(false) }),
        h('button', { class: 'btn primary', text: 'OK', onclick: () => shut(true) })));
    const place = () => {
      if (own || p.el.isConnected === false) return;
      const r = p.el.getBoundingClientRect(), [sw, sh] = this.v._size(p);
      const at = this._view(p, [rect[0] + rect[2], rect[1]]);
      pop.style.left = `${clamp(r.left + at[0] / sw * r.width + 12, 8, innerWidth - 300)}px`;
      pop.style.top = `${clamp(r.top + at[1] / sh * r.height, 60, innerHeight - 220)}px`;
    };
    const away = (e) => { // a press anywhere else: the words are kept
      if (pop.contains(e.target)) return;
      this._popAte = e; // (on the pages that press does no more than this, unless the tool in hand stays on: see down)
      shut(true);
    };
    ta.addEventListener('keydown', (e) => {
      e.stopPropagation();
      if (e.key === 'Escape') shut(false);
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); shut(true); }
    });
    ta.addEventListener('input', () => { pop.typed = true; this._touch(); }); // (words the worker doesn't have yet: the document shows as unsaved)
    head.addEventListener('pointerdown', (e) => { // dragged by its title, off whatever it covers
      if (e.button !== 0) return;
      e.preventDefault();
      own = true;
      const r0 = pop.getBoundingClientRect(), dx = e.clientX - r0.left, dy = e.clientY - r0.top;
      try { head.setPointerCapture(e.pointerId); } catch { /* not a pointer that can be held */ }
      const move = (m) => {
        pop.style.left = `${clamp(m.clientX - dx, 0, innerWidth - 60)}px`;
        pop.style.top = `${clamp(m.clientY - dy, 0, innerHeight - 30)}px`;
      };
      const up = () => { head.removeEventListener('pointermove', move); head.removeEventListener('pointerup', up); head.removeEventListener('pointercancel', up); ta.focus(); };
      head.addEventListener('pointermove', move);
      head.addEventListener('pointerup', up);
      head.addEventListener('pointercancel', up);
    });
    place();
    document.body.append(pop);
    document.addEventListener('pointerdown', away, true);
    this.v.scroller.addEventListener('scroll', place);
    pop.shut = shut;
    this._pop = pop;
    setTimeout(() => ta.focus(), 0);
  }

  _dbl(e) {
    if (!this.editable) return;
    if (MARKS.has(this.tool) || this.tool === 'redactText') { this._markWord(e, this.tool); return; } // a tool that marks words: the word double-clicked
    if (this.tool !== 'select') return;
    if (e.target.closest?.('.pe-bar, .pe-h, .pe-field, .pe-fbox, .pe-inline')) return; // (a bar's button or a handle clicked twice: theirs)
    if (this.v.balloons?.on || !this.sel || this.sel.type !== 'annot' || this.group.length) { this._selectWord(e); return; }
    const a = this.sel.a, p = this.v.pages[a.page], box = e.target.closest?.('.pv-pagebox');
    // the selected comment opens only when it's the thing double-clicked (not from a double-click somewhere else)
    if (!box || +box.dataset.page !== a.page || !this._hitsAt(a.page, this.v._pagePoint(p, e)).some((x) => x.id === a.id)) { this._selectWord(e); return; }
    if (a.kind === 'text') {
      this._editAnnotText(a);
    } else {
      this._popup(p, a.rect, a.contents, (text) => { if (text !== a.contents) this.run('annot_set', { page: a.page, id: a.id, contents: text }); }, this._label(a));
    }
  }

  // a double-click with a tool that marks words marks the word under it
  async _markWord(e, tool) {
    const box = e.target.closest?.('.pv-pagebox');
    if (!box || this.v.balloons?.on) return;
    const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e), doc = this.doc;
    const words = await this._wordsFor(p.i), pad = this._px(p.i, 2);
    const w = (words || []).find((r) => inRect(r, pt, pad));
    if (!w || this.doc !== doc || this.tool !== tool) return;
    const mid = [w[0] + w[2] / 2, w[1] + w[3] / 2];
    const s = await api.pdfSelect(doc.id, { page: p.i, ax: mid[0], ay: mid[1], bx: mid[0], by: mid[1] }).catch(() => null);
    if (!s?.rects?.length || this.doc !== doc) return;
    const r = await this.run('annot_add', this._markArgs(tool, { page: p.i, ...s }));
    if (r?.result?.existing && MARKED_ALREADY[tool]) this._say(MARKED_ALREADY[tool]);
  }

  // a text comment's words changed where they are (its size, color and fill too, from the options strip meanwhile)
  _editAnnotText(a) {
    const p = this.v.pages[a.page], fitted = a.fitted ?? ['Typewriter', 'Date'].includes(a.subject);
    this._inlineBox(p, [...a.rect], { value: a.contents || '', size: a.fontsize, color: a.textColor || '#000000', fill: a.fill || null, back: '#ffffff', // (back: its old words are under the box)
      grow: fitted, boxed: !fitted, kind: 'annot', annot: a,
      done: async (text, it) => {
        if (!text.trim()) { this._emptied(a); return; }
        const change = {};
        if (text !== (a.contents || '')) change.text = text;
        if (it.size !== a.fontsize) change.fontsize = it.size;
        if (it.color !== (a.textColor || '#000000')) change.textColor = it.color;
        if ((it.fill || null) !== (a.fill || null)) change.fill = it.fill || null;
        if (!Object.keys(change).length) return;
        const r = await this.run('annot_set', { page: a.page, id: a.id, ...change });
        if (!r) this._retype(it, text);
      } });
  }

  // a text comment left with no words is taken out (with none it would still be there, and invisible)
  async _emptied(a) {
    const r = await this.run('annot_delete', { page: a.page, ids: [a.id] });
    if (r) this._gone('Text deleted: it had no words left.');
  }

  // ------------------------------------------------------------------ selecting the page's own text
  async _selectSpan(page, a, b) {
    try {
      const r = await api.pdfSelect(this.doc.id, { page, ax: a[0], ay: a[1], bx: b[0], by: b[1] });
      if (!r.rects.length) return;
      this.v.selection = { page, ...r };
      this.v._showSelection();
    } catch { /* nothing there */ }
  }

  // Ctrl+A: every word on the page
  async _selectPage(page) {
    const w = await this._wordsFor(page);
    if (!w?.length) return;
    const mid = (r) => [r[0] + r[2] / 2, r[1] + r[3] / 2];
    await this._selectSpan(page, mid(w[0]), mid(w[w.length - 1]));
  }

  // a double-click on a word selects it
  _selectWord(e) {
    const box = e.target.closest?.('.pv-pagebox');
    if (!box) return;
    const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e);
    const w = (this.words[p.i] || []).find((r) => inRect(r, pt, this._px(p.i, 2)));
    if (w) this._selectSpan(p.i, [w[0] + w[2] / 2, w[1] + w[3] / 2], [w[0] + w[2] / 2, w[1] + w[3] / 2]);
  }

  // What can be done to the selected words, once: the bar by them and their right-click menu are both drawn from this
  // list. sep: a new group starts here. icon: its picture on the bar. Balloon is on: Copy only.
  _textActions(s) {
    const p = this.v.pages[s.page], mark = (kind, extra) => () => this._markSel(kind, extra);
    const copy = { label: 'Copy', icon: 'copy', kb: 'Ctrl+C', run: async () => { await copyText(s.text); toast('Copied.', 'ok', 1200); } };
    if (this.v.balloons?.on) return [copy];
    const top = this.v.state.turns !== 0 ? s.rects[0] : s.rects.reduce((a, b) => (b[1] < a[1] ? b : a));
    return [copy,
      { label: 'Highlight', icon: 'highlight', sep: true, run: mark('highlight') },
      { label: 'Highlighter color', dot: this.style.colors.highlight || HILITE[0], tip: 'The highlighter\'s color: click to change it', // (on the bar only)
        run: (b) => menu(b, [{ el: this._colorGrid(this.style.colors.highlight, (c) => { this._setStyle(null, 'highlight', { color: c }); this._textBar(); }, false, HILITE) }]) },
      { label: 'Underline', icon: 'underline', run: mark('underline') },
      { label: 'Strikethrough', icon: 'strikeout', run: mark('strikeout') },
      { label: 'Cross out', icon: 'strikeText', tip: 'Cross out: a single line through it', run: mark('strikeText') },
      { label: 'Squiggly underline', icon: 'squiggly', run: mark('squiggly') },
      { label: 'Highlight with a note…', icon: 'note', tip: 'Highlight with a note',
        run: () => this._popup(p, top, '', (text) => this._markSel('highlight', text.trim() ? { contents: text } : {}), 'Note on this text') },
      { label: 'Mark for redaction', icon: 'redactText', sep: true, run: mark('redact') },
      { label: 'Delete from the page', icon: 'trash', sep: true, kb: this.set === 'edit' ? 'Del' : '', tip: "Delete from the page: takes the words out of the page itself (Undo puts them back)", run: () => this.deleteText() },
    ];
  }

  // ...and to a comment: the bar that rides on the selected one shows those with a picture (after its quick colors),
  // its right-click menu shows them all
  _annotActions(s) {
    const a = s.a, p = this.v.pages[s.page], colorable = !['stamp', 'redact', 'file'].includes(a.kind);
    const key = a.kind === 'text' ? 'textColor' : 'color', now = (a.kind === 'text' ? a.textColor : a.color) || '';
    const words = () => this._popup(p, a.rect, a.contents, (text) => { if (text !== a.contents) this.run('annot_set', { page: a.page, id: a.id, contents: text }); }, this._label(a));
    // several selected (and this is one of them): what's done is done to them all
    const all = this.group.length && this._live(s) ? this._sels() : [s], many = all.length > 1, can = all.some((x) => canClone(x.a));
    const color = (c) => (many ? this._setStyle(a, null, { color: c }) : this.run('annot_set', { page: s.page, id: s.id, [key]: c }));
    const order = (label, to) => ({ label, action: () => this.run('annot_order', { page: s.page, ids: [s.id], to }) });
    return [
      many ? null : a.kind === 'text' ? { label: 'Edit text', icon: 'editText', tip: 'Edit the text (double-click)', run: () => this._editAnnotText(a) }
        : { label: a.contents ? 'Edit comment…' : 'Add a comment…', icon: 'note', tip: a.contents ? 'Edit the comment (double-click)' : 'Add a comment (double-click)', run: words },
      { label: 'Cut', kb: 'Ctrl+X', sep: true, off: !can, run: () => this._copy(all, true) },
      { label: 'Copy', kb: 'Ctrl+C', off: !can, run: () => this._copy(all) },
      { label: 'Duplicate', icon: 'copy', kb: 'Ctrl+D', tip: 'Duplicate (Ctrl+D)', off: !can, run: () => this._duplicate(all) },
      colorable || many ? { label: 'Color', sub: () => [{ el: this._colorGrid(many ? '' : now, color, false, !many && a.kind === 'highlight' ? HILITE : COLORS) }] } : null,
      // which lies over which, where comments overlap
      many ? null : { label: 'Arrange', sub: [order('Bring to front', 'front'), order('Bring forward', 'forward'), order('Send backward', 'backward'), order('Send to back', 'back')] },
      many ? null : { label: 'Show in the comments list', sep: true, run: () => { if (!this.showPanel) this.togglePanel(); this.select(this.sel); this.panel.querySelector('.pe-item.on')?.scrollIntoView({ block: 'nearest' }); } },
      { label: many ? `Delete ${all.length} comments` : 'Delete', icon: 'trash', kb: 'Del', tip: 'Delete (Del)', sep: true, run: () => this.deleteSel() },
    ].filter(Boolean);
  }

  // a list of actions as a menu's items...
  _menuOf(list) {
    return list.filter((x) => !x.dot).flatMap((x, i) => [x.sep && i ? { sep: true } : null, { label: x.label, kb: x.kb || undefined, disabled: !!x.off, sub: x.sub, action: x.run && (() => x.run()) }]).filter(Boolean);
  }

  // ...and as the buttons of a bar on the page (those with a picture that can act now)
  _barOf(list) {
    const out = [];
    for (const x of list) {
      if ((!x.icon && !x.dot) || x.off) continue;
      if (x.sep && out.length) out.push(h('span', { class: 'pe-bs' }));
      const title = x.tip || `${x.label}${x.kb ? ` (${x.kb})` : ''}`;
      const b = x.dot ? h('button', { class: 'pe-bd', style: { background: x.dot }, title }) // (a color to pick, shown as it is now)
        : h('button', { class: 'pe-bb', title, html: ICON[x.icon] });
      b.addEventListener('click', (ev) => { ev.stopPropagation(); x.run(b); });
      out.push(b);
    }
    return out;
  }

  // Right-click on the pages always opens a menu, and never changes the tool in hand: for the selected words, a
  // comment, a field's box (Forms), a picture (Edit), or the paper itself
  _context(e) {
    if (!this.editable) return;
    const box = e.target.closest?.('.pv-pagebox');
    if (!box || e.target.closest('.pe-field, .pe-inline')) return; // (a field being filled in keeps the system's own menu)
    e.preventDefault();
    const p = this.v.pages[+box.dataset.page], pt = this.v._pagePoint(p, e), at = { x: e.clientX, y: e.clientY };
    const s = this.v.selection;
    if (s?.page === p.i && s.rects.some((r) => inRect(r, pt, this._px(p.i, 3)))) { menu(null, this._menuOf(this._textActions(s)), { at }); return; }
    if (this.v.balloons?.on) return; // (Balloon is on: the comments and the page's tools are put away)
    const f = e.target.closest('.pe-fbox')?.field;
    if (f) {
      this.fsel = { page: f.page, id: f.id };
      this._drawFields();
      this._bar();
      menu(null, [{ label: 'Properties…', action: () => this._fieldProps(f) }, { sep: true }, { label: 'Delete field', kb: 'Del', action: () => this._fieldDelete() }], { at });
      return;
    }
    const a = this._hitAnnot(p.i, pt);
    if (a) { // (on one of several selected: the menu is for them all)
      if (!(this.group.length && this._live(a))) this.select(selOf(a));
      menu(null, this._menuOf(this._annotActions(this._live(a) || this.sel)), { at });
      return;
    }
    if (this.set === 'edit' || this.tool === 'editImage') this._pictureMenu(p, pt, at); else this._paperMenu(p, pt, at);
  }

  // right-click with the Edit tab open: on one of the page's own pictures, that picture's menu
  async _pictureMenu(p, pt, at) {
    const doc = this.doc;
    if (!this.images[p.i]) await this._loadImages(p.i);
    if (this.doc !== doc) return;
    const im = (this.images[p.i] || []).filter((x) => inRect(x.rect, pt)).sort((a, b) => a.rect[2] * a.rect[3] - b.rect[2] * b.rect[3])[0];
    if (!im) { this._paperMenu(p, pt, at); return; }
    this.select({ type: 'image', page: p.i, id: im.id, rect: im.rect });
    menu(null, [{ label: 'Delete picture', kb: 'Del', action: () => this.deleteSel() }], { at });
  }

  // right-click on bare paper
  _paperMenu(p, pt, at) {
    const v = this.v;
    menu(null, [
      { label: CLIP?.clips.length > 1 ? `Paste ${CLIP.clips.length} comments` : 'Paste comment', kb: 'Ctrl+V', disabled: !CLIP, action: () => this._paste(p.i, pt) },
      { label: 'Add sticky note here', action: () => this._noteAt(p, pt) },
      { sep: true },
      { label: 'Select all text on this page', kb: 'Ctrl+A', action: () => this._selectPage(p.i) },
      { sep: true },
      { label: 'Fit page', kb: 'Ctrl+0', check: v.state.fit === 'page', action: () => v.setFit('page') },
      { label: 'Fit width', kb: 'Ctrl+2', check: v.state.fit === 'width', action: () => v.setFit('width') },
      { label: 'Turn view', kb: 'R', action: () => v.turn() },
      { sep: true },
      { label: 'Find…', kb: 'Ctrl+F', action: () => v.findFocus() },
    ], { at });
  }

  // ------------------------------------------------------------------ selection, moving and sizing
  // a picture of the selected comment, to carry along when it's dragged
  _fetchImg(sel) {
    if (sel?.type !== 'annot' || !this.doc) return;
    const doc = this.doc;
    this._img(sel.page, sel.id).then((img) => {
      if (this.doc !== doc || !this._sels().includes(sel) || !img) return;
      sel.img = img;
      if (sel.box?.classList.contains('moving')) this._carry(sel.box, sel); // (already on the move: it joins in)
    });
  }

  // a comment's picture from the worker, asked for once until the next change (the selection asks, and so does
  // the pointer resting on a comment, so it's there by the time a drag starts)
  _img(page, id) {
    const all = this._imgs ||= new Map(), key = `${page}:${id}`;
    if (!all.has(key)) all.set(key, this._ask('annot_image', { page, id }).catch(() => null));
    return all.get(key);
  }

  // sel: what's selected now (null: nothing). also: more comments selected along with it
  select(sel, also = []) {
    this._flushNudge(); // (what the arrow keys moved is put down before the selection moves on)
    this.sel = sel;
    this.group = sel?.type === 'annot' ? also.filter((x) => x?.type === 'annot' && !same(sel)(x)) : [];
    for (const s of this._sels()) if (!s.img) this._fetchImg(s);
    if (sel && this.v.selection) { this.v.selection = null; this.v._showSelection(); }
    this._drawSel();
    this._bar();
    const all = this._sels();
    this.panel.querySelectorAll('.pe-item').forEach((n) => n.classList.toggle('on', all.some((s) => +n.dataset.id === s.id && +n.dataset.page === s.page)));
  }

  // What's selected, drawn over the pages: a box round each, and for one alone its bar and its handles
  _drawSel() {
    this.v.sheet.querySelectorAll('.pe-sel, .pe-h').forEach((n) => n.remove());
    const all = this._sels(), many = all.length > 1;
    if (all.length) this._setHover(null);
    for (const s of all) {
      s.box = null;
      const p = this.v.pages?.[s.page];
      if (!p) continue;
      const it = this.inline?.annot;
      if (it && s.type === 'annot' && it.id === s.id && it.page === s.page) continue; // (its words are being typed: nothing lies over the box typed in)
      const [x, y, w, hh] = s.rect, going = s.moved || s.held; // (on the move, or put down and not yet drawn there by the page)
      const thin = !many && s.type === 'annot' && s.a.kind === 'line' && !going; // a line shows its two ends, not a box (a box while it's on the move)
      const box = s.box = h('div', { class: `pe-sel${s.type === 'image' ? ' img' : ''}${thin ? ' thin' : ''}${many ? ' also' : ''}`, style: this.v._rectStyle(p, s.rect) });
      p.edit.append(box);
      if (going) this._carry(box, s);
      if (many) continue;
      if (s.type === 'annot') box.append(this._annotBar(s, p));
      // (no handles: a note's icon, text typed onto the page, which fits its words, and a mark that stays on its words)
      const fixed = s.type === 'annot' && (s.a.kind === 'note' || (s.a.kind === 'text' && s.a.fitted) || pinned(s.a));
      if (fixed || going) continue; // (nor while it's on the move: there's nothing to get hold of until it's put down)
      if (s.type === 'annot' && s.a.kind === 'line' && s.a.points?.length === 2) { // a line: a handle on each end
        s.a.points.forEach((q, i) => {
          const el = h('div', { class: 'pe-h pt', style: this.v._rectStyle(p, [q[0], q[1], 0, 0]) });
          el.dataset.pt = i;
          p.edit.append(el);
        });
        continue;
      }
      // Handles never get in the way of the thing itself, at any zoom: a side handle only where there's room for it
      // between the corners (30 pixels of the screen), and round something small (16 pixels) they stand off it, so a
      // press on it moves it. A stamp or a picture keeps its shape, so it has corners only
      const k = p.cssW / this.v._size(p)[0], sw = w * k, sh = hh * k, t = this.v.state.turns;
      const shaped = s.type === 'image' || s.a.kind === 'stamp';
      for (const mx of [-1, 0, 1]) {
        for (const my of [-1, 0, 1]) {
          if (!mx && !my) continue;
          if ((!mx || !my) && shaped) continue;
          if ((!my && sh < 30) || (!mx && sw < 30)) continue;
          const px = x + (mx + 1) / 2 * w, py = y + (my + 1) / 2 * hh;
          const el = h('div', { class: 'pe-h', style: this.v._rectStyle(p, [px, py, 0, 0]) });
          el.dataset.mx = mx;
          el.dataset.my = my;
          let off = [sw < 16 ? mx * 7 : 0, sh < 16 ? my * 7 : 0];
          for (let i = 0; i < t; i++) off = [-off[1], off[0]]; // (outward as the view is turned)
          if (off[0] || off[1]) { el.style.marginLeft = `${off[0] - 5}px`; el.style.marginTop = `${off[1] - 5}px`; }
          p.edit.append(el);
        }
      }
    }
  }

  // the bar that rides on a selected comment: quick colors (and a swatch that opens the rest), then its actions
  _annotBar(s, p) {
    const a = s.a, colorable = !['stamp', 'redact', 'file'].includes(a.kind), key = a.kind === 'text' ? 'textColor' : 'color';
    const now = (a.kind === 'text' ? a.textColor : a.color) || '';
    const set = (c) => this.run('annot_set', { page: s.page, id: s.id, [key]: c });
    const all = a.kind === 'highlight' ? HILITE : COLORS, quick = a.kind === 'highlight' ? HILITE.slice(0, 5) : QUICK;
    const more = h('button', { class: `pe-bd more${now && !quick.includes(now) ? ' on' : ''}`, text: '…', title: 'More colors' });
    more.addEventListener('click', (ev) => { ev.stopPropagation(); menu(more, [{ el: this._colorGrid(now, set, false, all) }]); });
    const kids = [
      ...(colorable ? [...quick.map((c) => h('button', { class: `pe-bd${c === now ? ' on' : ''}`, style: { background: c }, title: 'Color',
        onclick: (ev) => { ev.stopPropagation(); set(c); } })), more, h('span', { class: 'pe-bs' })] : []),
      ...this._barOf(this._annotActions(s)).filter((n) => !n.classList.contains('pe-bs')), // (one group here: the colors are the other)
    ];
    const turned = this.v.state.turns !== 0;
    const cls = `${!turned && s.rect[1] < 40 ? ' below' : ''}${!turned && s.rect[0] > p.info.w - 190 ? ' right' : ''}`;
    return h('div', { class: `pe-bar annot${cls}` }, h('div', { class: 'pe-bar-in' }, ...kids));
  }

  // the bar by selected text (with Select, or a tool that marks text): copy it, mark it up, note it, redact it
  _textBar() {
    this.v.sheet?.querySelectorAll('.pe-bar.text').forEach((n) => n.remove());
    const s = this.v.selection, tool = this.tool;
    if (!this.editable || this._selecting || !(tool === 'select' || TOOLS[tool]?.markup || tool === 'strikeText') || !s?.rects?.length) return;
    const p = this.v.pages?.[s.page];
    if (!p) return;
    // It rides on the sheet, not in the page (a page cuts off whatever hangs over its edge): just above the topmost
    // selected line as the view shows it (turned or not), under the lowest one when there's no room above, and slid
    // sideways to stay whole inside what's in sight
    const kids = this._barOf(this._textActions(s)), bar = h('div', { class: 'pe-bar text' }, h('div', { class: 'pe-bar-in' }, ...kids));
    this.v.sheet.append(bar);
    const boxes = s.rects.map((r) => this._screen(p, r)), top = boxes.reduce((a, b) => (b.top < a.top ? b : a)), low = Math.max(...boxes.map((b) => b.bottom));
    const sheet = this.v.sheet.getBoundingClientRect(), sc = this.v.scroller.getBoundingClientRect();
    const w = bar.offsetWidth || kids.reduce((t, n) => t + (n.classList.contains('pe-bs') ? 9 : 28), 10), hh = bar.offsetHeight || 34;
    const right = sc.left + (this.v.scroller.clientWidth || sc.width), bottom = sc.top + (this.v.scroller.clientHeight || sc.height);
    let y = top.top - hh - 8;
    if (y < sc.top + 4) { y = low + 8; if (y + hh > bottom - 4) y = sc.top + 4; } // (the selection fills the view: at its top)
    const x = clamp(top.left, sc.left + 4, Math.max(sc.left + 4, right - w - 4));
    bar.style.left = `${Math.max(0, x - sheet.left)}px`;
    bar.style.top = `${Math.max(0, y - sheet.top)}px`;
  }

  // drag one end of a line
  _pointDrag(e, i) {
    const s = this.sel, p = this.v.pages[s.page], pts = s.a.points.map((q) => [...q]), svg = this._ghost(p);
    const look = { color: s.a.color || '#e02020', width: s.a.width, opacity: s.a.opacity };
    this._drag(e, p, this.v._pagePoint(p, e), (a, b, m) => {
      pts[i] = this._constrain(p, 'line', pts[1 - i], onPagePt(p, b), m?.shiftKey);
      this._ghostShape(svg, p, s.a.arrow ? 'arrow' : 'line', pts[0], pts[1], look);
    }, async (a, b, moved) => {
      if (moved) {
        const res = await this.run('annot_set', { page: s.page, id: s.id, points: pts });
        const n = res?.result;
        if (n && this.sel === s) this.select(selOf({ ...n, page: s.page })); // (the selection follows by itself: only if it hasn't)
      }
      svg.remove();
    }, () => svg.remove());
  }

  // while a comment is dragged its picture goes along, so it's plain where it will land
  // (called at every step: the picture may only arrive once the drag is on, and in a turned view it's fitted to the
  // box again as that changes. A line, which shows no box while it lies still, shows one now)
  _carry(box, s = this.sel) {
    if (!box || !s) return;
    box.classList.add('moving');
    box.classList.remove('thin');
    let img = box.querySelector('.pe-carry');
    if (!img && s.img) { img = h('img', { class: 'pe-carry', src: s.img }); box.prepend(img); }
    const t = this.v.state.turns, [, , w, hh] = s.rect;
    if (!img || !t) return;
    // the view is turned: the picture is turned with it (a quarter turn: the box is as wide as the picture is tall)
    if (t % 2 && w > 0 && hh > 0) Object.assign(img.style, { inset: 'auto', left: '50%', top: '50%', width: `${w / hh * 100}%`, height: `${hh / w * 100}%`, transform: `translate(-50%, -50%) rotate(${t * 90}deg)` });
    else img.style.transform = `rotate(${t * 90}deg)`;
  }

  // What's selected is dragged: all of it together (but for marks, which stay on their words), none of it off its
  // page. Shift keeps it level or upright with where it was. tap: called on a click with no drag
  _moveDrag(e, p, from, tap = null) {
    this._flushNudge();
    const set = this._sels().filter((s) => !(s.type === 'annot' && pinned(s.a)) && this.v.pages?.[s.page])
      .map((s) => ({ type: s.type, page: s.page, id: s.id, r0: [...s.rect], was: !!s.moved }));
    const shift = (a, b, m) => {
      let dx = b[0] - a[0], dy = b[1] - a[1];
      if (m?.shiftKey) { if (Math.abs(dx) >= Math.abs(dy)) dy = 0; else dx = 0; }
      return this._roomFor(set.map((x) => x.r0), set.map((x) => x.page), dx, dy);
    };
    // (each is looked up again at every step: an answer from the worker meanwhile makes new records of the selection)
    const put = ([dx, dy]) => set.map((x) => {
      const s = this._live(x);
      if (s) { s.rect = [x.r0[0] + dx, x.r0[1] + dy, x.r0[2], x.r0[3]]; s.moved = true; }
      return s;
    });
    this._drag(e, p, from, (a, b, m) => {
      for (const s of put(shift(a, b, m))) {
        if (!s?.box) continue;
        this._carry(s.box, s);
        s.box.style.cssText = this.v._rectStyle(this.v.pages[s.page], s.rect);
      }
      this.v.sheet.querySelectorAll('.pe-h').forEach((n) => n.remove());
    }, (a, b, moved, u) => {
      if (!moved) { tap?.(); return; }
      const live = put(shift(a, b, u));
      this._commit(live.filter(Boolean), set.filter((x, i) => live[i]).map((x) => x.r0));
    }, () => { // (put back where it was)
      for (const x of set) { const s = this._live(x); if (s) { s.rect = x.r0; s.moved = x.was; } }
      this._drawSel();
    });
  }

  // how far several rectangles can go together (dx, dy) with each staying on its own page
  _roomFor(rects, pages, dx, dy) {
    rects.forEach((r, i) => {
      const p = this.v.pages?.[pages[i]];
      if (!p) return;
      dx = clamp(dx, Math.min(0, -r[0]), Math.max(0, p.info.w - r[0] - r[2]));
      dy = clamp(dy, Math.min(0, -r[1]), Math.max(0, p.info.h - r[1] - r[3]));
    });
    return [dx, dy];
  }

  // a rectangle moved back onto its page (as shown, unturned by the view), so nothing is dragged out of sight
  _onPage(p, r) {
    const W = p.info.w, H = p.info.h;
    return [clamp(r[0], 0, Math.max(0, W - r[2])), clamp(r[1], 0, Math.max(0, H - r[3])), r[2], r[3]];
  }

  // A handle is dragged. A stamp or a picture keeps its shape; with Shift so does anything dragged by a corner (a
  // rectangle or an oval becomes a square or a circle). The side opposite stays put, and it stops at the page's edge
  _sizeDrag(e, mx, my) {
    const s0 = this.sel, p = this.v.pages[s0.page], r0 = [...s0.rect], was = !!s0.moved, kind = s0.a?.kind;
    const from = this.v._pagePoint(p, e);
    const keepShape = s0.type === 'image' || kind === 'stamp';
    const calc = (b, shift) => {
      let x0 = r0[0], y0 = r0[1], x1 = r0[0] + r0[2], y1 = r0[1] + r0[3];
      if (mx < 0) x0 = b[0]; if (mx > 0) x1 = b[0];
      if (my < 0) y0 = b[1]; if (my > 0) y1 = b[1];
      x0 = clamp(x0, 0, p.info.w); x1 = clamp(x1, 0, p.info.w); y0 = clamp(y0, 0, p.info.h); y1 = clamp(y1, 0, p.info.h);
      let r = rectOf([x0, y0], [x1, y1]);
      const asp = !(mx && my && r0[2] && r0[3]) ? 0 : keepShape ? r0[2] / r0[3] : !shift ? 0 : kind === 'rect' || kind === 'ellipse' ? 1 : r0[2] / r0[3];
      if (asp) { // a corner that keeps a shape (its width over its height)
        const ax = mx < 0 ? r0[0] + r0[2] : r0[0], ay = my < 0 ? r0[1] + r0[3] : r0[1];
        const w = Math.min(Math.max(r[2], r[3] * asp), mx < 0 ? ax : p.info.w - ax, (my < 0 ? ay : p.info.h - ay) * asp), hh = w / asp;
        r = [mx < 0 ? ax - w : ax, my < 0 ? ay - hh : ay, w, hh];
      }
      // never too small to get hold of again; a text box never narrower than a couple of letters, or shorter than a line
      const fs = kind === 'text' ? s0.a.fontsize || 12 : 0, least = fs ? [Math.max(2 * fs, 24), fs * 1.3] : [2, 2];
      const w = Math.max(r[2], Math.min(least[0], p.info.w)), hh = Math.max(r[3], Math.min(least[1], p.info.h));
      // (the side opposite the handle stays put)
      return this._onPage(p, [w > r[2] && mx < 0 ? r0[0] + r0[2] - w : r[0], hh > r[3] && my < 0 ? r0[1] + r0[3] - hh : r[1], w, hh]);
    };
    this._drag(e, p, from, (a, b, m) => {
      const s = this._live(s0); // (looked up again at every step: the worker's answers make new records)
      if (!s) return;
      s.rect = calc(b, m?.shiftKey);
      s.moved = true;
      if (s.box) { this._carry(s.box, s); s.box.style.cssText = this.v._rectStyle(p, s.rect); }
      p.edit.querySelectorAll('.pe-h').forEach((n) => n.remove());
    }, (a, b, moved, u) => {
      const s = this._live(s0);
      if (!s) return;
      if (!moved) { this._drawSel(); return; }
      s.rect = calc(b, u?.shiftKey);
      this._commit([s], [r0]);
    }, () => {
      const s = this._live(s0);
      if (s) { s.rect = r0; s.moved = was; }
      this._drawSel();
    });
  }

  // What was moved or sized goes to the worker (items: records of the selection, already at their new places; r0s:
  // where each was): several at once are one step to undo. Until the page is drawn again each keeps its picture
  // where it was put, so nothing jumps back; if the worker can't do it, each goes back where it was
  async _commit(items, r0s) {
    if (!items.length) return;
    for (const s of items) { s.moved = false; s.held = 'sent'; } // (held: 'sent' until the worker answers, then 'drawn' until the page shows it)
    this._drawSel();
    const one = items[0], keys = items.map((s) => ({ type: s.type, page: s.page, id: s.id }));
    const back = () => {
      keys.forEach((x, i) => { const s = this._live(x); if (s?.held) { s.rect = r0s[i]; s.held = false; } });
      this._drawSel();
    };
    if (one.type === 'image') {
      const res = await this.run('image_set', { page: one.page, id: one.id, rect: one.rect });
      if (!res) { back(); return; }
      if (!this.sel || this.sel === one) this._reselectImage(one.page, one.rect); // (it comes back as a new picture: found by its place)
      return;
    }
    const res = items.length === 1 ? await this.run('annot_set', { page: one.page, id: one.id, rect: one.rect })
      : await this.run('annot_set_many', { items: items.map((s) => ({ page: s.page, id: s.id, rect: s.rect })) });
    if (!res) { back(); return; }
    const a = items.length === 1 ? res.result : null;
    if (a && this.sel === one) this.select(selOf({ ...a, page: one.page })); // (the selection follows its comment by itself: only if it hasn't)
    for (const x of keys) {
      const s = this._live(x);
      if (!s?.held) continue;
      s.held = 'drawn';
      if (!s.moved) s.rect = s.a.rect; // (nudged again meanwhile: that move stays, and goes in next) (where the worker put it: a text box may be wider, a stamp keeps its shape)
    }
    this._drawSel();
    // the picture stays over each until the page has drawn it there itself
    const t0 = performance.now();
    const wait = () => {
      const held = this._sels().filter((s) => s.held === 'drawn');
      if (!held.length) return;
      const dt = performance.now() - t0, drawn = !this.v.queue?.length && !this.v.busy;
      if (!(drawn && dt > 150) && dt < 2500) { setTimeout(wait, 80); return; }
      for (const s of held) {
        s.held = false;
        if (s.type === 'annot' && !s.moved) s.rect = s.a.rect;
        s.img = null; // (asked for again: it may look different now)
        this._fetchImg(s);
      }
      this._drawSel();
    };
    setTimeout(wait, 80);
  }

  // What the arrow keys moved goes to the worker: once they've rested a moment, and before anything else is done
  // (another selection, a tool, an undo, a save), so a nudge is never lost
  _flushNudge() {
    const n = this._nudge;
    if (!n) return;
    this._nudge = null;
    clearTimeout(n.timer);
    const went = n.items.filter(({ s, r0 }) => s.rect[0] !== r0[0] || s.rect[1] !== r0[1]);
    for (const { s } of n.items) s.moved = false;
    if (went.length) this._commit(went.map((x) => x.s), went.map((x) => x.r0)); else this._drawSel();
  }

  // ...or is dropped, each back where it was (what was nudged is being deleted)
  _dropNudge() {
    const n = this._nudge;
    if (!n) return;
    this._nudge = null;
    clearTimeout(n.timer);
    for (const { s, r0 } of n.items) { s.rect = r0; s.moved = false; }
  }

  // The document is being left (put aside for another, or closed) with a nudge still waiting: it goes straight to
  // its worker, which is still there when it's only put aside
  _nudgeLeave() {
    const n = this._nudge, doc = this.doc;
    if (!n) return;
    this._nudge = null;
    clearTimeout(n.timer);
    if (!doc) return;
    const went = n.items.filter(({ s, r0 }) => s.rect[0] !== r0[0] || s.rect[1] !== r0[1]).map((x) => x.s);
    const notes = went.filter((s) => s.type === 'annot').map((s) => ({ page: s.page, id: s.id, rect: s.rect }));
    if (notes.length) api.pdfEdit(doc.id, 'annot_set_many', { items: notes }).catch(() => {});
    for (const s of went) if (s.type === 'image') api.pdfEdit(doc.id, 'image_set', { page: s.page, id: s.id, rect: s.rect }).catch(() => {});
  }

  // the selected words taken out of the page itself (not a comment): Ctrl+Z puts them back
  async deleteText() {
    const s = this.v.selection;
    if (!s?.rects?.length || !this.editable) return;
    this.v.selection = null;
    this.v._showSelection();
    const r = await this.run('text_delete', { page: s.page, rects: s.rects }, 'Deleting…');
    if (r) this._gone('Deleted from the page.');
  }

  // everything selected is taken out: several comments in one step to undo
  async deleteSel() {
    const all = this._sels(), s = all[0];
    if (!s) return;
    this._dropNudge(); // (no use moving what's being deleted)
    this.select(null);
    if (s.type === 'image') {
      if (await this.run('image_delete', { page: s.page, id: s.id })) this._gone('Picture deleted.');
      return;
    }
    const by = new Map();
    for (const x of all) by.set(x.page, [...(by.get(x.page) || []), x.id]);
    const r = all.length === 1 ? await this.run('annot_delete', { page: s.page, ids: [s.id] })
      : await this.run('annot_delete_many', { items: [...by].map(([page, ids]) => ({ page, ids })) });
    if (r) this._gone(all.length === 1 ? `${this._label(s.a)} deleted.` : `${all.length} comments deleted.`);
  }

  // a comment taken out from the comments list
  async _deleteAnnot(a) {
    const r = await this.run('annot_delete', { page: a.page, ids: [a.id] });
    if (r) this._gone(a.replyTo ? 'Reply deleted.' : `${this._label(a)} deleted.`);
  }

  // ------------------------------------------------------------------ the pages' own text and pictures
  async _editTextAt(p, pt) {
    const doc = this.doc;
    await doc?._peQ; // (the edit just finished, queued by _endInline a moment ago, lands first: the line is read as it is now)
    if (this.doc !== doc || this.tool !== 'editText' || this.v.pages?.[p.i] !== p) return;
    let line;
    try { line = await this._ask('text_at', { page: p.i, at: pt }, doc); } catch (e) { toast(e.message, 'error'); return; }
    if (!line) { toast('There\'s no text there to edit. (A scanned page is a picture: use Add page text and a white box instead.)', 'info'); return; }
    if (this.doc !== doc || this.tool !== 'editText' || this.v.pages?.[p.i] !== p) return; // (another tool was picked while the worker looked)
    // a line of several looks (a bold label, then a value): only the run clicked is changed, so the rest keep theirs
    const run = line.mixed ? line.spans?.[line.span] : null, src = run ? { ...line, ...run } : line;
    const family = src.mono ? 'Courier New, monospace' : src.serif ? 'Times New Roman, serif' : 'Helvetica, Arial, sans-serif';
    const font = `${src.italic ? 'italic ' : ''}${src.bold ? 'bold ' : ''}${src.size}px ${family}`;
    this._inlineBox(p, src.rect, { value: src.text, size: src.size, color: src.color || '#000000', font, back: '#ffffff', kind: 'line', enter: 'done', // (one line)
      dir: line.dirShown || line.dir, // which way it runs as the page is shown: the box lies along it
      done: async (text, it) => {
        if (text === src.text && it.size === src.size && it.color === (src.color || '#000000')) return;
        // origin and dir as the worker gave them: the words go back on their own line, at their own angle
        const r = await this.run('text_replace', { page: p.i, rect: src.rect, text, origin: src.origin, dir: line.dir, size: it.size, color: it.color,
          bold: src.bold, italic: src.italic, serif: src.serif, mono: src.mono });
        if (!r) this._retype(it, text);
      } });
  }

  async _loadImages(page) {
    if (!this.editable) return;
    const pages = page == null ? this.v._visible().map((p) => p.i) : [page];
    for (const i of pages) {
      if (this.images[i]) continue;
      try { this.images[i] = await this._ask('images', { page: i }); } catch { this.images[i] = []; }
    }
  }

  async _imageDown(e, p, pt) {
    let up = false; // (the button may come up while the worker is asked for the page's pictures: then it was a click)
    const let_go = () => { up = true; };
    if (!this.images[p.i]) {
      window.addEventListener('pointerup', let_go);
      window.addEventListener('pointercancel', let_go);
      await this._loadImages(p.i);
      window.removeEventListener('pointerup', let_go);
      window.removeEventListener('pointercancel', let_go);
      if (this.tool !== 'editImage' || this.v.pages?.[p.i] !== p) return;
    }
    const hits = (this.images[p.i] || []).filter((im) => inRect(im.rect, pt)).sort((a, b) => a.rect[2] * a.rect[3] - b.rect[2] * b.rect[3]);
    if (!hits.length) { this.select(null); return; }
    const im = hits[0];
    if (this.sel?.type !== 'image' || this.sel.id !== im.id || this.sel.page !== p.i) this.select({ type: 'image', page: p.i, id: im.id, rect: im.rect });
    if (!up) this._moveDrag(e, p, pt);
  }

  async _reselectImage(page, r) {
    await this._loadImages(page);
    const near = (this.images[page] || []).find((im) => Math.abs(im.rect[0] - r[0]) < 2 && Math.abs(im.rect[1] - r[1]) < 2);
    this.select(near ? { type: 'image', page, id: near.id, rect: near.rect } : null);
  }

  // ------------------------------------------------------------------ form fields
  _drawFields() {
    const live = new Set(), design = this.set === 'form';
    for (const f of this.fields) {
      const p = this.v.pages?.[f.page];
      if (!p || (!design && !['text', 'checkbox', 'radio', 'combo', 'list'].includes(f.kind))) continue;
      const key = `${design ? 'd' : 'f'}:${f.page}:${f.id}`;
      live.add(key);
      let el = this.fieldEls.get(key);
      if (!el) {
        el = design ? this._fieldBox(f) : this._fieldEl(f);
        this.fieldEls.set(key, el);
      }
      if (el.parentNode !== p.edit) p.edit.append(el);
      el.style.cssText = this.v._rectStyle(p, f.rect);
      if (design) { // a box to arrange: named, and marked when it's the one selected
        el.field = f;
        el.firstChild.textContent = f.name;
        el.title = `${f.name}\nDrag to move, the corner to size, double-click for its properties`;
        el.dataset.kind = f.kind;
        el.classList.toggle('on', this.fsel?.page === f.page && this.fsel?.id === f.id);
        continue;
      }
      const k = p.cssW / this.v._size(p)[0];
      if (f.kind === 'text' || f.kind === 'combo' || f.kind === 'list') el.style.fontSize = `${(f.fontsize || Math.min(f.rect[3] * 0.7, 12)) * k}px`;
      // never under someone typing (a tick box or a list has nothing half typed: it follows an undo even with the keyboard on it)
      if ((document.activeElement !== el || el.type === 'checkbox' || el.tagName === 'SELECT') && !el.timer) {
        if (el.type === 'checkbox') el.checked = !!f.value && f.value !== 'Off';
        else el.value = f.value ?? '';
        el.sent = el.type === 'checkbox' ? el.checked : el.value;
      }
      el.field = f;
    }
    for (const [key, el] of this.fieldEls) if (!live.has(key)) { el.remove(); this.fieldEls.delete(key); }
  }

  _fieldEl(f) {
    let el;
    if (f.kind === 'checkbox' || f.kind === 'radio') el = h('input', { type: 'checkbox', class: `pe-field check${f.kind === 'radio' ? ' radio' : ''}` });
    else if (f.kind === 'combo' || f.kind === 'list') {
      el = h('select', { class: 'pe-field' }, ...['', ...f.options.map((o) => (Array.isArray(o) ? o[0] : o))].map((o) => h('option', { value: o, text: o })));
    } else el = f.multiline ? h('textarea', { class: 'pe-field' }) : h('input', { class: 'pe-field', type: 'text', spellcheck: 'false' });
    el.title = `${f.label || f.name}${f.required ? ' (required)' : ''}`;
    if (f.readonly) el.disabled = true;
    if (f.maxlen) el.maxLength = f.maxlen;
    el.addEventListener('keydown', (e) => e.stopPropagation());
    // typed words reach the PDF a moment after typing stops (and when the field is left, or before a save), so
    // nothing typed is lost to a save or a close, and the tab shows the change at once
    const doc = this.doc;
    el.commit = () => {
      clearTimeout(el.timer);
      el.timer = null;
      if (this.doc !== doc) return; // (its document was left, and what was typed went in then: see close. Never into another document)
      const field = el.field, value = el.type === 'checkbox' ? el.checked : el.value;
      if (el.sent === value) { this._calm(); return; }
      el.sent = value;
      this.run('field_set', { page: field.page, id: field.id, value });
    };
    el.addEventListener('change', () => el.commit());
    if (el.type !== 'checkbox' && el.tagName !== 'SELECT') {
      el.addEventListener('input', () => {
        if (!this.doc.pdfDirty) { this.doc.pdfDirty = true; this.v.app?.shell?.renderDocTabs(); this._syncFile(); }
        clearTimeout(el.timer);
        el.timer = setTimeout(() => el.commit(), 700);
      });
    }
    el.sent = f.kind === 'checkbox' || f.kind === 'radio' ? !!f.value && f.value !== 'Off' : f.value ?? '';
    return el;
  }

  // ------------------------------------------------------------------ making a form (the Forms tab)
  _fselField() { return this.fsel ? this.fields.find((f) => f.page === this.fsel.page && f.id === this.fsel.id) : null; }

  _fieldBox() {
    const el = h('div', { class: 'pe-fbox' }, h('span', { class: 'pe-fname' }), h('i', { class: 'pe-fh' }));
    el.addEventListener('pointerdown', (e) => this._fieldDown(e, el));
    el.addEventListener('dblclick', (e) => { e.stopPropagation(); this._fieldProps(el.field); });
    return el;
  }

  // a field's box is pressed: it's selected, and a drag moves it (its corner sizes it)
  _fieldDown(e, el) {
    if (e.button !== 0 || this.space) return; // (Space held: the press pans the pages, see down)
    e.preventDefault();
    const f = el.field, p = this.v.pages[f.page], sizing = e.target.classList.contains('pe-fh'), r0 = [...f.rect];
    let r = r0;
    const had = !!this.fsel;
    this.fsel = { page: f.page, id: f.id };
    this._drawFields();
    if (!had) this._bar(); // (Field properties and Delete field come on)
    this._drag(e, p, this.v._pagePoint(p, e), (a, b) => {
      const dx = b[0] - a[0], dy = b[1] - a[1];
      r = sizing ? [r0[0], r0[1], Math.max(r0[2] + dx, 6), Math.max(r0[3] + dy, 6)] : this._onPage(p, [r0[0] + dx, r0[1] + dy, r0[2], r0[3]]);
      el.style.cssText = this.v._rectStyle(p, r);
    }, (a, b, moved) => { if (moved) this.run('field_edit', { page: f.page, id: f.id, rect: r }); },
    () => { el.style.cssText = this.v._rectStyle(p, r0); });
  }

  // a new field is dragged out (a click makes one of a usual size)
  _fieldDrag(e, p, from, over = null) {
    const tool = this.tool, [kind, w, hh] = FIELD_TOOLS[tool], svg = this._ghost(p);
    this._drag(e, p, from, (a, b) => this._ghostShape(svg, p, 'crop', a, b), async (a, b, moved) => {
      svg.remove();
      if (!moved && over) { this._take(over); return; }
      let r = rectOf(a, b);
      const least = this._px(p.i, 5); // (a few pixels of the screen, at any zoom)
      if (!moved || r[2] < least || r[3] < least) r = [a[0], a[1] - hh / 2, w, hh];
      if (kind === 'checkbox') { const s = Math.min(r[2], r[3]); r = [r[0], r[1], s, s]; }
      const keepOn = this._staysOn(tool), seq = this._toolSeq, doc = this.doc;
      const res = await this.run('field_add', { page: p.i, kind, rect: this._onPage(p, r), multiline: tool === 'fMulti' });
      if (!res?.result?.id || this.doc !== doc || this.tool !== tool || this._toolSeq !== seq || this.set !== 'form') return; // (another pick meanwhile stays)
      this.fsel = { page: p.i, id: res.result.id };
      this.setTool(keepOn ? tool : 'select');
    }, () => svg.remove(), { onPage: true });
  }

  _formAuto(b) {
    const go = async (pages) => {
      const r = await this.run('form_auto', pages ? { pages } : {}, 'Looking for the blanks…');
      if (!r) return;
      const n = r.result?.count || 0;
      toast(n ? `${n} field${n === 1 ? '' : 's'} added. Drag one to move it, its corner to size it, double-click to name it, Delete to remove it. Fill & Sign tries them out.`
        : 'No blanks found here. Draw the fields with the tools beside this one.', 'info', 8000);
    };
    if (this.v.pages.length < 2) { go(null); return; }
    menu(b, [{ label: 'On this page', action: () => go([this.v.current || 0]) }, { label: `On all ${this.v.pages.length} pages`, action: () => go(null) }]);
  }

  async _formClear() {
    if (!this.fields.length) { toast('There are no fields to remove.', 'info'); return; }
    if (!await this._confirm('Remove all fields', `Take all ${this.fields.length} fields out of the document, with whatever is filled into them?`, 'Remove')) return;
    this.fsel = null;
    if (await this.run('field_delete', {})) this._gone('All the fields were removed.');
  }

  async _fieldDelete() {
    const f = this._fselField();
    if (!f) return;
    this.fsel = null;
    if (await this.run('field_delete', { page: f.page, ids: [f.id] })) this._gone(`Field "${f.name}" deleted.`);
  }

  _fieldProps(f) {
    const row = (label, el) => h('label', { class: 'pe-frow' }, h('span', { text: label }), el);
    const tick = (el, label) => h('label', { class: 'pe-ftick' }, el, label);
    const name = h('input', { type: 'text', value: f.name, spellcheck: 'false' });
    const tip = h('input', { type: 'text', value: f.label && f.label !== f.name ? f.label : '', placeholder: 'Shown when the pointer is on the field' });
    const req = h('input', { type: 'checkbox', checked: f.required }), ro = h('input', { type: 'checkbox', checked: f.readonly });
    const texty = !['checkbox', 'radio', 'signature', 'button'].includes(f.kind);
    const multi = f.kind === 'text' ? h('input', { type: 'checkbox', checked: f.multiline }) : null;
    const size = texty ? h('select', {}, ...[0, 8, 9, 10, 11, 12, 14, 18].map((x) => h('option', { value: x, text: x ? `${x} pt` : 'Fit to the field', selected: Math.round(f.fontsize) === x }))) : null;
    const opts = ['combo', 'list'].includes(f.kind) ? h('textarea', { rows: 5, spellcheck: 'false' }) : null;
    if (opts) opts.value = f.options.map((o) => (Array.isArray(o) ? o[0] : o)).join('\n');
    let d = null;
    const ok = () => {
      d.close();
      const change = { page: f.page, id: f.id, name: name.value.trim() || f.name, label: tip.value.trim(), required: req.checked, readonly: ro.checked };
      if (multi) change.multiline = multi.checked;
      if (size) change.fontsize = +size.value;
      if (opts) change.options = opts.value.split('\n').map((x) => x.trim()).filter(Boolean);
      this.run('field_edit', change);
    };
    d = modal('Field Properties', h('div', { class: 'pe-fprops' },
      row('Name', name), row('Tip', tip), size && row('Text size', size), opts && row('Choices, one to a line', opts),
      h('div', { class: 'pe-fticks' }, tick(req, 'Required'), tick(ro, 'Read-only'), multi && tick(multi, 'Several lines')),
      h('div', { class: 'pe-pop-foot' },
        h('button', { class: 'btn', text: 'Delete field', onclick: () => { d.close(); this.fsel = { page: f.page, id: f.id }; this._fieldDelete(); } }),
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn', text: 'Cancel', onclick: () => d.close() }),
        h('button', { class: 'btn primary', text: 'OK', onclick: ok }))), { width: 420 });
    for (const el of [name, tip]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); });
    setTimeout(() => { name.focus(); name.select(); }, 30);
  }

  // ------------------------------------------------------------------ stamps and signatures
  _stampMenu(b) {
    const items = Object.entries(STAMP_LABEL).map(([id, label]) => ({ label, action: () => this.setTool('stamp', { stamp: id }) }));
    items.push({ sep: true }, { label: 'Picture as a stamp…', action: async () => {
      const r = await api.openFiles('image', 'Choose a picture to stamp with').catch(() => null);
      if (r?.files?.length) this.setTool('stamp', { image: r.files[0].data, aspect: await this._aspect(r.files[0].data) });
    } });
    menu(b, items);
  }

  _aspect(data) {
    return new Promise((res) => { const im = new Image(); im.onload = () => res(im.width / Math.max(im.height, 1)); im.onerror = () => res(3); im.src = data; });
  }

  _signMenu(b, kind) {
    const pref = kind === 'sign' ? 'pdfSignature' : 'pdfInitials', saved = this.v.app?.prefs?.[pref];
    const what = kind === 'sign' ? 'signature' : 'initials';
    const items = [];
    if (saved) items.push({ label: `Place my ${what}`, action: async () => this.setTool(kind, { image: saved, aspect: await this._aspect(saved) }) });
    items.push({ label: saved ? `Change my ${what}…` : `Add my ${what}…`, action: () => this._signDialog(kind) });
    if (saved) items.push({ sep: true }, { label: `Forget my ${what}`, action: () => this.v.app?.save({ [pref]: null }) });
    menu(b, items);
  }

  // draw or type a signature once; it's kept (on this computer only) to place again
  _signDialog(kind) {
    const pref = kind === 'sign' ? 'pdfSignature' : 'pdfInitials', what = kind === 'sign' ? 'signature' : 'initials';
    const c = h('canvas', { class: 'pe-pad', width: 920, height: 300, tabindex: 0 });
    const g = c.getContext('2d'), INK = '#0b1f5c', PEN = 5;
    // What's on the pad: the words typed (if any), then each stroke drawn, kept as its points. A stroke is drawn a
    // piece at a time while the pen moves (never the whole of it over again, which hardens and darkens its start),
    // and the pad is drawn afresh from the list when it ends, or when the last one is taken back (Ctrl+Z).
    let strokes = [], words = '';
    const paint = () => {
      g.clearRect(0, 0, c.width, c.height);
      g.lineWidth = PEN; g.lineCap = 'round'; g.lineJoin = 'round'; g.strokeStyle = g.fillStyle = INK;
      if (words) {
        let size = 150;
        do { g.font = `${size}px "Segoe Script", "Brush Script MT", cursive`; size -= 6; } while (g.measureText(words).width > c.width - 40 && size > 20);
        g.textBaseline = 'middle';
        g.fillText(words, 20, c.height / 2);
      }
      for (const st of strokes) {
        g.beginPath();
        if (st.length === 1) { g.arc(st[0][0], st[0][1], PEN / 2, 0, 2 * Math.PI); g.fill(); continue; } // a tap: a dot (on an i, a full stop)
        g.moveTo(st[0][0], st[0][1]);
        for (let q = 1; q < st.length; q++) g.lineTo(st[q][0], st[q][1]);
        g.stroke();
      }
      if (back) back.disabled = !strokes.length;
    };
    let back = null;
    const clear = () => { strokes = []; words = ''; paint(); };
    const undo = () => { if (strokes.length) { strokes.pop(); paint(); } };
    c.addEventListener('pointerdown', (e) => {
      if (e.button > 0) return;
      e.preventDefault();
      c.focus({ preventScroll: true });
      try { c.setPointerCapture(e.pointerId); } catch { /* not a pointer that can be held */ }
      const r = c.getBoundingClientRect(), k = c.width / r.width, id = e.pointerId;
      const at = (m) => [(m.clientX - r.left) * k, (m.clientY - r.top) * k];
      const st = [at(e)];
      strokes.push(st);
      paint();
      const mv = (m) => {
        if (m.pointerId !== id) return;
        const between = m.getCoalescedEvents?.() || []; // (every sample of the pen, not one a move: quick loops stay round)
        for (const q of (between.length ? between : [m]).map(at)) {
          const l = st[st.length - 1];
          if (Math.hypot(q[0] - l[0], q[1] - l[1]) < 1.5) continue;
          g.beginPath();
          g.moveTo(l[0], l[1]);
          g.lineTo(q[0], q[1]);
          g.stroke();
          st.push(q);
        }
      };
      const up = (u) => { // (lifted, or taken away by the system: a pen out of range, a touch it took over)
        if (u.pointerId !== id) return;
        c.removeEventListener('pointermove', mv);
        c.removeEventListener('pointerup', up);
        c.removeEventListener('pointercancel', up);
        if (strokes.includes(st)) paint();
      };
      c.addEventListener('pointermove', mv);
      c.addEventListener('pointerup', up);
      c.addEventListener('pointercancel', up);
    });
    c.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); e.stopPropagation(); undo(); }
    });
    const typed = h('input', { class: 'pe-type', placeholder: `Or type your ${what}`, spellcheck: 'false' });
    typed.addEventListener('input', () => { // typed instead: it takes the place of whatever was drawn
      strokes = [];
      words = typed.value.trim() ? typed.value : '';
      paint();
    });
    typed.addEventListener('keydown', (e) => e.stopPropagation());
    const d = modal(kind === 'sign' ? 'Your signature' : 'Your initials', h('div', { class: 'pe-sign' },
      h('p', { class: 'pv-of', text: `Draw your ${what} with the mouse or a pen, or type it. It's kept on this computer to place again.` }),
      c, typed,
      h('div', { class: 'pe-pop-foot' },
        (back = h('button', { class: 'btn', text: 'Undo stroke', title: 'Take back the last stroke (Ctrl+Z)', disabled: true, onclick: undo })),
        h('button', { class: 'btn', text: 'Clear', onclick: () => { clear(); typed.value = ''; } }),
        h('span', { class: 'pv-grow' }),
        h('button', { class: 'btn primary', text: 'Use it', onclick: async () => {
          if (!words && !strokes.length) { toast(`Draw or type your ${what} first.`, 'info'); return; }
          const data = this._trim(c);
          d.close();
          this.v.app?.save({ [pref]: data });
          this.setTool(kind, { image: data, aspect: await this._aspect(data) });
          toast(`Click where your ${what} goes (or drag its size).`, 'info');
        } }))), { width: 520 });
  }

  _trim(c) { // just the ink, with a little margin
    const g = c.getContext('2d'), { width: w, height: hh } = c, px = g.getImageData(0, 0, w, hh).data;
    let x0 = w, y0 = hh, x1 = 0, y1 = 0;
    for (let y = 0; y < hh; y++) for (let x = 0; x < w; x++) if (px[(y * w + x) * 4 + 3] > 10) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
    const m = 8;
    x0 = Math.max(0, x0 - m); y0 = Math.max(0, y0 - m); x1 = Math.min(w - 1, x1 + m); y1 = Math.min(hh - 1, y1 + m);
    const out = h('canvas', { width: x1 - x0 + 1, height: y1 - y0 + 1 });
    out.getContext('2d').drawImage(c, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
    return out.toDataURL('image/png');
  }

  async _flatten() {
    if (!await this._confirm('Flatten', 'Make every comment, signature and filled-in field part of the pages? Nobody will be able to change or remove them after this (until you undo). Balloons on a print stay balloons.', 'Flatten')) return;
    await this.run('flatten', {}, 'Flattening…');
  }

  // ------------------------------------------------------------------ redacting
  async _redactFound() {
    const hits = this.v.hits || [];
    if (!hits.length) { this.v.findIn.focus(); return; } // (its button is off until Find has found something)
    if (this._marking) return; // (clicked again while the marks are still going in)
    this._marking = true;
    try {
      // places that are marked already (by this, or by hand) aren't marked a second time
      const marks = this.annots.filter((a) => a.kind === 'redact');
      const marked = (page, r) => marks.some((a) => a.page === page && inRect(a.rect, [r[0] + r[2] / 2, r[1] + r[3] / 2], 1));
      const fresh = hits.filter((hit) => !hit.rects.every((r) => marked(hit.page, r)));
      if (!fresh.length) { toast('Every place found is marked already. Check them, then Apply redactions.', 'info'); return; }
      const byPage = new Map(), doc = this.doc;
      for (const hit of fresh) byPage.set(hit.page, [...(byPage.get(hit.page) || []), ...hit.rects.filter((r) => !marked(hit.page, r))]);
      for (const [page, rects] of byPage) {
        if (this.doc !== doc) return;
        if (!await this.run('annot_add', { page, kind: 'redact', rects })) return; // (the toast says why it stopped)
      }
      const n = fresh.length, was = hits.length - n;
      toast(`Marked ${n} place${n === 1 ? '' : 's'}${was ? ` (${was} ${was === 1 ? 'was' : 'were'} marked already)` : ''}. Check them, then Apply redactions.`);
    } finally { this._marking = false; }
  }

  async _redactApply() {
    const n = this.annots.filter((a) => a.kind === 'redact').length;
    if (!n) {
      const k = this.annots.some((a) => a.kind === 'strikeout' && a.subject === 'Strike through');
      toast(k ? 'A cross-out needs no Apply: it shows and prints as it is, and stays a mark you can select and delete, even after saving.'
        : 'Mark something first: Mark text, Mark area or Mark all found.', 'info', 6000);
      return;
    }
    const s = (x) => (x === 1 ? '' : 's');
    const says = `Take everything under the ${n} redaction mark${s(n)} out of the pages for good: words, the parts of pictures and drawing they cover, and form fields with what's filled into them. Cross-outs stay as they are. It can't be undone in the saved file.`;
    if (!await this._confirm('Apply redactions', says, 'Apply')) return;
    const r = await this.run('redact_apply', { fill: load('pe:redact', 'black') }, 'Redacting…');
    if (r) toast('Redacted. Save to keep it (Save As keeps the original as it was).');
  }

  async _scrub() {
    if (!await this._confirm('Remove hidden information', "Take out the document's details (author, title, keywords), attached files, scripts, hidden text, and leftover data? Comments stay.", 'Remove')) return;
    await this.run('scrub', {}, 'Cleaning…');
  }

  _confirm(title, text, yes) {
    return new Promise((res) => {
      let answered = false;
      const d = modal(title, h('div', { class: 'pe-confirm' }, h('p', { text }),
        h('div', { class: 'pe-pop-foot' },
          h('button', { class: 'btn', text: 'Cancel', onclick: () => { answered = true; d.close(); res(false); } }),
          h('button', { class: 'btn primary', text: yes, onclick: () => { answered = true; d.close(); res(true); } }))), { width: 440 });
      const close = d.onClose;
      d.onClose = () => { close?.(); if (!answered) res(false); };
    });
  }

  // ================================================================== pages
  _sideOn() { if (!this.v.state.side) this.v._toggleSide(); }

  // the Pages tab: Select, which pages the commands will act on, then the commands (from PAGE_CMDS)
  _pagesTools() {
    const sep = () => h('span', { class: 'pv-sep' }), picked = this.picked.size > 0;
    this.scopeText = h('span', { text: this._scopeSays() });
    const chip = h('span', { class: `pe-scope${picked ? ' on' : ''}`,
      title: 'The pages these commands act on: the ones picked in the Pages panel (click one; Ctrl+click or Shift+click for several), or the page in view when none is picked.\nDrag thumbnails there to move pages, right-click one for more.' },
    this.scopeText,
    picked ? h('button', { class: 'pe-scx', text: '×', title: 'Clear the pick: the commands act on the page in view again', onclick: () => { this.picked.clear(); this._pickedChanged(); } }) : null);
    const out = [this._btn('select'), sep(), chip];
    let group = 0;
    for (const c of PAGE_CMDS.filter((x) => x.bar).sort((a, b) => a.bar - b.bar)) {
      if (Math.floor(c.bar) !== group) { out.push(sep()); group = Math.floor(c.bar); }
      out.push(c.tool ? this._btn(c.tool) : this._btn(c.id, { label: c.label, icon: c.icon, text: true, tip: c.tip, caret: !!c.sub,
        run: (b) => (c.sub ? menu(b, c.sub.map((x) => ({ label: x.label, action: () => x.run(this) }))) : c.run(this)) }));
    }
    return out;
  }

  _scopeSays() {
    const pages = this._which();
    return this.picked.size ? `Acting on: page${pages.length > 1 ? 's' : ''} ${pageList(pages)}` : `Acting on: page ${this.v._at() + 1}`;
  }

  // the pages were scrolled: with nothing picked, the page in view is the one the commands act on
  _scope() { if (this.scopeText?.isConnected && !this.picked.size) this.scopeText.textContent = this._scopeSays(); }

  // ================================================================== cleaning up a scan
  _enhance() {
    const cur = this.v.current || 0, picked = this.picked.size > 1 ? this._which() : null;
    const o = { specks: 1, straighten: true, text: true, ...load('pe:enhance', {}) };
    const radio = (value, label, on) => {
      const r = h('input', { type: 'radio', name: 'pe-enh-scope', value });
      r.checked = on;
      return [r, h('label', { class: 'pe-line' }, r, ` ${label}`)];
    };
    const [rAll, lAll] = radio('all', 'Every scanned page', !picked);
    const [rThis, lThis] = radio('this', `This page (${cur + 1})`, false);
    const [rPicked, lPicked] = picked ? radio('picked', `The ${picked.length} picked pages`, true) : [null, null];
    const specks = h('select', {}, ...[[0, 'Off'], [1, 'Light: the smallest specks'], [2, 'Strong: a hair bigger (check decimal points)']]
      .map(([v, t]) => h('option', { value: v, text: t, selected: +o.specks === v })));
    const straight = h('input', { type: 'checkbox' });
    straight.checked = !!o.straighten;
    const text = h('input', { type: 'checkbox' });
    text.checked = !!o.text;
    const before = h('img', { class: 'pe-enh-img', alt: 'Before' }), after = h('img', { class: 'pe-enh-img', alt: 'After' });
    const note = h('p', { class: 'pe-enh-note', text: 'Reading this page…' });
    const shots = h('div', { class: 'pe-enh-pair' },
      h('figure', {}, h('figcaption', { text: 'Before' }), before), h('figure', {}, h('figcaption', { text: 'After' }), after));
    const go = h('button', { class: 'btn primary', text: 'Enhance' });
    let ask = 0;
    const preview = async () => {
      const n = ++ask;
      note.textContent = 'Cleaning this page to show you…';
      try {
        const r = await this._ask('enhance_preview', { page: cur, specks: +specks.value, straighten: straight.checked });
        if (n !== ask) return;
        if (!r.scan) {
          shots.hidden = true;
          note.textContent = `Page ${cur + 1} isn't a scan: it's lines and text already (a print from CAD), sharp at any size. Pick a scanned page to see it cleaned.`;
          return;
        }
        shots.hidden = false;
        before.src = r.before;
        after.src = r.after;
        note.textContent = `Page ${cur + 1}${r.angle ? `, straightened by ${Math.abs(r.angle).toFixed(2)}°` : ''}. Check the decimal points and thin lines in the After picture are all there; Undo puts the pages back.`;
      } catch (e) { if (n === ask) note.textContent = e.message; }
    };
    specks.addEventListener('change', preview);
    straight.addEventListener('change', preview);
    const d = modal('Enhance scan', h('div', { class: 'pe-confirm pe-enh' },
      h('p', { text: 'Cleans up scanned pages: the paper made white and shadows taken out, the lines made solid black and broken ones joined, specks taken off, and the page straightened. Pages that are already lines and text are left alone.' }),
      h('div', { class: 'pe-enh-opts' },
        h('div', { class: 'pe-enh-col' }, h('b', { text: 'Pages' }), lAll, lThis, ...(lPicked ? [lPicked] : [])),
        h('div', { class: 'pe-enh-col' },
          h('label', { class: 'pe-frow' }, h('span', { text: 'Despeckle' }), specks),
          h('label', { class: 'pe-line' }, straight, ' Straighten the page'),
          h('label', { class: 'pe-line', title: 'Windows OCR reads the cleaned page, and what it reads goes under the picture as invisible text.\nThe print you see is the cleaned scan itself: nothing on it is retyped, so a misread cannot change a requirement.' },
            text, ' Make the text searchable (hidden OCR text)'))),
      note, shots,
      h('div', { class: 'pe-pop-foot' },
        h('button', { class: 'btn', text: 'Cancel', onclick: () => d.close() }), go)), { width: 860 });
    go.addEventListener('click', async () => {
      const scope = rThis.checked ? 'this' : rPicked?.checked ? 'picked' : 'all';
      const args = { pages: scope === 'this' ? [cur] : scope === 'picked' ? picked : null, specks: +specks.value, straighten: straight.checked, text: text.checked };
      keep('pe:enhance', { specks: args.specks, straighten: args.straighten, text: args.text });
      d.close();
      const r = await this.run('enhance', args, 'Cleaning up the scan…');
      if (!r) return;
      const x = r.result, n = x.enhanced.length;
      let msg = `Cleaned up ${n} scanned page${n === 1 ? '' : 's'}`;
      if (x.read) msg += `, with ${x.lines} line${x.lines === 1 ? '' : 's'} of searchable text`;
      if (x.skipped.length) msg += `. ${x.skipped.length} page${x.skipped.length === 1 ? ' was' : 's were'} already sharp and left alone`;
      toast(`${msg}.${args.text && !x.read ? ` ${x.error ? `OCR couldn't read it (${x.error})` : 'Searchable text needs Windows OCR, which isn\'t on this computer'}.` : ''} Undo puts it back.`, 'ok', 8000);
    });
    preview();
  }

  // Edit > Remove watermark: what's found, each to keep or take out, the first page with one before and after
  async _watermark() {
    const body = h('div', { class: 'pe-confirm pe-enh' }, h('p', { class: 'pe-enh-note', text: 'Looking for watermarks…' }));
    const d = modal('Remove watermark', body, { width: 860 });
    let r;
    try { r = await this._ask('watermark_find', {}); } catch (e) { body.replaceChildren(h('p', { text: e.message })); return; }
    const pages = (list) => (list.length === this.v.pages.length ? `every page` : list.length === 1 ? `page ${list[0] + 1}` : `${list.length} pages`);
    if (!r.items.length) {
      body.replaceChildren(
        h('p', { text: 'No watermark found: nothing marked as one, no watermark layer or comment, and no large or tilted words repeated on the pages.' }),
        h('p', { class: 'pe-enh-note', text: 'If you can see one, it may be a picture (Edit pictures, click it, Delete) or words you can select (in the Edit tab: Select, drag across them, Delete). One drawn as outlines can’t be picked out yet.' }),
        h('div', { class: 'pe-pop-foot' }, h('button', { class: 'btn primary', text: 'OK', onclick: () => d.close() })));
      return;
    }
    const ticks = r.items.map((it) => {
      const box = h('input', { type: 'checkbox', checked: true });
      return { it, box, row: h('label', { class: 'pe-line pe-wm-row' }, box, h('span', { text: ` ${it.label}` }), h('span', { class: 'pe-enh-note', text: ` (${pages(it.pages)})` })) };
    });
    const go = h('button', { class: 'btn primary', text: 'Remove' });
    const sync = () => { go.disabled = !ticks.some((t) => t.box.checked); };
    ticks.forEach((t) => t.box.addEventListener('change', sync));
    body.replaceChildren(
      h('p', { text: 'Found on this PDF. Ticked ones are taken out of every page they’re on; nothing else on the pages changes, and Undo puts them back.' }),
      h('div', { class: 'pe-wm-list' }, ...ticks.map((t) => t.row)),
      r.kept.length ? h('p', { class: 'pe-enh-note', text: `On ${r.kept.length === 1 ? `page ${r.kept[0] + 1}` : `pages ${r.kept.map((i) => i + 1).join(', ')}`} the repeated words run through other words, so they stay there (taking them out would take those too): select them in the Edit tab and press Delete to do it by hand.` }) : '',
      r.page != null ? h('div', { class: 'pe-enh-pair' },
        h('figure', {}, h('figcaption', { text: `Before (page ${r.page + 1})` }), h('img', { class: 'pe-enh-img', src: r.before, alt: 'Before' })),
        h('figure', {}, h('figcaption', { text: 'After, with everything found taken out' }), h('img', { class: 'pe-enh-img', src: r.after, alt: 'After' }))) : '',
      h('div', { class: 'pe-pop-foot' }, h('button', { class: 'btn', text: 'Cancel', onclick: () => d.close() }), go));
    go.addEventListener('click', async () => {
      const on = ticks.filter((t) => t.box.checked).map((t) => t.it);
      const kinds = [...new Set(on.map((it) => it.kind))];
      const keys = on.filter((it) => it.kind === 'text').map((it) => it.key);
      d.close();
      const res = await this.run('watermark_remove', { kinds, keys: kinds.includes('text') ? keys : null }, 'Removing the watermark…');
      if (!res) return;
      const x = res.result;
      toast(`Watermark taken out of ${x.pages} page${x.pages === 1 ? '' : 's'}${x.kept.length ? `; left on ${pages(x.kept)} where it runs through other words` : ''}. Undo puts it back.`, 'ok', 7000);
    });
  }

  _which() { return this.picked.size ? [...this.picked].sort((a, b) => a - b) : [this.v.pages?.length ? this.v._at() : 0]; }

  async _pagesDelete() {
    const pages = this._which();
    if (!await this._confirm('Delete pages', `Take out ${pages.length === 1 ? `page ${pages[0] + 1}` : `${pages.length} pages`}?`, 'Delete')) return;
    if (await this.run('pages_delete', { pages })) this._gone(pages.length === 1 ? `Page ${pages[0] + 1} deleted.` : `${pages.length} pages deleted.`);
  }

  async _insertFiles(at) {
    const r = await api.openFiles('pdf', 'Choose PDFs or pictures to insert').catch((e) => { toast(e.message, 'error'); return null; });
    if (!r?.files?.length) return;
    const res = await this.run('pages_insert_file', { at, paths: r.files.map((f) => f.path) }, 'Inserting…');
    if (res) toast(`Added ${res.result.added} page${res.result.added === 1 ? '' : 's'}.`);
  }

  async _replace() {
    const r = await api.openFiles('pdf', 'Choose the file with the new pages').catch(() => null);
    if (!r?.files?.length) return;
    const res = await this.run('pages_replace', { pages: this._which(), path: r.files[0].path });
    if (res) toast(`Replaced ${res.result.replaced} page${res.result.replaced === 1 ? '' : 's'}.`);
  }

  async _extract() {
    const pages = this._which(), stem = this.doc.name.replace(/\.pdf$/i, '');
    const name = pages.length === 1 ? `${stem} (page ${pages[0] + 1}).pdf` : `${stem} (pages).pdf`;
    const r = await api.savePdfDialog(name, 'Extract pages to').catch(() => null);
    if (!r?.path) return;
    const res = await this.run('pages_extract', { pages, path: r.path });
    if (res) this._saved(`Saved ${pages.length} page${pages.length === 1 ? '' : 's'} to ${r.path.split(/[\\/]/).pop()}.`, r.path);
  }

  _saved(msg, path) {
    const t = toast(msg, 'ok', 6000);
    if (this.v.app?.native !== false) t.append(h('button', { class: 'btn', text: 'Show', onclick: () => api.reveal(path) }));
  }

  _split() {
    const every = h('input', { class: 'pe-num', type: 'number', min: '1', value: '1' });
    const ranges = h('input', { class: 'pe-type', placeholder: 'or ranges, such as 1-3, 4-9, 10-', spellcheck: 'false' });
    [every, ranges].forEach((i) => i.addEventListener('keydown', (e) => e.stopPropagation()));
    const d = modal('Split the document', h('div', { class: 'pe-confirm' },
      h('p', { text: `Saves the pieces next to ${this.doc.name}, as "name (pages 1-3).pdf" and so on. The document itself stays as it is.` }),
      h('label', { class: 'pe-line' }, 'Every ', every, ' pages'), ranges,
      h('div', { class: 'pe-pop-foot' },
        h('button', { class: 'btn', text: 'Cancel', onclick: () => d.close() }),
        h('button', { class: 'btn primary', text: 'Split', onclick: async () => {
          const n = this.v.pagesInfo.length;
          let args = { every: Math.max(1, parseInt(every.value, 10) || 1) };
          if (ranges.value.trim()) {
            const list = ranges.value.split(',').map((x) => x.trim()).filter(Boolean).map((x) => {
              const [a, b] = x.split('-');
              return [parseInt(a, 10) || 1, b === undefined ? parseInt(a, 10) : b === '' ? n : parseInt(b, 10)];
            });
            if (list.some(([a, b]) => !a || !b)) { toast('Write the ranges like 1-3, 4-9, 10-', 'error'); return; }
            args = { ranges: list };
          }
          d.close();
          try {
            const r = await this._ask('split', args);
            this._saved(`Saved ${r.paths.length} PDF${r.paths.length === 1 ? '' : 's'}.`, r.paths[0]);
          } catch (e) { toast(e.message, 'error'); }
        } }))), { width: 460 });
  }

  // a crop was dragged out: its box stays on the page while the options strip asks which pages get it (_cropBar)
  _cropAsk(p, r) {
    this._cropEnd();
    const svg = this._ghost(p);
    this._ghostShape(svg, p, 'crop', [r[0], r[1]], [r[0] + r[2], r[1] + r[3]]);
    this.cropAsk = { p, r, svg, pages: this.picked.size > 1 && this.picked.has(p.i) ? this._which() : [p.i] };
    this._optsBar();
  }

  // the page view's thumbnails: pick (Ctrl/Shift+click), drag to move, right-click for page tools
  thumb(t, i) {
    if (!this.editable) return;
    t.draggable = true;
    t.classList.toggle('pick', this.picked.has(i));
    t.addEventListener('click', (e) => {
      if (e.ctrlKey || e.metaKey) { if (this.picked.has(i)) this.picked.delete(i); else this.picked.add(i); }
      else if (e.shiftKey && this.lastPick != null) { for (let k = Math.min(i, this.lastPick); k <= Math.max(i, this.lastPick); k++) this.picked.add(k); }
      else { this.picked.clear(); this.picked.add(i); }
      this.lastPick = i;
      this._pickedChanged();
    });
    t.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      if (!this.picked.has(i)) { this.picked.clear(); this.picked.add(i); this._pickedChanged(); }
      const n = this._which().length, items = []; // (the same commands as the Pages tab, in the same order)
      let group = 0;
      for (const c of PAGE_CMDS) {
        if (group && c.group !== group) items.push({ sep: true });
        group = c.group;
        items.push(c.sub ? { label: c.label, sub: c.sub.map((x) => ({ label: x.label, action: () => x.run(this) })) }
          : { label: c.menuLabel ? c.menuLabel(n) : c.label, action: () => c.run(this) });
      }
      menu(t, items);
    });
    t.addEventListener('dragstart', (e) => {
      if (!this.picked.has(i)) { this.picked.clear(); this.picked.add(i); this._pickedChanged(); }
      e.dataTransfer.setData('text/x-pages', JSON.stringify(this._which()));
      e.dataTransfer.effectAllowed = 'move';
    });
    t.addEventListener('dragover', (e) => {
      if (!e.dataTransfer.types.includes('text/x-pages')) return;
      e.preventDefault();
      const r = t.getBoundingClientRect(), after = e.clientY > r.top + r.height / 2;
      this.v.side.querySelectorAll('.drop-before, .drop-after').forEach((n) => n.classList.remove('drop-before', 'drop-after'));
      t.classList.add(after ? 'drop-after' : 'drop-before');
    });
    t.addEventListener('dragleave', () => t.classList.remove('drop-before', 'drop-after'));
    t.addEventListener('drop', (e) => {
      const raw = e.dataTransfer.getData('text/x-pages');
      t.classList.remove('drop-before', 'drop-after');
      if (!raw) return;
      e.preventDefault();
      const r = t.getBoundingClientRect(), to = e.clientY > r.top + r.height / 2 ? i + 1 : i;
      this.run('pages_move', { pages: JSON.parse(raw), to });
    });
  }

  _pickedChanged() {
    this.v.side.querySelectorAll('.pv-thumb').forEach((n) => n.classList.toggle('pick', this.picked.has(+n.dataset.page)));
    if (this.set === 'pages') this._bar();
  }

  // ================================================================== the comments list
  togglePanel() {
    this.showPanel = !this.showPanel;
    keep('pe:panel', this.showPanel);
    this.panel.hidden = !this.showPanel;
    if (this.showPanel) this._renderPanel();
    this._bar();
    this.v._resized();
  }

  _label(a) {
    if (a.clouds) return 'Cloud';
    if (a.kind === 'line' && a.arrow) return 'Arrow';
    if (a.subject && !/^(Image Stamp|Stamp)$/.test(a.subject)) return a.subject.replace(/([a-z])([A-Z])/g, '$1 $2');
    return KIND_LABEL[a.kind] || a.kind;
  }

  _top() { return this.annots.filter((a) => !a.replyTo && a.kind !== 'popup'); }

  _renderPanel() {
    const top = this._top(), replies = (id) => this.annots.filter((a) => a.replyTo === id);
    const head = h('div', { class: 'pe-ph' }, h('b', { text: `Comments (${top.length})` }), h('span', { class: 'pv-grow' }),
      h('button', { class: 'pv-btn', text: '×', title: 'Close', onclick: () => this.togglePanel() }));
    if (!top.length) { this.panel.replaceChildren(head, h('p', { class: 'pe-empty', text: 'No comments yet. Pick a tool from Comment to add one.' })); return; }
    const list = h('div', { class: 'pe-list' });
    let page = -1;
    for (const a of top) {
      if (a.page !== page) { page = a.page; list.append(h('div', { class: 'pe-pg', text: `Page ${this.v.pagesInfo[page]?.label || page + 1}` })); }
      const words = h('div', { class: 'pe-words', text: a.contents || '', contenteditable: 'plaintext-only', 'data-ph': 'Add a comment' });
      words.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); words.blur(); } });
      words.addEventListener('blur', () => {
        const t = words.textContent;
        if (t === (a.contents || '')) return;
        if (a.kind === 'text' && !t.trim()) this._emptied(a); // (a text comment with no words would be there, and invisible)
        else this.run('annot_set', { page: a.page, id: a.id, ...(a.kind === 'text' ? { text: t } : { contents: t }) });
      });
      const reply = h('input', { class: 'pe-reply', placeholder: 'Reply…', spellcheck: 'true' });
      reply.addEventListener('keydown', (e) => {
        e.stopPropagation();
        if (e.key !== 'Enter' || e.repeat || reply.disabled || !reply.value.trim()) return;
        const t = reply.value.trim(); // sent once: the box empties and waits (and gets its words back if they couldn't be added)
        reply.value = '';
        reply.disabled = true;
        this.run('annot_reply', { page: a.page, id: a.id, contents: t }).then((r) => {
          if (!reply.isConnected) return;
          reply.disabled = false;
          if (!r) reply.value = t;
        });
      });
      const item = h('div', { class: `pe-item${this.sel?.id === a.id && this.sel?.page === a.page ? ' on' : ''}` },
        h('div', { class: 'pe-meta' }, h('span', { class: 'pe-dot', style: { background: (a.kind === 'text' ? a.textColor : a.color) || a.textColor || '#999' } }),
          h('b', { text: this._label(a) }), h('span', { text: a.author || '' }), h('span', { class: 'pv-grow' }),
          h('span', { class: 'pv-of', text: pdfDate(a.date) }),
          h('button', { class: 'pe-del', title: 'Delete', text: '×', onclick: (e) => { e.stopPropagation(); this._deleteAnnot(a); } })),
        a.quote && a.quote !== a.contents ? h('div', { class: 'pe-quote', text: a.quote, title: 'The words it marks' }) : null,
        words,
        ...replies(a.id).map((r) => h('div', { class: 'pe-replyrow' }, h('b', { text: r.author || '' }), h('span', { text: ` ${r.contents}` }),
          h('button', { class: 'pe-del', title: 'Delete the reply', text: '×', onclick: () => this._deleteAnnot(r) }))),
        reply);
      item.dataset.id = a.id;
      item.dataset.page = a.page;
      item.addEventListener('click', (e) => {
        if (e.target.closest('.pe-words, .pe-reply, .pe-del')) return;
        this.setTool('select');
        this.select({ type: 'annot', page: a.page, id: a.id, rect: a.rect, a });
        const p = this.v.pages[a.page];
        p.edit.querySelector('.pe-sel')?.scrollIntoView({ block: 'center', inline: 'nearest' });
      });
      list.append(item);
    }
    this.panel.replaceChildren(head, list);
  }

  // ================================================================== undo, redo and saving
  undo() {
    if (this._inkBack()) return; // (a pen stroke not sent yet: just that stroke)
    this._flushNudge(); // (what the arrow keys just moved goes in first, and is what's undone)
    this._step('undo');
  }

  redo() {
    this._flushNudge();
    this._step('redo');
  }

  // One step back or forward. It waits for the edits still on their way (a box just ticked, a nudge), so whether
  // there's a step to take is known and it's the last edit that's undone; and asked again before the worker has
  // answered (the key held down), it's one step at a time, never a step that isn't there
  async _step(op) {
    const doc = this.doc;
    if (!doc || this._stepping) return;
    this._stepping = true;
    try {
      await doc._peQ;
      if (this.doc === doc && this.state?.[op]) await this.run(op);
    } finally { this._stepping = false; }
  }

  // whatever is being typed (a field, a box on the page) goes in, and every edit lands, before saving
  async _settle() {
    const doc = this.doc;
    for (const el of this.fieldEls.values()) if (el.timer || document.activeElement === el) { el.timer = null; el.commit(); }
    this._endInline(true);
    this._pop?.shut(true);
    this._inkFlush();
    this._flushNudge();
    await doc?._peQ;
  }

  // Save and Save As, one at a time: asked again while one is under way (Ctrl+S twice), the one save answers both
  save() { return this._saveOnce(() => this._save()); }

  saveAs() { return this._saveOnce(() => this._saveAs()); }

  _saveOnce(go) {
    if (!this.editable) return Promise.resolve(false);
    if (this._saving) return this._saving;
    const p = this._saving = go().finally(() => { if (this._saving === p) this._saving = null; });
    return p;
  }

  async _save() {
    const doc = this.doc;
    await this._ready;
    await this._settle();
    if (this.doc !== doc) return false; // (another document came forward meanwhile: this save was for the one before)
    if (doc.meta.pdf.saveAs) return this._saveAs();
    if (!this.state?.dirty) { toast('No changes to save.', 'info'); return true; }
    const r = await this._saveRun({}, true);
    if (r === 'copy') return this._saveAs();
    if (r) toast(r.result?.appended ? `Saved ${doc.name}: the changes were added to the end of the file, so what was signed or checked stays as it was.` : `Saved ${doc.name}.`, 'ok', r.result?.appended ? 6000 : 3000);
    return !!r;
  }

  // a save, asking first when the file changed on disk since it was opened, or when saving would undo a signature,
  // PDF/A or XFA form (the editor answers with a question rather than saving): the answer, 'copy', or null
  async _saveRun(args, copy) {
    for (;;) {
      const r = await this.run('save', args, 'Saving…');
      const ask = r?.result?.ask;
      if (!ask) return r;
      const pick = await new Promise((res) => {
        let done = false;
        const go = (a) => { done = true; d.close(); res(a); };
        const d = modal(ask.title, h('div', { class: 'pe-confirm' },
          h('p', { text: ask.text }),
          h('div', { class: 'pe-pop-foot' },
            h('button', { class: 'btn', text: 'Cancel', onclick: () => go('cancel') }),
            h('button', { class: copy ? 'btn' : 'btn primary', text: ask.go, onclick: () => go('go') }),
            copy ? h('button', { class: 'btn primary', text: 'Save a copy…', onclick: () => go('copy') }) : null)), { width: 460 });
        const was = d.onClose;
        d.onClose = () => { was?.(); if (!done) res('cancel'); };
      });
      if (pick === 'cancel') return null;
      if (pick === 'copy') return 'copy';
      args = { ...args, [ask.kind === 'changed' ? 'changedOk' : 'guardsOk']: true };
    }
  }

  async _saveAs() {
    const doc = this.doc;
    if (!this.editable) return false;
    await this._ready;
    await this._settle();
    if (this.doc !== doc) return false;
    const r = await api.savePdfDialog(doc.name, 'Save PDF As').catch((e) => { toast(e.message, 'error'); return null; });
    if (!r?.path || this.doc !== doc) return false;
    const res = await this._saveRun({ path: r.path }, false);
    if (!res) return false;
    doc.path = r.path;
    doc.name = r.path.split(/[\\/]/).pop();
    doc.meta.path = r.path;
    doc.meta.name = doc.name;
    doc.meta.pdf.saveAs = false;
    this.v.app?.shell?.renderDocTabs();
    if (this.v.app && this.doc === doc) { document.title = `${doc.name} - ${PRODUCT}`; api.title(document.title); }
    toast(`Saved as ${doc.name}.`);
    return true;
  }
}
