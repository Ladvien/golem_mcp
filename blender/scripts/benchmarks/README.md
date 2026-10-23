# The benchmark: recreating real PBR sets from a description

The lane is measured against **real sets**: ambientCG's, which are CC0 and
photoreal. The **recreation** gets only the material's own words - "bricks,
natural, stone", "beige, grain, knots, wood", "aged, black, brown, oxidized,
steel" - and never the truth's pixels. The pattern, the palette and every
channel come from those words; only the size comes from the truth's measured
feature count, because a description cannot say how big the stones are.

## The truth sets

Four sets under `~/mnt/codex_fs/game_assets/benchmarks/` (`/mnt/codex_fs/...`
on big), 159 distinct materials:

| set | materials | how it was chosen |
|---|---|---|
| `ambientcg` | 20 | hand-picked: brick, fabric, wood, ground, asphalt, tiles, concrete, metal, rock |
| `ambientcg_wide` | 87 | a wide sample across the kinds |
| `ambientcg_popular` | 47 | the kinds on the site's popular list |
| `ambientcg_top` | 60 | the site's own sixty most downloaded (`fetch_ambientcg_popular_list.py`: the API's `sort=popular` sorts by release date) |

Each `<set>/<asset>/` holds the truth's `albedo`, `normal_gl`, `roughness` and
`displacement`, and often an `ambient_occlusion` and a `metalness`.

## What is scored

- **The albedo** (`score_recreations.py`): brightness, contrast, feature scale
  and colour balance against the truth's, and the seam.
- **The whole set** (`score_pbr_channels.py`): the set the agent's layered-set
  tool writes, channel by channel - roughness mean and spread, metallic mean,
  normal strength (the mean tilt from flat, in degrees), AO mean and spread
  where the truth ships one, and the height's shape where it ships a
  displacement: its correlation with the albedo's luma and its skew. The two
  sets are different layouts, so a channel is compared by its statistics, not
  pixel by pixel.

A description that **composes** - a mossy rock, a rusted iron - is recreated
as the layered set builds it (`compose_from_description`: the base with its
overlay laid on it), in both scores.

## The current score

Over the 159, mean |log ratio| for the albedo's ratios and mean |error| for
the rest (run b21, at `c5edf97`):

| measure | score |
|---|---|
| albedo brightness | 0.161 |
| albedo contrast | 0.218 |
| albedo feature scale | 0.331 |
| albedo colour balance error | 0.1286 |
| roughness mean error | 0.0885 |
| roughness spread | 0.398 |
| normal strength | 0.427 |
| AO mean error / spread (74 with an AO) | 0.067 / 0.800 |
| height-luma correlation error / skew error | 0.318 / 0.902 |

Every run of a round, with what changed, is in `_evaluate/round<N>_plan.md`.

Two limits of the measures, known and left as they are:

- The feature scale is the autocorrelation's first zero crossing, and on a
  tile floor with near-flat faces and a hairline grout it reads the grout
  (Tiles107 13.0x, Tiles138 9.5x) - the look is checked on the close sheet.
- The size handed to the lane is the truth's measured feature count, and a
  tile floor's count is its faces' shading (Tiles107: 26 features, eight
  tiles), so a recreated floor has two to three times the truth's tiles.

## The order the scripts run in

```
python scripts/benchmarks/fetch_ambientcg_ground_truth.py
blender --background --factory-startup --python scripts/benchmarks/convert_ground_truth.py
blender --background --factory-startup --python scripts/benchmarks/measure_ground_truth.py
```

then, for each set, with `GOLEM_BENCH_ROOT=~/mnt/codex_fs/game_assets/benchmarks/<set>`:

```
blender --background --factory-startup --python scripts/benchmarks/recreate_from_descriptions.py
blender --background --factory-startup --python scripts/benchmarks/score_recreations.py
blender --background --factory-startup --python scripts/benchmarks/score_pbr_channels.py
```

The recreations land in `<set>/recreated/`, the whole sets in
`<set>/recreated_set/`, and the scores in `recreation_scores.json` and
`pbr_channel_scores.json`. The fetch is the only step that needs the network.
`refit_palette_tables.py` rewrites the palette's fitted tables from all four
sets.

**The writing and the measuring are separate processes, and that matters.**
Measuring inside the writing process reads the recreation into Blender, and
the next write's read inherits that datablock - so every file after the first
came out as the first one's pattern. Measured: ten files, all 467876 bytes,
all the same hash, the same seam for every one. The lane was never broken; the
measurement was.

## Looking at it

A number hides what a sheet shows - a paving routed to loose stones, a
camouflage on a metal, a soft band at every board's end - so every change is
looked at as well as scored:

```
python scripts/benchmarks/close_sheet.py --root <set> --out <dir> --rows 12
python scripts/benchmarks/channel_sheet.py --root <set> --out sheet.png Asset1 Asset2
```

The close sheet puts the truth and the recreation side by side, whole and
cropped at the truth's own pixel scale; the channel sheet puts the truth's
albedo, roughness and normal beside the set's. Run them with a Python that has
Pillow and NumPy; they need no Blender.
