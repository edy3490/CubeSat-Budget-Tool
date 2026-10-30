# Part drawings

The 3D visualizer draws each satellite from ready-made part drawings. They come from two places, kept apart so it's always clear who drew what:

| Folder | Drawn by | How |
|---|---|---|
| `opus/drawings.py` | Claude Opus, in the coding session (not through the API) | Python, using the helpers at the top of the file. Real dimensions where known; estimates are marked `estimate=True`. Checked first. |
| `generated/*.json` | Sonnet or Haiku, at runtime | Saved automatically the first time the model draws a part the Opus set doesn't have. One file per part, reused from then on. Local to each machine: these files aren't in git. |

The model draws a part, and a file appears in `generated/`, in two cases:

- **A catalog part with no Opus drawing.** For example, the parts database gains a new radio. The file has `"kind": "catalog"`.
- **An extra invented for an unusual request,** such as a laser emitter for "a satellite with a laser beam." The file has `"kind": "extra"` and includes the estimated mass, power, purpose and the request that prompted it. Later requests can reuse it by name.

Each generated file records:
- `name`, `kind`, `vendor`, `purpose`;
- `mass_kg` and `power_w`, both estimates;
- `drawn_by` (which model) and `drawn_at`;
- `request`: what the user asked for;
- `size`, and `shapes` in the part's own frame.

## Reviewing generated parts (for Opus)

Generated drawings come from a smaller model and are rougher than the Opus set. To improve one:

1. Read the JSON: its `shapes`, `size` and `purpose`.
2. Redraw it properly with an `_add(...)` call in `opus/drawings.py`, using the same `name` and following the frame conventions at the top of that file.
3. Delete the JSON file. Opus drawings take precedence anyway, so the old file is simply ignored until it's removed.

`python -m visualizer --library` lists both sets and marks which is which.

## Frame conventions (both sets)

All measurements are in mm. Each part is drawn in its own frame, centered on its bounding box, with its own +z as "up":

- **Boards, ADCS, thrusters:** +z is the top of the stack.
- **Cameras:** the lens is on their own -z.
- **Panels:** cells are on +z, and the length runs along own y.
- **Antennas and patches:** +z points outward.

Shapes are axis-aligned boxes; a cylinder fills its box along `axis`. See `../placement.py` for how a part is turned and placed.
