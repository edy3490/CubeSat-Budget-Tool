# CubeSat Budget Tool: index.html reference

## Current version (served by `server.py`)

Run `sat-parser/.venv/bin/python server.py` from the repo root and open http://localhost:8000. The page is a thin client: the server owns the spec and all the numbers.

| Call | Body | Returns |
|---|---|---|
| `POST /api/budget` | `{}` | Starter design: `{spec, budget, design, build_plan, quick_scene, tokens}` (`reply` is null) |
| `POST /api/cubesat-chat` | `{messages, spec}` | Same fields plus `reply`. Send back the `spec` from the last response; it carries a `design_id` for follow-up edits |
| `POST /api/visual` | `{design_id, regenerate}` | 3D scene drawn by Sonnet (Haiku after 25k tokens), see `visualizer/README.md` |
| `GET /api/tokens` | | Sonnet token budget |

Errors come back as `{"detail": "..."}`. `budget` keeps the shape `render(b)` expects (`mass`, `maxMass`, `massRatio`, `massState`, `watts`, `powRatio`, `powState`, `cost`, `rows`, `notes`), filled from real parts by `designer/`. Extra fields: `gen`, `hardware`, `launch`, `costIsMinimum`, `unpriced`, and per row `part_index`, `gen_w`, `estimate` (`k` is null when a part has no public price).

The page opens on a **landing page** (hero, prompt box, example chips). Sending an idea opens the workspace, and **New design** goes back to the landing page. Links with `?idea=...` skip the landing page.

On top of the original layout the page adds a **3D model** (in place of the stack sketch) and a **build plan**:

- The 3D model shows a quick rule-based layout first, then the model's drawing. It has explode/assemble, a spread slider, part labels and hover details, and hovering a table row highlights its part. **Export STEP** downloads it as solid parts for CAD (SolidWorks, Fusion 360, FreeCAD, Onshape), and **Export STL** as a mesh for 3D printing (see `visualizer/README.md`).
- The Sonnet token meter is shown in the corner of the 3D view.
- The starter design never spends tokens; click **Draw with AI** to have it drawn.
- Under the 3D model, **How it works** shows the model's explanation: an overview, what each part does and why it was picked, and why the layout fits.
- Parts the model added for an unusual request (a laser, say) are marked "added for your request" in the 3D labels, in How it works, and as extra rows in the Subsystems table. They're estimates and aren't counted in the totals.

> Sections 2-6 below describe the earlier standalone version (built-in parts tables, demo parser, Model settings). The page no longer has those; the server does that work now.

`index.html` is the whole app: markup, styles and script in one file. There is no build step and no dependencies. The only external request is the IBM Plex fonts from Google Fonts, and the page falls back to system fonts if they don't load.

## 1. How it works

1. The user types a mission idea or a change in the chat.
2. The page sends the chat history and the current design (the **spec**) to your model endpoint. With no endpoint set, a keyword parser runs instead (demo mode).
3. The model returns a reply and an updated spec.
4. `computeBudget(spec)` turns the spec into mass, power and cost numbers using the parts tables in the script. The model never produces these numbers.
5. `render()` redraws the stat cards, subsystem table, flags, stack sketch and tabs.

```
chat input -> callModel() / demoParse() -> spec -> computeBudget() -> render()
```

## 2. The spec

The spec is the one object that describes a design. It is what your model reads and writes.

| Field | Type | Meaning |
|---|---|---|
| `form` | `"3U"` \| `"6U"` \| `"12U"` | Form factor. Sets mass limit, solar generation, structure and power-system size. |
| `payload` | `"camera"` \| `"spectrometer"` \| `"iot"` | Main payload. Sets payload mass, power, cost and the pointing system. |
| `altitude_km` | number | Orbit altitude. Above 800 km adds shielding. Below 450 km adds a drag warning. |
| `years` | number | Mission life. Over 2 years adds shielding. Each year past the first adds battery mass and cost. |
| `subsystems` | array (optional) | Extra parts the user asked for. Each one gets its own tab. See section 5. |

Default spec: `{ form: "6U", payload: "camera", altitude_km: 500, years: 1 }`.

Unknown `form` or `payload` values fall back to `6U` and `camera`. A missing or invalid `altitude_km` falls back to 500, and `years` is clamped to at least 1.

When a response arrives, the page merges it into the current spec (`Object.assign`). Fields the model leaves out keep their old values. The exception is `subsystems`: if the model returns that key, it replaces the whole list, so return the full list every time.

## 3. Model endpoint contract

Set the URL in **Model settings**. The page sends `POST` with `Content-Type: application/json`, plus an `Authorization` header if you entered one.

Request:

```json
{
  "messages": [
    { "role": "user", "content": "6U CubeSat that images wildfires from LEO for 1 year" },
    { "role": "assistant", "content": "Here is a starting design..." }
  ],
  "spec": { "form": "6U", "payload": "camera", "altitude_km": 500, "years": 1 }
}
```

Response:

```json
{
  "reply": "Text shown in the chat.",
  "spec": { "form": "6U", "payload": "camera", "altitude_km": 500, "years": 1 }
}
```

Behavior to know:

- If `spec` is missing but `reply` contains a fenced ```` ```json ```` block, the page parses the spec from that block and removes the block from the displayed reply.
- If `reply` is empty, the chat shows "Updated the design."
- A non-2xx response shows an error in the chat. A network failure also hints at CORS. After an error the last user message is removed from the history sent next time.
- If the page and endpoint are on different origins, your server must send CORS headers.
- The endpoint URL and authorization value are stored in the browser's `localStorage` (keys `cs_endpoint`, `cs_auth`). Anyone using that browser can read them, so use a low-privilege token and keep real keys on your server.

Suggested system prompt for the model:

> You turn a CubeSat mission idea into a JSON spec with keys form (3U|6U|12U), payload (camera|spectrometer|iot), altitude_km (number), years (number), and optionally subsystems. You receive the current spec; change only what the user asked to change. Reply with a short plain-language message and the full updated spec.

## 4. Budget engine: `computeBudget(spec)`

Pure function. Takes a spec, returns an object the renderer uses. No DOM access.

### Parts tables (edit these with your real data)

All triples are `[mass kg, power W, cost $k]`.

**`FORMS`**

| Form | Units | Max mass (kg) | Solar generation (W) | Structure | Power system |
|---|---|---|---|---|---|
| 3U | 3 | 4 | 6 | 0.6, 0, 25 | 1.1, 0, 80 |
| 6U | 6 | 12 | 14 | 1.2, 0, 40 | 2.1, 0, 120 |
| 12U | 12 | 24 | 30 | 2.4, 0, 70 | 3.8, 0, 190 |

**`PAYLOADS`** (each also carries the pointing system it needs in `adcs`)

| Key | Name | kg | W | $k | Pointing (ADCS) |
|---|---|---|---|---|---|
| `camera` | Camera payload | 1.5 | 8 | 150 | 0.8, 2, 90 |
| `spectrometer` | Spectrometer payload | 1.8 | 10 | 220 | 0.9, 3, 110 |
| `iot` | IoT relay payload | 0.6 | 3 | 70 | 0.5, 1, 40 |

**Fixed parts:** `RADIO = [0.5, 4, 60]`, `OBC = [0.3, 1, 20]` (flight computer).

### Rules

- **Harsh environment:** `years > 2` or `altitude_km > 800`. Adds 0.3 kg and $15k to the structure for shielding.
- **Battery sizing:** each year past the first adds 0.1 kg and $15k to the power system.
- **Rows:** payload, structure, power system, pointing, radio, flight computer, then one row per added subsystem. Totals are plain sums of the rows.
- **Power state:** peak draw divided by solar generation. Over 1.0 is `over`, over 0.7 is `tight`, otherwise `ok`.
- **Mass state:** total mass divided by the form's limit. Over 1.0 is `over`, over 0.85 is `tight`, otherwise `ok`.

Peak draw means every part running at once, compared against orbit-average generation. This is deliberately conservative, so a design can show "tight" or "over" even when duty cycling would make it work. Change the thresholds in `computeBudget` if you want a different margin policy.

### Flags

Each flag has a level (`good`, `warn`, `bad`) that colors its dot. The engine can produce:

- Mass fits, near the limit, or over the limit (with the excess in kg).
- Power has margin, is tight, or is over (with the percentage of generation used).
- Higher radiation environment, or long-life margin, when the harsh rule applies.
- Drag warning when altitude is under 450 km.

### Return value

`{ custom, form, maxMass, gen, rows, mass, watts, cost, powRatio, massRatio, powState, massState, notes, spec }`

## 5. Added subsystems and tabs

A subsystem is an extra part beyond the six base rows.

```json
{
  "id": "star-tracker",
  "name": "Star tracker",
  "kg": 0.35,
  "w": 1.5,
  "cost": 90,
  "description": "Fine attitude knowledge for sharp pointing.",
  "estimate": false
}
```

| Field | Notes |
|---|---|
| `id` | Used for the tab and removal. If omitted it is made from `name` (lowercase, hyphens). |
| `name` | Shown on the tab and in the table. Defaults to "Subsystem". |
| `kg`, `w`, `cost` | Numbers. Anything non-numeric becomes 0. `k` is accepted as an alias for `cost`. |
| `description` | Optional text on the tab. |
| `estimate` | `true` shows a "placeholder estimate" tag. Use it when the numbers are guesses. |

Each subsystem is added to the totals and the table, and gets a tab beside **Budget**. The tab shows:

- Mass, power and cost, each with its share of the total.
- An "Effect on the design" section showing totals before and after, against the mass limit and solar generation.
- A **Remove** button.

Tab behavior:

- A newly added subsystem's tab opens automatically. It shows a dot if the user switches away before looking at it.
- Clicking a subsystem name in the table opens its tab.
- If the active subsystem disappears from the spec, the view returns to **Budget**.
- The Remove button changes the spec locally and redraws. It does not notify the model. The next request sends the updated spec, so the model sees the change then.
- The stack sketch does not draw added subsystems. It always shows the base stack.

## 6. Demo mode

Runs when no endpoint is saved. The header label reads "demo mode" instead of "connected". It exists so the interface can be tried without a model, and it is a simple keyword parser, not a replacement for one.

`demoParse(text, prev)` reads:

| Pattern | Effect |
|---|---|
| `3U`, `6U`, `12U` | Sets `form`. |
| spectro, methane, gas, multispectral, hyperspectral | Payload becomes `spectrometer`. |
| iot, sensor network, relay | Payload becomes `iot`. |
| wildfire, imag, camera, earth observation, photo | Payload becomes `camera`. |
| a number followed by `km` (3 to 4 digits) | Sets `altitude_km`. |
| "low earth" or "LEO" | Sets 500 km if no altitude is set yet. |
| a number followed by year or yr | Sets `years`. |

`demoSubsystems(text, spec)` handles parts:

- **Adding:** triggered by add, include, install, put in, need or want. It matches the text against `CATALOG` (GPS receiver, star tracker, cold-gas propulsion, reaction wheels, active thermal control, S-band transmitter, extra battery pack, magnetorquers, deployable antenna).
- **Not in the catalog:** if the text contains "subsystem" or "module", it creates a placeholder (0.5 kg, 2 W, $50k) named from the words before that term, with the estimate tag.
- **Typed numbers:** values like `0.8 kg`, `6 W`, `$200k` override the catalog or placeholder numbers and clear the estimate tag.
- **Removing:** remove, delete, drop or take out, plus a name that matches an existing part.

To add a part to the demo catalog, add an entry to `CATALOG` with a regex (`re`), `name`, `kg`, `w`, `cost` and `description`.

## 7. Layout and markup

```
.app
├─ header                  title, mode label, "New design", "Model settings"
└─ .main (two columns)
   ├─ section.chat         #log, #chips, form#form (input#input, #sendBtn)
   └─ section.dash
      ├─ #tabs             tab buttons (Budget + one per subsystem)
      ├─ #detail           subsystem tab content (hidden on Budget)
      └─ #overview         Budget tab content
         ├─ .stats         #massV/#massS/#massM, #powV/#powS/#powM, #costV/#costS
         ├─ table          #rows (body), #tMass/#tPow/#tCost (totals)
         ├─ #notes         flags list
         └─ svg#sketch     stack sketch
#settings                  modal: #endpoint, #authKey, #cancelS, #saveS
```

Below 900 px wide the columns stack, the chat gets 70% of the viewport height, and the page scrolls normally.

## 8. Script reference

All code is inside one immediately-invoked function, so nothing leaks to `window`.

| Function | Purpose |
|---|---|
| `computeBudget(spec)` | Budget engine. Returns totals, rows, states and flags. |
| `getSubs(spec)` | Cleans `spec.subsystems` into a uniform list. |
| `subIds()` | IDs of the current subsystems. Used to detect newly added ones. |
| `demoParse`, `demoSubsystems`, `demoReply` | Demo-mode parsing and the canned reply. |
| `callModel()` | POSTs to the endpoint. Returns `null` when no endpoint is set. |
| `send(text)` | Full turn: add message, call model or demo parser, compute, render. Ignores input while a request is running. |
| `render(b)` | Redraws the Budget view, then calls `renderTabs`. |
| `renderTabs(b)` | Draws the tab bar and shows either the overview or the subsystem tab. |
| `renderDetail(b, c)` | Draws one subsystem tab. |
| `drawSketch(b)` | Draws the stack sketch as SVG, scaled to the form factor. |
| `setMeter(id, ratio, state)` | Sets a progress bar width (capped at 100%) and its color. |
| `reset()` | Clears chat, spec and tabs, shows the greeting, and renders the default design. |
| `store(key, val)` | Safe `localStorage` read/write. Returns `""` if storage is blocked. |
| `esc(s)` | HTML-escapes text before it goes into `innerHTML`. Used for all model and user text. |
| `fmt(n)` | Rounds to one decimal. |

Event wiring is in the "Wiring" section at the bottom: one delegated click handler for tabs and remove buttons, plus handlers for the form, New design, and the settings modal. Escape closes the modal.

## 9. Styling

- **Themes:** light by default, dark through `prefers-color-scheme: dark`. Colors are CSS variables on `:root`, and the dark values are defined twice (the media query and `[data-theme="dark"]`), so a `data-theme` attribute on `<html>` forces a theme either way.
- **Tokens:** `--bg`, `--pane`, `--card`, `--line`, `--fg`, `--muted`, `--accent`, `--user-bg`, `--user-fg`, status colors `--ok`, `--warn`, `--bad`, and sketch colors `--solar`, `--payload`, `--avi`, `--batt` with matching `-line` variants.
- **Type:** IBM Plex Sans for text, IBM Plex Mono for the mode label and settings fields.
- **Status colors:** green, amber and red are used only for state (the meters, the power label, flags, the Remove button).
- **Motion:** the meters animate their width, and that is turned off under `prefers-reduced-motion`.

## 10. Common changes

| I want to... | Change |
|---|---|
| Use real parts data | Edit `FORMS`, `PAYLOADS`, `RADIO`, `OBC` and `CATALOG`. |
| Add a form factor | Add a key to `FORMS`. It then works in the spec and the sketch. |
| Add a payload type | Add a key to `PAYLOADS`, and a keyword rule in `demoParse` if you want demo mode to find it. |
| Change margin thresholds | Edit the `0.7` and `0.85` values in `computeBudget`. |
| Move the math to your server | Replace `computeBudget` with a call that returns the same object shape. |
| Change the starter design | Edit `DEFAULT_SPEC`. |
| Change the quick-reply chips | Edit the `SUGGESTIONS` array. |
