# Spica: artistic direction

Oct 23, 2026 · @Thomas

## Name and idea

Spica is a bright star in Virgo whose Latin name means "ear of grain". The product does the same job: it separates the best candidates from the rest, without the data ever leaving the client's building.

The brand should feel bright, precise and calm. Cheerful enough to stand out from grey lab software, rigorous enough that a head of research trusts a one-person team.

- **Bright:** white space and a vivid azure, never dull
- **Precise:** every number aligned, sourced and legible
- **Calm:** few colors, no decoration, no hype
- **Cool, not warm:** cool whites and blues, which set it apart from the warm cream of many AI tools

## Color

White and cool neutrals carry the interface; a vivid azure is the only accent.

| Name | Hex | Role |
| --- | --- | --- |
| Azure | #00B2FF | Highlights: active chips, top score bars, selection, focus rings |
| Deep azure | #0077CC | Links, filled buttons, any accent-colored text |
| Mist | #EAF7FF | Tinted backgrounds: selected rows, chips, callouts |
| Frost | #F5FAFF | Page background behind white cards |
| White | #FFFFFF | Cards and the main working surface |
| Ink | #0B1B2B | Body text and headings |
| Slate | #5B6B7C | Secondary text, labels, metadata |
| Line | #E3EBF3 | Borders and dividers |
| Amber | #FEF3C7 fill, #92400E text | System warnings only |

- Azure is an accent, not wallpaper. If a screen starts to look blue overall, pull back.
- Azure is too faint for text on white (about 2.4:1). Accent text is always deep azure (about 4.6:1, passes WCAG AA).
- One filled button per screen; the rest are outlined or plain.
- Amber warnings always come with an icon and words, never color alone.

## Data color

In a scoring tool, color is data, so data colors follow fixed rules and stay separate from interface colors.

| Data | Scale | Colors |
| --- | --- | --- |
| Scores and ranks | One azure scale, stronger = higher | #99DEFF low, #4DC9FF mid, #00B2FF high |
| Fold change, signed values | Diverging around a neutral grey midpoint | Orange #F97316 up, azure #0077CC down |
| Missing or unmapped | Neutral | Slate text that names it (not measured, not found), never blank |

- Never red and green: about 1 in 12 men cannot tell them apart.
- Orange appears only in data, never on buttons, chips or headings.
- Color never carries meaning alone. Every bar or cell keeps its number, sign or label, so a grayscale print still reads.

## Dark mode

Settings, Appearance: Light (the default), Dark, or As Windows. The same cool family at
night: deep navy surfaces, never warm grey or black, and the one azure accent.

| Token | Light | Dark |
| --- | --- | --- |
| Frost (page) | #F5FAFF | #0A121C |
| Surface (cards) | #FFFFFF | #101B28 |
| Mist (tints) | #EAF7FF | #13283D |
| Line | #E3EBF3 | #223247 |
| Ink | #0B1B2B | #E7EEF5 |
| Slate | #5B6B7C | #95A5B5 |
| Azure | #00B2FF | #33C2FF |
| Deep azure (accent text, buttons) | #0077CC | #5CCBFF |
| Text on a filled button | #FFFFFF | #04121F |
| Amber warning (fill, text) | #FEF3C7, #92400E | #3A2A10, #F5C46B |

- Every colour is a token in `frontend/src/index.css`, set for both themes there; a
  component never writes a hex value. Code that has to compute a colour (a heatmap ramp, a
  canvas) reads the token and redraws when the theme changes (`theme.ts`, `useTheme`).
- Contrast holds in both: accent text 9.5:1 on a dark card, slate 6.9:1, button text 10:1.
- Data colour is re-stepped, not inverted: on dark, more is brighter, and every step of the
  sequential ramp clears 3:1 against the card (#276FA0, #2F9EDB, #48BDF5, #9BE0FF). Each step
  names the text that reads on it.
- What draws its own light canvas (the genome browser) stays a light island rather than
  half-following the theme.

## Typography

Sora sets the interface; JetBrains Mono sets anything a scientist will compare or copy.

| Use | Font | Weight | Size |
| --- | --- | --- | --- |
| Page titles | Sora | 700 | 28 to 32 px |
| Section headings | Sora | 600 | 18 to 20 px |
| Body and labels | Sora | 400 | 14 to 15 px |
| Table headers | Sora | 500 | 12 to 13 px |
| Gene IDs, scores, sequences, accessions | JetBrains Mono | 400 to 500 | 12 to 13 px |

- Tighten Sora slightly at small sizes (letter-spacing around -0.01em); its wide letters otherwise crowd labels.
- Monospaced data keeps every column of numbers aligned without extra work.
- Sentence case everywhere, no all-caps labels.
- Both fonts are under the SIL Open Font License, free to bundle with the product.

## Shape and space

Soft shapes and flat surfaces keep it friendly; dense tables keep it serious.

- **Buttons and chips:** fully rounded pills.
- **Cards:** 14 to 16 px corner radius, 1 px Line border, no shadow.
- **Rows and small controls:** 8 to 10 px radius.
- **Depth:** white cards on the Frost page. No shadows, gradients, glows or textures.
- **Airy chrome, dense data:** generous margins around panels; tables compact enough to show 15 to 20 rows at once.
- **Score bars:** about 7 px tall, rounded ends, on a pale track, always next to their number.
- **Charts:** one azure fill for a single series. Length carries the magnitude, so shading
  by value would say it twice and the pale end of the ramp is invisible on white. Bars are
  14 px on a mist track, square at the baseline, 4 px rounded at the data end. Every bar
  keeps its figure, which is what makes the chart readable in grayscale and what lets the
  log view be honest. Linear by default; a log toggle sits in the caption and says plainly
  that bar length is no longer proportional.
- **A plot wherever the data allows one.** A map of numbers, a set of scores across genes,
  a count over time: each gets a chart beside its figures, not instead of them.
- **Word maps** (the report's "At a glance") carry one measure, in size; the strongest
  words also take deep azure, the rest ink or slate, never a colour per word. No rotation,
  no random placement: words pack on a spiral from the centre, heaviest first, so a gene
  always draws the same picture. Each word gives its figure on hover and its source terms
  on click, and a list view holds every word with its number.
- **Never cut data.** A view may abbreviate; it may never truncate. Every "+46 more" opens,
  every top-12 extends to all 54. What was measured stays reachable.

## Logo direction

The mark is an azure four-point star read as a neuron: three equal short branches (dendrites), one long ray (the axon) that runs under the name, and a white core (the nucleus).

- **Nucleus:** a white Gaussian falloff in the star's center, clipped to the star. It is the only gradient in the brand.
- **Wordmark:** SPICA in letter-spaced capitals, Sora 600, in ink, sitting on the long ray.
- **Uses:** the star alone serves as app icon, favicon and stamp on client reports.
- **Test first in one color** (ink on white, white on azure) before adding any detail.

## Voice and the client report

Spica presents data, not conversation. Copy is minimal and scientific, and follows
ASD-STE100 Simplified Technical English.

- ASD-STE100: one topic per sentence; procedural sentences of 20 words or fewer,
  descriptive sentences of 25 or fewer; active voice, present tense; one word for one
  meaning.
- Titles are noun phrases, never sentences or questions: "Expression by organ",
  "Regulation atlas", "Mapping review"; not "Is the protein where the message is?".
- No direct address and no conversation: no "you", "we", "let's", "try", "pick",
  "please"; no tips on how to hover or click. A label says what the field holds.
- No placeholders in input fields: a visible label names the field.
- No rhetorical forms: no "not just X, but Y", no "this is not X, this is Y", no
  emphasis words.
- No em dashes, anywhere a user reads: interface, messages, reports, docs. Use a comma,
  a colon, a full stop or parentheses. A missing value says what it is ("not measured"),
  it is not drawn as a dash.
- States and errors are terse: "No gene entered.", "Report not saved: <cause>.",
  "Online access off (Settings)."
- Short labels; verbs on buttons only: "Export report", "Compare", "Open".
- Every number links to its source and database version.
- A plot wherever the data allows one; a sentence only for what a plot cannot show.

The client report is what most clients will see, so it gets the most care.

- Same palette and fonts as the app, on white so it prints well.
- Cover: the star, project name, date and data versions.
- Page one is the ranked table; per-candidate profiles and reasoning follow.
- Reads correctly in grayscale, since every bar keeps its number.
- Built by `spica/export.py`. Exported from Candidates, page one is the ranked table, with
  the weights and what each criterion reads; exported from Compare, it is the comparison,
  unranked, the highest marked in words. One HTML
  file with the fonts embedded and a Content-Security-Policy, so it never fetches anything;
  A4 print styles, the comparison on a landscape page, page numbers in the footer. Lists
  past 25 rows show the first 25 and keep the rest behind a click, never cut.

## What to avoid

- Warm cream or beige backgrounds, which read as generic AI tools
- Red and green pairs anywhere
- Gradients, glows, drop shadows, glass effects (the logo's nucleus is the only exception)
- Stock biotech imagery: glowing DNA helices, floating molecules, blue gloves
- A second accent hue in the interface
- Azure text on white
- Hype words such as "revolutionary", "AI-powered", "unlock"
