use macroquad::prelude::*;

const TICKS_PER_PHASE: u32 = 6; // 960 / 8 — temporary 8x speed
const MAX_FILL: u8 = 20;
const MAX_PHASE: u8 = 6;

pub struct Condenser {
    pub fill_level: u8, // 0–20
    pub phase: u8,      // 0–6
    tick: u32,

    // tile position (col, row) in world grid
    pub col: i32,
    pub row: i32,

    fill_textures: Vec<Texture2D>,  // h_cond_0 .. h_cond_20
    phase_textures: Vec<Texture2D>, // h_cond_phase_0 .. h_cond_phase_6
}

impl Condenser {
    pub async fn new(col: i32, row: i32) -> Self {
        let mut fill_textures = Vec::new();
        for i in 0..=MAX_FILL {
            let t = load_texture(&format!("assets/sprites/machines/h_condenser/h_cond_{}.png", i))
                .await
                .expect(&format!("missing h_cond_{}.png", i));
            t.set_filter(FilterMode::Nearest);
            fill_textures.push(t);
        }

        let mut phase_textures = Vec::new();
        for i in 0..=MAX_PHASE {
            let t = load_texture(&format!("assets/sprites/machines/h_condenser/h_cond_phase_{}.png", i))
                .await
                .expect(&format!("missing h_cond_phase_{}.png", i));
            t.set_filter(FilterMode::Nearest);
            phase_textures.push(t);
        }

        Self {
            fill_level: 0,
            phase: 0,
            tick: 0,
            col,
            row,
            fill_textures,
            phase_textures,
        }
    }

    pub fn update(&mut self) {
        if self.fill_level >= MAX_FILL {
            return; // full — stop cycling until collected
        }

        self.tick += 1;
        if self.tick >= TICKS_PER_PHASE {
            self.tick = 0;
            if self.phase < MAX_PHASE {
                self.phase += 1;
            } else {
                self.phase = 0;
                self.fill_level += 1;
                if self.fill_level >= MAX_FILL {
                    // just filled up — snap phase to 0 and stop until collected
                    self.phase = 0;
                    self.tick = 0;
                }
            }
        }
    }

    /// Returns true if the player centre is within one tile of the condenser centre.
    pub fn player_in_range(&self, player_x: f32, player_y: f32) -> bool {
        let cx = self.col as f32 * 32.0 + 16.0;
        let cy = self.row as f32 * 32.0 + 16.0;
        (player_x - cx).abs() < 32.0 && (player_y - cy).abs() < 32.0
    }

    /// Drain fill_level only — phase and tick keep running uninterrupted.
    pub fn collect(&mut self) -> u8 {
        let amount = self.fill_level;
        self.fill_level = 0;
        amount
    }

    pub fn draw(
        &self,
        screen_cx: f32,
        screen_cy: f32,
        cam_x: f32,
        cam_y: f32,
        zoom: f32,
        in_range: bool,
    ) {
        let wx = self.col as f32 * 32.0;
        let wy = self.row as f32 * 32.0;
        let sx = screen_cx + (wx - cam_x) * zoom;
        let sy = screen_cy + (wy - cam_y) * zoom;
        let sz = 32.0 * zoom;

        let params = DrawTextureParams {
            dest_size: Some(Vec2::new(sz, sz)),
            ..Default::default()
        };

        draw_texture_ex(
            &self.fill_textures[self.fill_level as usize],
            sx,
            sy,
            WHITE,
            params.clone(),
        );
        draw_texture_ex(
            &self.phase_textures[self.phase as usize],
            sx,
            sy,
            WHITE,
            params,
        );

        // highlight border when player is in range
        if in_range {
            draw_rectangle_lines(sx, sy, sz, sz, 2.0, Color::new(1.0, 1.0, 0.6, 0.7));
        }
    }
}
