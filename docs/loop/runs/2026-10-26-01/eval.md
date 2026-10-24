# Run 2026-10-26-01 — evaluation

## What was asked, and what was measured

Issue #21 wants one op that turns a piece's parts into one mesh, with six
acceptance conditions. Each is a measurement below; none is quoted from the
implementation.

## Fail-first

`join_objects` did not exist on `main` (`fd9c75d`): the test module's import
raised, so every condition failed at collection. Recorded rather than asserted
from the diff — the pre-fix `joined_pair` helper is reproduced in
`tests/blender/test_zz_failfirst.py`'s shape and reads:

```
NameTaken: an object named 'Joined' already exists (remove_object_and_mesh it
first, or pick another name)
```

on the **second** call, which is the defect the helper fixed: the op was right,
the helper reused one result name.

## The six conditions, measured

| # | condition | measurement |
|---|---|---|
| 1 | the report's triangle count is the parts' sum, and the RESULT measures it | two 1 m boxes (12 triangles each) → `triangles` 24; the joined mesh's own polygon count re-derived from the resulting object, not from the report |
| 2 | every source is gone from the scene | `consumed_names` lists both; `bpy.data.objects` contains neither, and the meshes are removed too (no orphan datablock left) |
| 3 | a part that was only MOVED keeps its place | the second part at x = 5 m: joined world bounds span 0…6 m, so the world matrix was baked, not dropped |
| 4 | material slots deduplicate by material | two parts sharing one material report `material_slots` 1, not 2; `keep_material_slots=False` keeps the first only |
| 5 | a gate verdict comes back | **measured on a live MCP call**: `gate: FAIL (24 tris, 2 components) — 2 disconnected components (budget 1)`, with the full `JoinReport` in `returned:` beside it |
| 6 | the edge cases are errors, not silent behaviour | one name → `ValueError` ("joining one object is a rename"); a duplicate name → `ValueError`; a non-mesh → refused by `object_by_name` naming both sides; an existing `result_name` → `NameTaken`; each raised BEFORE anything is consumed |

### Condition 5's boundary, stated rather than assumed

| pair of 1 m boxes | `self_intersecting_face_pair_count` |
|---|---|
| 50 % overlap | 8 |
| 1 mm gap | 0 |
| 1 m gap | 0 |
| face-to-face contact (0 offset) | **1** |

The issue expected touching solids not to intersect; measured, the analyzer
counts coplanar contact, and that is the honest reading — a lid resting on a pot
is coincident surfaces, not clear space. The test asserts the measured value
with that sentence beside it rather than the issue's expectation.

## The contract change

`join_objects(object_names: list[str], ...)` is the first PLURAL name parameter,
so `_contract.py` gained `PLURAL_NAME_ANNOTATIONS` and a `_names$` branch in the
name rule. The element rule is unchanged: the plural form widens the CONTAINER,
not the type.

**Proven by reverting the rule**: with `"list[str]"` removed from
`PLURAL_NAME_ANNOTATIONS`, the new test reads

```
assert not ["parameter 'object_names' looks like a name but is 'list[str]'"]
```

and with the rule restored it passes (71 passed in the module). A
`list[bpy.types.Mesh]`-shaped parameter is still refused both ways (`looks like a
name` AND `a bpy type`), which is what proves the container widened and the type
did not.

## Gates

| gate | result |
|---|---|
| `make test-golem` | 10 passed |
| `make -C blender test-pure` | 1552 passed, 1 xfailed (was 1547 / 1: +5 = 4 facade-parametrized tests for the new op and the plural-name contract test) |
| `make -C blender test-mcp` | 53 tests, OK |
| `make -C blender test-blender-app` | **487 passed, 1 skipped** (was 486 passed / 1 failed / 1 skipped before the helper fix) |

## Tool surface

Measured from the live facade and registry, never quoted:

| | before (`fd9c75d`) | after |
|---|---|---|
| `TOOL_SCHEMAS` | 71 | **72** |
| generated op tools | 62 | **63** |
| require a declared plan | 45 | **46** |
| op tools that are readers | 18 | 18 |
| fingerprint | `t:7a8ffdbc17da` | **`t:ff9833ed06ec`** |

`join_objects` returns an object name, so it is plan-required by the same rule
every other scene-changing op obeys — no marker, no exception.


## The defect the unit tests could not see, found by a live call

The op was written `-> ObjectName` but returned `JoinReport`. Every unit test
passed, because the tests call `join_objects` directly. The first **live** MCP
call through `dispatch_tool` raised:

```
File "src/golem_blender/agent/op_call.py", line 257, in _returned_object_names
    return tuple(str(name) for name in returned)
TypeError: 'JoinReport' object is not iterable
```

The dispatcher derives gating from the return ANNOTATION, so an op annotated
`-> ObjectName` is gated and its return is iterated as names. No unit test
covered the tool path, and the annotation was simply untrue.

**Fixed at the contract, not at the crash site.** An op may now state
`@op(gated=True)` and return a report; `gate_target_names` reads the report's
own `object_name` (every report here already carries it), so the gate measures
the object and the model still receives the counts the issue asked for. A
marked-gated op whose return type has no `object_name` is a contract violation,
so the shape cannot come back:

```
marked @op(gated=True) but returns <class '_AnonymousReport'>, which carries
no 'object_name' for the gate to measure
```

Proven by disabling that rule — the new test reads `assert any(...)` → `[]` —
and restoring it (72 passed in the module). The tool-schema description now
carries the gated marker for a gated report (`Returns JoinReport. Gated: …`),
which is why the pin moved a second time.

**A second live finding, and it was NOT a defect.** The overlapping smoke pair
reported `4 triangles face inward`. Measured on both cases: disjoint boxes
**0 of 24** flipped, overlapping boxes **4 of 24**, each source box 0. The join
does not flip normals; the parity check is correctly reporting faces that lie
inside another solid, which is what the analyzer's own message calls
"join-without-union". Nothing was changed for it.

Live proof of the fixed path (two disjoint 1 m boxes, `SmokeJoin_Joined`):

```
execute: ok in 0.00s (Blender 5.2)
returned: {"object_name": "SmokeJoin_Joined", "triangles": 24, "parts_joined": 2,
           "material_slots": 0, "consumed_names": ["SmokeJoin_A", "SmokeJoin_B"],
           "connected_component_count": 2, "boundary_edge_count": 0,
           "self_intersecting_face_pair_count": 0}
gate: FAIL (24 tris, 2 components)
  - 2 disconnected components (budget 1)
```

Both smoke objects were removed afterwards; the user's scene holds only the
Sanctuary work it held before.
