use macroquad::prelude::*;

const BLOCK_SIZE: f32 = 4.0;
const PARTICLES_PER_LAYER: usize = 60;

// Vertical gradient bands: (normalized_y, (r, g, b))
const BAND_COLORS: &[(f32, (f32, f32, f32))] = &[
    (0.00, (0.70, 0.38, 0.16)),
    (0.25, (0.74, 0.47, 0.18)),
    (0.50, (0.63, 0.32, 0.14)),
    (0.75, (0.77, 0.52, 0.20)),
    (1.00, (0.56, 0.25, 0.09)),
];

const SCROLL_SPEED: f32 = 6.0; // blocks/sec horizontal gradient drift
const LAYER_SPEEDS:  [f32; 3] = [0.4, 1.0, 1.8];
const LAYER_ALPHAS:  [f32; 3] = [0.45, 0.65, 0.85];
const LAYER_SIZES:   [(f32, f32); 3] = [(1.0, 1.0), (1.0, 2.0), (2.0, 3.0)];

// Per-layer direction archetype: (vx_sign, vy_sign)
// 0 = left→right (flat), 1 = upper-left→lower-right, 2 = lower-left→upper-right
const LAYER_DIRS: [(f32, f32); 3] = [(1.0, 0.0), (1.0, 1.0), (1.0, -1.0)];

// Spice particle colors (warm light tones against the orange gas)
const SPICE_COLORS: [(f32, f32, f32); 5] = [
    (0.96, 0.92, 0.72), // pale cream yellow
    (0.98, 0.88, 0.78), // warm cream
    (0.94, 0.80, 0.70), // light peach
    (0.99, 0.95, 0.85), // near white
    (0.95, 0.82, 0.75), // light rose
];

struct Particle {
    nx: f32, // normalized x in [0, 1)
    ny: f32, // normalized y in [0, 1)
    vx: f32, // pixels/sec at reference width 1280
    vy: f32, // pixels/sec at reference height 720
    size: f32,
    color: Color,
}

pub struct Background {
    gradient_cells: Vec<Color>,
    gradient_w: u32,
    gradient_h: u32,
    particles: Vec<Particle>,
    scroll: f32, // horizontal block offset for gradient drift
}

impl Background {
    pub fn new() -> Self {
        let mut bg = Self {
            gradient_cells: Vec::new(),
            gradient_w: 0,
            gradient_h: 0,
            particles: Vec::new(),
            scroll: 0.0,
        };
        bg.spawn_particles();
        bg
    }

    pub fn update(&mut self, dt: f32) {
        self.scroll = (self.scroll + SCROLL_SPEED * dt).rem_euclid(self.gradient_w.max(1) as f32);
        for p in &mut self.particles {
            p.nx = (p.nx + p.vx * dt / 1280.0).rem_euclid(1.0);
            p.ny = (p.ny + p.vy * dt /  720.0).rem_euclid(1.0);
        }
    }

    pub fn draw(&mut self) {
        if self.needs_rebuild() {
            self.rebuild_gradient();
        }
        self.draw_gradient();
        self.draw_particles();
    }

    // ── private ───────────────────────────────────────────────────────────────

    fn needs_rebuild(&self) -> bool {
        let cw = (screen_width()  / BLOCK_SIZE).ceil() as u32;
        let ch = (screen_height() / BLOCK_SIZE).ceil() as u32;
        cw != self.gradient_w || ch != self.gradient_h
    }

    fn rebuild_gradient(&mut self) {
        let cw = (screen_width()  / BLOCK_SIZE).ceil() as u32;
        let ch = (screen_height() / BLOCK_SIZE).ceil() as u32;
        self.gradient_w = cw;
        self.gradient_h = ch;
        self.gradient_cells = Vec::with_capacity((cw * ch) as usize);

        for row in 0..ch {
            let t = if ch > 1 { row as f32 / (ch - 1) as f32 } else { 0.0 };
            let (br, bg, bb) = lerp_band(t);
            for col in 0..cw {
                let jr = cell_jitter(col, row, 0);
                let jg = cell_jitter(col, row, 1);
                let jb = cell_jitter(col, row, 2);
                self.gradient_cells.push(Color::new(
                    (br + jr).clamp(0.0, 1.0),
                    (bg + jg).clamp(0.0, 1.0),
                    (bb + jb).clamp(0.0, 1.0),
                    1.0,
                ));
            }
        }
    }

    fn draw_gradient(&self) {
        let frac_offset = self.scroll.fract() * BLOCK_SIZE;
        let col_offset  = self.scroll as u32;
        // render one extra column so the right edge stays filled during the scroll
        for col in 0..self.gradient_w + 1 {
            let src_col = (col + col_offset) % self.gradient_w;
            let screen_x = col as f32 * BLOCK_SIZE - frac_offset;
            for row in 0..self.gradient_h {
                let c = self.gradient_cells[(row * self.gradient_w + src_col) as usize];
                draw_rectangle(screen_x, row as f32 * BLOCK_SIZE, BLOCK_SIZE, BLOCK_SIZE, c);
            }
        }
    }

    fn draw_particles(&self) {
        let sw = screen_width();
        let sh = screen_height();
        for p in &self.particles {
            draw_rectangle(p.nx * sw, p.ny * sh, p.size, p.size, p.color);
        }
    }

    fn spawn_particles(&mut self) {
        for layer in 0..3usize {
            let speed_mul = LAYER_SPEEDS[layer];
            let alpha     = LAYER_ALPHAS[layer];
            let (sz_min, sz_max) = LAYER_SIZES[layer];

            for i in 0..PARTICLES_PER_LAYER {
                // deterministic-ish spread using simple arithmetic seeding
                let seed = (layer * PARTICLES_PER_LAYER + i) as u32;
                let nx = hash_f(seed, 0);
                let ny = hash_f(seed, 1);

                // direction archetype for this layer, with per-particle speed variation
                let (dx, dy) = LAYER_DIRS[layer];
                let base_speed = (hash_f(seed, 2) * 50.0 + 20.0) * speed_mul;
                let vx = dx * base_speed;
                let vy = dy * (hash_f(seed, 4) * 30.0 + 10.0) * speed_mul;

                let size = sz_min + hash_f(seed, 5) * (sz_max - sz_min);

                let ci = (hash_f(seed, 6) * SPICE_COLORS.len() as f32) as usize;
                let ci = ci.min(SPICE_COLORS.len() - 1);
                let (cr, cg, cb) = SPICE_COLORS[ci];

                self.particles.push(Particle {
                    nx, ny, vx, vy, size,
                    color: Color::new(cr, cg, cb, alpha),
                });
            }
        }
    }
}

// ── helpers ───────────────────────────────────────────────────────────────────

/// Piecewise linear interpolation over BAND_COLORS.
fn lerp_band(t: f32) -> (f32, f32, f32) {
    for i in 1..BAND_COLORS.len() {
        let (t0, c0) = BAND_COLORS[i - 1];
        let (t1, c1) = BAND_COLORS[i];
        if t <= t1 {
            let f = (t - t0) / (t1 - t0);
            return (
                c0.0 + (c1.0 - c0.0) * f,
                c0.1 + (c1.1 - c0.1) * f,
                c0.2 + (c1.2 - c0.2) * f,
            );
        }
    }
    BAND_COLORS.last().unwrap().1
}

/// Deterministic per-cell color jitter in [-0.07, 0.07].
fn cell_jitter(col: u32, row: u32, channel: u32) -> f32 {
    hash_f(col.wrapping_mul(7919).wrapping_add(row.wrapping_mul(104729)).wrapping_add(channel), 0)
        * 0.14 - 0.07
}

/// Maps (seed, sub_index) → [0, 1).
fn hash_f(seed: u32, sub: u32) -> f32 {
    let mut h = seed.wrapping_mul(2246822519).wrapping_add(sub.wrapping_mul(3266489917));
    h ^= h >> 13;
    h = h.wrapping_mul(0xbf58476d_u32);
    h ^= h >> 16;
    (h as f32) / (u32::MAX as f32)
}
