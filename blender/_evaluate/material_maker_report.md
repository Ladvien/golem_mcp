# Material Maker: what to port to the golem_blender PBR lane

Source: `/tmp/material-maker` (HEAD `61bac4d`, MIT). Sparse checkout holds `addons/material_maker/nodes` and `material_maker/library` only. No network was used.

Tags: **[measured]** = run and observed here. **[quoted]** = read from the file, cited. **[INFERENCE]** = not observed, reasoned from the code.

## 0. Caveats that apply to everything below

- **Registry claim is wrong.** The plan says `material_maker/library/base.json` holds 328 entries. It holds **2** (`uniform`, `grayscale`). [measured]
- **Engine absent.** `material_maker/engine/` is not in the sparse clone. `$name` expansion and enum index-to-name mapping are only as visible in each `.mmg`. [quoted]
- **Hash is float32-dependent.** `rand(x) = fract(cos(mod(dot(x, vec2(13.9898, 8.141)), 3.14)) * 43758.5)` (`shader_functions.tres` L11-18). Results differ across GPUs; a NumPy port must use its own integer hash, not a bit-match. [quoted] + [INFERENCE]
- **Parameter defaults disagree between shader and saved instance.** Examples: `splatter` count 10 (shader) vs 25 (instance); `beehive` sx 2 vs 4; `fbm4` see §2. Port the shader default and tune. [quoted]
- **`smooth_curvature2.mmg` is invalid JSON** (trailing comma before `]` near line 373). Strict readers fail. Parse after stripping `,(\s*[\]\}])`. [measured]
- **`tones_map` shader defaults divide by zero.** Its shader defaults are `in_min = in_max = 0.5`, so `(out_max−out_min)/(in_max−in_min)` is undefined. The saved instance uses 0..1. [quoted] [measured]

### GORE / WOUND / TOON search: absent

A content grep over `addons/material_maker/nodes` and `material_maker/library` for `toon|cel shad|posteri|wound|gore|blood|outline|quantiz|floor(...)` plus a narrowed label/longdesc pass returned **no toon, cel, wound, gore or blood node** [measured]. Hits were only:
- outline/mask nodes (`binary_smooth.mmg` "Smoothes the outline of a mask", `edge_detect*.mmg`, `fill*.mmg`);
- Godot tilemap `outline: []` fields in `material*.mmg`.

The only look-related nodes are `quantize.mmg` (posterise) and `edge_detect.mmg` (outline). Both are trivial and are covered in §10.

---

## 1. Domain warping — `warp`, `warp2`, `multi_warp2`, `directional_warp`, `tex3d_warp`

**Priority: highest. This is our biggest gap.**

### 1a. `warp.mmg` (shader + graph) [quoted]

Instance function for slope (`warp.mmg` `shader_model.instance`):

```
vec2 $(name)_slope(vec2 uv, float epsilon) {
  return vec2($d(fract(uv+vec2(epsilon,0.0))) - $d(fract(uv-vec2(epsilon,0.0))),
              $d(fract(uv+vec2(0.0,epsilon))) - $d(fract(uv-vec2(0.0,epsilon))));
}
```

Output (`shader_model.outputs[0].rgba`):

```
$in#($uv + $amount*$strength_map($uv)*$(name_uv)_warp)
```

- Warp is an **unnormalised central difference** of the input `d`, not a gradient. The step is `amount · strength_map · Δd`, so its size scales with the height contrast of `d`, not with 1/(2ε).
- Defaults: `amount 0.1`, `eps 0.1`, `mode 0`. Mode 1 uses `slope·(1 − d(uv))`.

**NumPy recipe (single pass):**

```python
import numpy as np
from scipy.ndimage import map_coordinates  # or a wrapped bilinear sampler

def sample(img, uv):  # uv (H,W,2) in [0,1), periodic
    h, w = img.shape
    coords = np.stack([uv[...,1]*h, uv[...,0]*w])
    return map_coordinates(img, coords, order=1, mode='grid-wrap')

def warp(d, src, amount=0.1, eps=0.1, strength=None):
    H, W = d.shape
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    uv = np.stack([xs/W, ys/H], -1)
    f = lambda o: sample(d, np.mod(uv + o, 1.0))
    sx = f(np.array([eps,0])) - f(np.array([-eps,0]))
    sy = f(np.array([0,eps])) - f(np.array([0,-eps]))
    slope = np.stack([sx, sy], -1)
    s = np.ones((H,W,1)) if strength is None else strength[...,None]
    off = amount * s * slope
    return sample(src, np.mod(uv + off, 1.0))
```

`eps` is in UV units (0.1 is coarse). Measure the seam: `np.mod` on the sampled UV keeps the field periodic.

### 1b. `warp2.mmg` [quoted]

Fixed `e = (0.001, 0)`, output `in(uv + amount·warp(uv))`, `amount 0.05`. No `strength_map`. Use it only as a cheaper, tiny-step variant.

### 1c. `multi_warp2.mmg` — the iterated streamline warp [quoted]

Graph params: `param0 grid size 10`, `param1 intensity 4`, `param2 quality 15`, `param3 mode 0`. Inner `edge_detect_3_3_3` instance:

```
float dx = 1.0/$size;
int iterations = int(ceil($intensity * $quality)); iterations = max(1, iterations);
vec2 it_uv = uv; vec3 pt_value = $in(uv); vec3 rv = vec3(0.0);
for (int i=0; i<iterations; i++) {
    v = $heightmap(it_uv);
    slope = vec2($heightmap(it_uv+vec2(dx,0)) - v, $heightmap(it_uv+vec2(0,dx)) - v) * 2.0;
    it_uv += slope * $intensity * $intensity / float(iterations);
    rv += $mode;      // mode 0: min(in(it_uv), pt_value); blur: in(it_uv); max: max(...)
}
return rv / float(iterations);
```

This is **streamline advection** along the heightmap's slope: each pixel walks downhill (or uphill) and the result is the average of the source sampled along that path. The step per iteration is `slope · I²/N`, and `N = ceil(I·Q)`.

- With defaults `I=4, Q=15`, `N=60`, step `slope·16/60`.
- `dx = 1/size` with `size=10`: the slope is measured over a 0.1-domain baseline. This is coarse; a finer `dx` gives sharper flow.

**NumPy recipe (vectorised over pixels):**

```python
def multi_warp(height, src, size=10, intensity=4.0, quality=15, mode='min'):
    H, W = height.shape
    dx = 1.0/size
    N = max(1, int(np.ceil(intensity*quality)))
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    uv = np.stack([xs/W, ys/H], -1)          # (H,W,2)
    it = uv.copy()
    pt = sample(src, uv)                     # (H,W,C)
    rv = np.zeros_like(pt)
    h = lambda p: sample(height, np.mod(p,1.0))
    for _ in range(N):
        v = h(it)
        sx = (h(it + [dx,0]) - v) * 2.0
        sy = (h(it + [0,dx]) - v) * 2.0
        slope = np.stack([sx, sy], -1)
        it = it + slope * intensity**2 / N
        s = sample(src, np.mod(it,1.0))
        rv += np.minimum(s, pt) if mode=='min' else (np.maximum(s, pt) if mode=='max' else s)
    return rv / N
```

Cost is `N = I·Q` interpolations per pixel (60 here). At 1024² that is 60 gathers of 1M pixels; acceptable in numpy.

### 1d. `directional_warp.mmg` [quoted]

`uv + (cos a, sin a)·(strengthmap(uv) − 0.5)·strength`, with `a = angle · anglemap(uv) · π/180`. Defaults `angle 0` (±180), `strength 0.1` (±1). Use it to make grain or streaks bend along a field direction (e.g., wood grain). Port directly.

### 1e. `tex3d_warp.mmg` [quoted]

3D version of `warp`: defaults `amount 0.0`, `eps 0.0`, `mode 0.0`. **Not useful for us now**, because the lane is 2D. Revisit only if the lane moves to 3D volumes.

**Port status:** `warp` and `multi_warp2` are direct ports of MIT maths. The formulas above are copied from the source. [quoted]. Implementing them is the single highest-value change: our wood fibre and pebbles have no domain warp.

---

## 2. fBm variants — `fbm4`, `fbm_variations`, `shard_fbm`, `sdf3d_fbm2`

### 2a. `fbm4.mmg` — what it does differently from plain fBm [quoted + measured]

Signature: `fbm_2d_$noise(coord, size, folds, octaves, persistence, lacunarity, offset, seed)`.

Per octave:
```
noise = *_noise_2d(coord*size, size, offset, seed+i);   // periodic on the lattice modulo size
for each fold: noise = abs(2*noise - 1);                 // ridged fold
value += noise*scale; norm += scale;
size *= lacunarity; scale *= persistence;
return value / norm;
```

- **Periodic**: the lattice is wrapped with `mod(o, size)` on corner indices. That is why it tiles exactly [quoted].
- **Fold** `abs(2n−1)` makes ridges (the crease look). `folds 0` disables it.
- **Two default sets** [quoted]: instance `parameters`: `folds 0, iterations 5, noise 9, offset 0, persistence 0.5, scale_x 2, scale_y 2`. Shader `parameters`: `scale_x/y 4, folds 0, iterations 3, persistence 0.5, lacunarity 2.0, offset 0`.
- `noise 9` is the enum index for the underlying noise. Its name is `[INFERENCE]` because the `values` array is in an engine file we don't have.

**Value noise (`value_noise_2d`) — measured.** Corner values are `sin(p·2π + offset·2π)/2 + 0.5`. Measured corner distribution: **mean 0.5004, std 0.3529, min 0.0000, max 1.0000** [measured]. Theory for an arcsine on [0,1] gives std 0.3536. So corners pile at 0 and 1. A NumPy port must reproduce this, or the histogram changes. A uniform integer hash gives std 0.2887 and a different look. Choose deliberately.

**Fade** (quoted in `value_noise_2d`): `t = f³(f(6f−15)+10)` (quintic; zero first and second derivative at lattice edges).

**Perlin (`fbm4` perlin branch)**: `rand2` gradients with the same quintic fade, returns `0.5 + mix`. **Simplex** returns `0.5 + 5.5·n` (quoted).

**Port status:** the periodic value-noise fBm is **already ported** (`pbr/noise.py`, per the memory summary). The only open item is the corner distribution (above). Keep the sine-based corners only if a benchmark prefers them.

### 2b. `fbm_variations.mmg` [quoted]

Params: `iterations 10, persistance 0.5, randomize True, variable 0.0`. Per iteration: `$in.variation(uv, seedvar, var)`; `var.$variable *= 2`; `seedvar = rand(vec2(seedvar, sum))` when randomized. Returns `v/sum`.

It is a **meta-fBm over an upstream node**, not a noise generator. **Not useful for us**, because our lane has no upstream variation graph to feed it. [INFERENCE]

### 2c. `shard_fbm.mmg` — fracture-like fBm [quoted; look NOT rendered]

ENDESGA-style (Shadertoy, adapted). Hash `hash(vec3)`: `dot(p, vec3(127.1,311.7,74.7))` then `fract(sin(p)·43758.5453)`. Neighbourhood is **3 × 5 × 5**.

Per cell:
```
w = exp2(-6.283185 * |r|²)               // Gaussian-like weight, r = offset to feature
s = sharpness * dot(r, hash(io + (11,31,47)) - 0.5)
v += w * s / sqrt(1 + s²)                // soft-clipped signed distance
t += w
return (v/t) * 0.5 + 0.5
```

Defaults: `sharp 0.7, sx 7, sy 7, folds 0, iter 4, per 0.5, off 0`.

The `s/√(1+s²)` term is a soft sign that makes sharp ridges along cell borders. That is the crevice-network look. **Fracture look is [INFERENCE]: not rendered.** Measure before adopting. The cost is 75 neighbours per pixel per octave, which is heavy in numpy.

### 2d. `sdf3d_fbm2.mmg` — IQ fbmsdf [quoted]

Per octave: a sphere SDF at each of 8 cube corners, radius `0.5·rand31(i + c + seed)`, combined with min over corners. Then `n = s·sdBase(p)`. Mode 0 (add) and mode 1 (subtract, default) use `smax`/`smin` with `smoothness·s`. Between octaves `p = mat3(...)·p` and `s *= 0.5`. Defaults `mode 1, iterations 5, smoothness 0.3, scaling 0`. Input `distance` default `length($uv) − .45`.

**Not useful for us**, because it is a 3D SDF carve for volumes. Our textures are 2D height/colour maps. [INFERENCE]

---

## 3. Cellular and organic masks — `beehive`, `beehive2`, `crystal`, `circle_map`

### 3a. `beehive.mmg` [quoted]
- `beehive_dist(p) = max(dot(|p|, s·0.5), |p.x|)`, `s = (1, √3)`. A hexagonal distance.
- `beehive_center` picks the nearer of two hex lattices.
- Output `1 − 2·beehive_dist(center.xy)`; colour `rand3(fract(center.zw/(sx,sy)) + seed)`.
- Defaults `sx 2, sy 2` (shader) vs `sx 4, sy 4` (saved).
- Longdesc: "Draws a grayscale hexagonal tiles pattern".

**Use:** hex tiles only. For the `tiles` benchmark category, [INFERENCE] a hex option might help hex-tile sets; not shown to help the others. Niche.

### 3b. `beehive2.mmg` [quoted]
Same centre function plus `fill = fract(uv − center − (0.5, 0.577))`, quantised `floor(··16384)/16384`. Niche (fill ID texture).

### 3c. `crystal.mmg` (graph) [quoted; look NOT rendered]
Wiring (measured from the `.mmg` connections):
- `voronoi` (seed 0) → `math_2 = sqrt(1 − v1²)` (op 19)
- `voronoi_2` (seed 1998774700) → `math_3 = sqrt(1 − v2²)` (op 19)
- `math = min(m2, m3)` (op 13), `math_4 = max(m2, m3)` (op 14)
- `math_5 = math_4 − math` (op 1); `math_6 = math_5 / math_4` (op 3); `math_7 = math_6 · 1.45` (op 2)
- Output `= 1.45·(max − min)/max`.

Each Voronoi has `scale 16, randomness 1, stretch 0.85, intensity 1`. So the crystal is a **relative edge contrast between two independent Voronoi fields**. The look is [INFERENCE]: not rendered. NumPy: take F1 of two Voronoi fields `m_i = sqrt(1 − v_i²)` (note: `v_i` is the voronoi nodes output, already in [0,1]), then `1.45·(max−min)/max`.

**Use:** niche. Fractured rock or crystal facets might use it. Low priority.

### 3d. `circle_map.mmg` [quoted]
Polar remap: `in#(vec2(fract(repeat·atan(uv.y−0.5, uv.x−0.5)·0.15915494), min(0.99999, 2/radius·length(uv−0.5))))`. Params `radius 1 (0–1.5)`, `repeat 1 (0–16)`.

**Use:** a polar remap for radial patterns. **Not useful for us** for the benchmark categories (brick, fabric, wood, ground, asphalt, tiles, concrete, metal, rock). [INFERENCE]

### 3e. Underlying cell noises (for context) [quoted]
- `cellular_noise_2d` (L154): F1 over 3×3 neighbours; feature point `0.5 + 0.25·sin(offset·2π + 2π·node)`, confined to the middle half of the cell.
- `cellular5` (L302): Chebyshev `max(|dx|, |dy|)`.
- `voronoise_noise_2d` (L455): 5×5, `w = 1 − smoothstep(0, 1.414, |d|)`, returns `Σ(o.z·w)/Σw`, jitter `o.xy += 0.25·sin(offset·2π + 2π·o.xy)`.

---

## 4. Scratches — `scratches2.mmg` (new primitive; the lane has none)

[quoted]

```
scratch(uv, size, waviness, angle, randomness, seed):
  cell = floor(1/size.x)
  r1, r2 = per-cell randoms
  a = 2π*(angle + (r1.x-0.5)*randomness)        // rotation
  uv.y += 0.5*waviness*cos(2*uv.x + 2π*r2.y)    // waviness
  border = min(border.x, border.y) * (1 - uv.x²) * max(0, 1 - 1000*uv.y²)
scratches(): max over `layers`, returns v*2
```

Defaults (shader): `length 0.25, width 0.5, layers 4, waviness 0.5, angle 0, randomness 0.5`. Saved instance: `layers 5, waviness 0.3, width 0.4, randomness 0.3`. Angle is ±180, divided by 360 in `scratches()`.

**NumPy recipe:** per layer, compute the cell grid, rotate uv by `a`, apply the waviness shift, evaluate the border product, take the max across layers, double. Vectorise over cells with a per-cell random table. Two-cell-per-pixel, cheap.

**Use for us:** scratches or abrasion on `metal_field` and `ground` (worn surfaces). **Port.** The maths is a few lines. An older implementation `scratches.mmg` (`old_scratches`, `length 0.25, width 0.5, layers 4, waviness 0.5, angle 0, randomness 0.5`) is superseded; port `scratches2` only.

---

## 5. Curvature — `smooth_curvature`, `smooth_curvature2`, `normal2height`, `normal2height_simple`

### 5a. `smooth_curvature.mmg` (graph) [quoted]
`normal_map(12)` → `buffer_2`. Four `598_*` shaders read `buffer_2` at radii 1, 2, 4, 8, 16 (`598_3`, `598_2`, `598_4`, `598_5`, `598_6`), `size 12`, `amount 1.0`. Each:

```
rv += in(uv + e·(dx,dy)).xy · cos(atan(dy,dx) − (0, 0.5)π) / |(dx,dy)|    // over a square of radius `pixels`
return amount·rv/pixels + 0.5
```

This is a **directional emboss of the normal map**: an orientation-weighted derivative, not a Laplacian. Each feeds `fast_blur` (11, 5, 8, 16, 34), `param2 2`, `param3 1`. Blend chain (all Overlay `blend_type 4`, `amount 1.0`): `blend(fb4, fb5)` → `blend_2(fb3, blend)` → `blend_3(fb2, blend_2)` → `blend_4(fb6, blend_3)` → `invert`.

The curvature-like look is [INFERENCE]: not rendered.

**NumPy recipe:** for each radius r in {1,2,4,8,16}, sum over the square of radius r of `n_xy(p+d) · cos(atan2(dy,dx) − π/2·(0,0.5)) / |d|`, divide by r, add 0.5. Blur each with a Gaussian of the listed radius, Overlay-blend the five, invert.

### 5b. `smooth_curvature2.mmg` (graph; JSON needs repair) [quoted + measured]
Params `param0 10, param1 4, param2 1, param3 1, param4 1`. Chain: `buffer` (lod 0, size 10) → `switch` → `598` → `buffer_2` → `switch_2` → outputs. The `598` shader's output is `$(name)_curvature($uv, $quality, $strength, $radius)`, instance:

```
float $(name)_curve(vec2 p, vec2 o) {
  float a = $in(p+o), b = $in(p-o);
  float c = $in(p+o*vec2(1,-1)), d = $in(p-o*vec2(1,-1));
  return -a - b - c - d;
}
float $(name)_curvature_map(vec2 p, float r, float q) {
  float s = r/q; float H = $in(p)*4.0; float v = 0.0;
  for ox,oy in [0,q): o = (ox,oy); c = curve(p, o*s);
      v += (H + c) * ((r - length(o*s)) / r);
  return v/(q*q);
}
float $(name)_curvature(uv, quality, strength, radius) {
  float c = curvature_map(uv, 0.050*radius, quality)*strength/radius;
  return 0.5 + c;
}
```

This is a **discrete second difference** (`4·H − Σ neighbours`, the 5-point Laplacian when `o` is unit) averaged over a cone-weighted set of offsets. `(H + c)` equals `4·in(p) − (in(p±o) + in(p±o·diag))`, a Laplacian at scale `o`. So `smooth_curvature2` is a **curvature (Laplacian) map**, unlike `smooth_curvature` (emboss). That makes it the one we would use for edge wear and cavity masks.

**NumPy recipe:**
```python
def curvature(h, radius=1.0, quality=4, strength=1.0):
    r = 0.05*radius; s = r/quality; H = 4*h; v = np.zeros_like(h)
    for ox in range(quality):
        for oy in range(quality):
            o = np.array([ox, oy])*s
            a = shift(h, +o); b = shift(h, -o)
            c = shift(h, +o*[1,-1]); d = shift(h, -o*[1,-1])
            cv = -a - b - c - d
            v += (H + cv) * ((r - np.linalg.norm(o)) / r)
    v /= quality*quality
    return 0.5 + v*strength/radius
```
`shift` = periodic sampling of `h` at a fractional offset (bilinear, wrapped). Cost: `quality²` samples × 4 per pixel (64 for quality 4). Cheap.

Parameter note: the `598` shader defaults are `quality 4, radius 1, strength 1`; the saved instance is `param0 10, param1 4, param2 1, param3 1`. Use shader defaults.

### 5c. `normal2height_simple.mmg` (shader, instance) [quoted]
`find_height(uv, center, center_height, steps)`: along the straight path from `center` to `uv`, `height += scale·dot((uv − center)/steps, nm.xy − 0.5)`. Then `h = 0.5·h + 0.25·(hx + hy)`, averaging the direct path with two L-shaped paths through `(c.x, uv.y)` and `(uv.x, c.y)`. Params `size 10, center_height 0.5, scale 20` (saved `scale 25`).

This is a **line integral of the gradient** derived from the normal. It recovers height up to a constant. [quoted]

### 5d. `normal2height.mmg` (graph) [quoted]
Params `param0 25, param1 0.5, param2 10`. Chain: `gen_inputs` → `normal2height_simple_2` → `buffer` → `normal2height_base` (`h`) and `edge_detect_1`.

`edge_detect_1` (`amount 25, size 10`): `rv *= size·40/amount/128`; returns `length(0.5 + 0.5·normalize(rv, −1) − n(uv))`, a per-pixel **normal mismatch** `q`.

`normal2height_base` iterates an 11×11 window (`dx, dy ∈ [−5, 5]`):

```
p = uv + d/size
w = max(1 − 50·q(p), 0.01) / (1 + |d|²)
h −= scale · dot(d/size, nm(p).xy − 0.5)
return Σ w·h / Σ w
```

This is a **weighted relaxation** that suppresses integration across edges (large `q`). It is the robust version of `normal2height_simple`.

**Use:** only if a normal map arrives without its height. Our bakes go height→normal, not the reverse, so this is an inverse we do not need yet. [INFERENCE]. Port `normal2height_simple` for the line integral; `normal2height` only if an AI-generated normal map must be turned into height.

---

## 6. Splatter — `splatter`, `splatter_color`, `circle_splatter`, `circle_splatter_color`

### 6a. `splatter.mmg` (instance lines 7-41) [quoted]

```
for i < count:
    seed = rand2(seed);            rc1 = rand3(seed);
    pos  = fract(seed + 0.5);      mask = $mask(pos);
    if mask <= 0.01: continue;
    pv = fract(uv − seed) − 0.5;
    angle = (seed.x*2 − 1) · rotate · π/180;   rotate pv by angle
    pv *= (seed.y − 0.5)*2*scale + 1;
    pv /= (scale_x, scale_y);
    pv += 0.5;
    if pv outside [0,1]²: continue;            // no wrap
    v = in.variation(pv) · mask · (1 − value·seed.x);
    keep max; track rc, instance_uv, center_uv via step
```

Placement is **uniform random via hash, not Poisson disc** [quoted]. Rejection on `pv` leaving [0,1]² means splats do not wrap across the tile edge: a splat cut by the edge is dropped, not continued. [quoted]

Defaults (shader): `count 10, scale_x/y 1, rotate 0, scale 0, value 0.5`. Saved: `count 25, value 0`.

**NumPy recipe (vectorised):**
```python
def splatter(src, mask, count=25, scale=(1,1), rotate=0.0, scale_jit=0.0, value=0.0, rng=np.random.default_rng(0)):
    H, W = src.shape[:2]
    out = np.zeros_like(src); # (H,W)
    ys, xs = np.mgrid[0:H,0:W].astype(np.float32); uv = np.stack([xs/W, ys/H], -1)
    for _ in range(count):
        seed = rng.random(2)
        pos = np.mod(seed + 0.5, 1.0); m = sample(mask, pos)
        if m <= 0.01: continue
        ang = (seed[0]*2-1)*rotate*np.pi/180
        pv = np.mod(uv - seed, 1.0) - 0.5
        c, s = np.cos(ang), np.sin(ang)
        pv = np.stack([c*pv[...,0] - s*pv[...,1], s*pv[...,0] + c*pv[...,1]], -1)
        pv *= (seed[1]-0.5)*2*scale_jit + 1
        pv /= np.array(scale); pv += 0.5
        inside = np.all((pv >= 0) & (pv <= 1), -1)
        v = sample(src, pv) * m * (1 - value*seed[0])
        out = np.where(inside[...,None], np.maximum(out, v), out)
    return out
```

Use a seeded RNG, not the GPU hash. The hash is float32-dependent [quoted].

**Use for us:** debris, rubble, dirt, leaves, spots. The benchmark has `rock`, `ground`, `asphalt`, `concrete`. **Port** as a cheap rejection placement for ground and asphalt debris. Note the no-wrap caveat: a tileable output needs the splat to be allowed to wrap, which this source does not do. [INFERENCE]

### 6b. `splatter_color` [quoted]
Same placement; composite `c = mix(c, n, na)`, `na = n.a·mask·(1 − opacity·seed.x)`, `opacity 0.5`. Use the alpha composite for coloured stains rather than height.

### 6c. `circle_splatter.mmg` (instance lines 87-124) [quoted]
Deterministic, not random:
```
a = −π/2 + 2π·i·rings/count
rings_distance = ceil((i+1)·rings/count)/rings
spiral_distance = (i+1)/count
pos = radius · mix(rings_distance, spiral_distance, spiral) · (cos a, sin a)
angle includes (a + π/2)·i_rotate
pv /= mix(1, (i+1)/(count+1), i_scale)
max-combine
```
Defaults `count 10, rings 1, radius 0.25, spiral 0, value 0.5`. Saved `count 20, rings 2, radius 0.4`.

**Use:** ring or spiral placement (for example, a bullet impact pattern). **Not useful for us** for the benchmark sets. [INFERENCE]

### 6d. `circle_splatter_color` [quoted]
Alpha composite, `opacity` default 0.5, rejects outside [0,1].

---

## 7. Tones — `tones.mmg`, `tones_map.mmg`, `tex3d_tones_map.mmg`, `auto_tones.mmg`, `quantize.mmg`, `tones_range`, `tones_step`

### 7a. `tones.mmg` — three-point levels with piecewise-linear gamma [quoted]
`adjust_levels` (`shader_model.global`):
```
color = clamp((color − in_min)/(in_max − in_min), 0, 1)
in_mid = (in_mid − in_min)/(in_max − in_min)
dark = step(in_mid, color)
color = 0.5 · mix(color/in_mid, 1 + (color − in_mid)/(1 − in_mid), dark)
return out_min + color·(out_max − out_min)
```
Saved parameters: `in_min 0, in_mid 0.498, in_max 1`, `out_min (0,0,0,1)`, `out_max 1` (colour type in the file).

**NumPy:**
```python
def levels(c, in_min=0, in_mid=0.5, in_max=1, out_min=0, out_max=1):
    c = np.clip((c - in_min)/(in_max - in_min), 0, 1)
    m = (in_mid - in_min)/(in_max - in_min)
    dark = c >= m
    c = 0.5*np.where(dark, 1 + (c-m)/(1-m), c/m)
    return out_min + c*(out_max - out_min)
```
Note the `0.5·` factor: the mid-grey is pinned at 0.5 whatever `in_mid` is [quoted]. Three-point levels are a trivial port and useful for pinning the palette's mid.

### 7b. `tones_map.mmg` — linear remap, no clamp [quoted + measured]
Output: `vec4(vec3(out_min) + (in.rgb − vec3(in_min))·vec3((out_max − out_min)/(in_max − in_min)), in.a)`. Shader defaults `in_min 0.5, in_max 0.5, out_min 1, out_max 0.5` (`in_max == in_min` divides by zero). Saved: `in 0..1, out 0..1`. No clamp.

### 7c. `tex3d_tones_map.mmg` [quoted]
Shader with empty `CODE`/`INST`; the 3D version. Not used for 2D.

### 7d. `quantize.mmg` — posterise [quoted + measured]
Output: `vec4(floor($in#($uv).rgb·$steps)/$steps, $in#($uv).a)`. Parameter `steps` default `4`, range 2–32 [quoted].

**NumPy:** `np.floor(rgb*steps)/steps`. Note `floor(1.0·steps)/steps = 1.0` only when `rgb = 1.0`; values at exactly 1.0 are not clamped below 1. [INFERENCE]

**Use:** posterisation, a toon-like step look. Trivial. Not needed for the PBR benchmark, but it is a one-line port if a stylised output appears.

### 7e. `tones_range.mmg`, `tones_step.mmg` [quoted]
- `tones_range`: `step = clamp((in − value)/max(1e-4, width) + 0.5, 0, 1)`; `false = clamp(min(step, 1−step)·2/(1−contrast), 0, 1)`; `true = 1 − false`. Defaults `value 0.5, width 0.25, contrast 0.5, invert False`. A band-pass mask around `value`.
- `tones_step`: per channel `false = clamp((in − value)/max(1e-4, width) + 0.5, 0, 1)`, `true = 1 − false`. Defaults `value 0.5, width 1`. A soft threshold.

**Use:** a height-band mask (for example, "dirt only in low areas"). Port `tones_step` if a mask is needed. Trivial.

### 7f. `auto_tones.mmg` [quoted]
Graph (`size 11`): `tones_map` + `decompose` + `combine` + `iterate_buffer` + node `14423`. Auto-derives levels from a histogram. The UI (`tones.gd`) sets `in_min`/`in_mid`/`in_max` from the histogram peak; this is Godot UI, not maths.

**Use:** not needed. Our lane already calibrates colour from the description (`palette.py`).

**Port status (tones overall):** `adjust_levels` is a 6-line port. Worth doing only for the mid-pin. Nothing else here moves the benchmark.

---

## 8. The exporter — `material_maker/nodes/material_export/` and `material.mmg`

### 8a. Structure [quoted]
`material.mmg` `type: material_export`. Top-level keys: `export, name, node_position, parameters, seed_int, shader_model, type`. `shader_model` keys: `shortdesc, longdesc, code, exports, global, inputs, instance, name, outputs, parameters, preview_shader`. The exporter's `export` top level is empty (`{}`). Target definitions live in `shader_model.exports`. [measured]

### 8b. The 14 output expressions [quoted]

| idx | type | expression |
|---|---|---|
| 0 | rgba | `vec4(albedo_tex, opacity_tex)` |
| 1 | rgb | `vec3(ao_tex, roughness_tex, metallic_tex)` |
| 2 | rgb | `emission_tex` |
| 3 | rgb | `normal_tex·vec3(−1,1,−1) + vec3(1,0,1)` |
| 4 | f | `clamp(depth_tex, 0, 1)` |
| 5 | f | `sss_tex` |
| 6 | rgba | `vec4(metallic_tex, 1 − roughness_tex)` |
| 7 | rgb | `normal_tex·vec3(−1,1,−1) + vec3(1,0,1)` |
| 8 | f | `1 − depth_tex` |
| 9 | f | `ao_tex` |
| 10 | rgb | `normal_tex·vec3(−1) + vec3(1)` |
| 11 | rgba | `vec4(metallic_tex, ao_tex, 1, 1 − roughness_tex)` |
| 12 | f | `metallic_tex` |
| 13 | f | `roughness_tex` |

Params: `albedo_color`, `metallic 1`, `roughness 1`, `emission_energy 1`, `normal 1`, `ao 1`, `depth_scale 0.5`, `flags_transparent False`, `sss 0`, `size 11`. [quoted]

### 8c. Target mapping — resolved from `shader_model.exports` [quoted]

The mapping that was `[INFERENCE]` in the prior draft is now read from the file.

**Blender target** (`export_extension tres`):
- `albedo` → output 0 → `_albedo.png`
- `roughness` → output 13 → `_rough.exr`
- `metallic` → output 12 → `_metal.exr`
- `normal` → output 7 → `_normal.png`
- `depth` → output 8 (`1 − depth`) → `_displace.exr`
- `sss` → output 5 → `_sss.exr`
- `emission` → output 2 → `_emission.png`
- `ao` → output 9 → `_occlusion.exr`

**GLTF target** (`export_extension gltf`):
- `albedo` → output 0 → `_albedo.png`
- **ORM** → output 1 → `_orm.png`, conditioned on `ao|roughness|metallic` being connected. Channels: `vec3(ao, roughness, metallic)` = **R = AO, G = roughness, B = metallic**.
- `emission` → output 2
- `normal` → output 3 → `_normal.png`

### 8d. What this means for us [quoted + measured]
- **ORM packing matches the golem convention exactly**: R=AO, G=roughness, B=metallic (`T_Plaster_ORM.png`). No change needed.
- **Height is written** (not omitted). The Blender target writes `1 − depth` (output 8) as `_displace.exr`. The GLTF target writes no height. So "does it write a height map?" is **yes, only as `1 − depth` in the Blender target**. Our lane has no height export; the displacement convention would be `1 − depth` if we add one. [quoted]
- **Normal sign**: outputs 3 and 7 flip X and Z (`·vec3(−1,1,−1)+vec3(1,0,1)`). Output 10 flips all three axes. Our bake's normal convention must be checked against this; the flip is the OpenGL/DirectX convention difference. [INFERENCE: which convention golem uses is not verified here]
- **Packed alt**: output 11 `vec4(metallic, ao, 1, 1−roughness)` is a Godot-oriented pack. Not needed.
- Parameters `depth_scale 0.5`, `sss 0` are as above.

**Port status:** the exporter is a reference for naming and packing, not code to port. The ORM convention is already correct. Confirm our normal sign against output 3 before shipping.

---

## 9. GORE / WOUND

**Absent from this repo** [measured]. Content grep found no `gore`, `wound`, `blood`, or `wound` node. Only outline and mask helpers, and Godot tilemap fields. Nothing portable for GORE/WOUND.

## 10. STYLIZED / TOON

**Absent as a look** [measured]. Two nodes are adjacent:
- `quantize.mmg`: `floor(rgb·steps)/steps`, steps 2–32, default 4. A posteriser. [quoted]. Trivial port.
- `edge_detect.mmg`: `clamp(100·(fct − threshold), 0, 1)` with `fct = Σ length(in(uv±e) − ref)` over 8 neighbours, `size 9, width 1, threshold 0.5`. An outline. [quoted]

Both are one to five lines of NumPy. We do not need the repo for them. Do not port them as a "toon" feature; there is no toon shading in Material Maker.

---

## Ranked implementation list

1. **Domain warp (`multi_warp2` for organic flow; `warp` for simple displacement; `directional_warp` for grain).** Largest gap: wood fibre and pebbles have no warp. Direct MIT maths, §1. Measure seam and cost.
2. **Curvature (`smooth_curvature2`) for edge wear and cavity masks.** A Laplacian, cheap (`quality²·4` samples), and gives a real wear/cavity mask our bakes lack. §5b.
3. **Exact bisector border (`voronoi` port 1 "Borders").** `md = min(dot(0.5·(mr+r)·stretch, normalize((r−mr)·stretch)))` over 5×5 gives the exact distance to the joint. Our `cell_and_edge` uses F2−F1, which is not a distance, so joint width varies with spacing. §3e and the voronoi shader. Measure before adopting.
4. **Scratches (`scratches2`).** No abrasion primitive exists. A few lines of numpy, §4. Metal and ground.
5. **Splatter (`splatter` placement, with the no-wrap caveat).** Cheap debris/rubble mask for ground, asphalt, concrete. §6a. Needs a wrap fix before it tiles.
6. **Periodic value-noise fBm (`fbm4`).** Already ported (`pbr/noise.py`). Remaining item: decide the corner distribution (sine-arcsine, measured std 0.3529, vs uniform 0.2887). §2a.
7. **Height from normal (`normal2height_simple`, line integral).** Only if an AI normal map must be converted. §5c. Low priority.
8. **Three-point levels (`tones.mmg` `adjust_levels`).** Trivial port, only to pin mid-grey. §7a.
9. **Crystal (`crystal`).** Niche fracture contrast, look not rendered. §3c.
10. **Beehive, circle_map, shard_fbm, sdf3d_fbm2, fbm_variations, tex3d_warp.** Not useful for the benchmark categories, or 3D/meta, or unverified look. §2, §3, §1e.

**Not-to-port list:** `fbm_variations` (needs an upstream graph), `sdf3d_fbm2` (3D), `tex3d_*` (3D), `circle_map`, `circle_splatter` (deterministic rings, not organic), `auto_tones` (histogram UI), `tones.gd` / `material_export.gd` (Godot UI).

## Does Material Maker have anything we should port?

**Yes, in three places:** the domain warp (`multi_warp2`, `warp`), the curvature Laplacian (`smooth_curvature2`), and the scratch primitive (`scratches2`). The exact bisector border (`voronoi` port 1) is a fourth, to measure. Periodic value-noise fBm is already ported. The exporter's ORM packing already matches golem. Material Maker has **nothing for GORE/WOUND**, and for **TOON** only the trivial posteriser and outline nodes described in §10.

## Summary of what was verified and what was not

- Verified by measurement: value-noise corner distribution (mean 0.5004, std 0.3529, min 0, max 1); registry has 2 entries; no toon/gore/wound node exists; exporter output-to-target mapping (read from `shader_model.exports`).
- Verified by quoting the source: all formulas in §1–§8 as cited.
- Not verified (`[INFERENCE]`): crystal, shard_fbm and smooth_curvature visual looks (not rendered); fbm4 noise enum name for index 9; normal sign convention used by golem; whether splatter should wrap.
