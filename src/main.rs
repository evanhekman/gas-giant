use macroquad::prelude::*;
use std::collections::HashSet;

mod background;
mod condenser;
mod resources;
use background::Background;
use condenser::Condenser;
use resources::RESOURCES;

const TILE_SIZE: f32 = 32.0;

const ZOOM_MIN: f32 = 0.5;
const ZOOM_MAX: f32 = 4.0;
const ZOOM_SPEED: f32 = 0.09;
const ZOOM_LERP: f32 = 0.18;

const PLAYER_SPEED: f32 = 180.0;
const PLAYER_HALF: f32 = TILE_SIZE * 0.3;

const PANEL_W: f32 = 180.0;
const PANEL_BG: Color = Color::new(0.10, 0.10, 0.12, 0.92);
const PANEL_DIVIDER: Color = Color::new(0.3, 0.3, 0.35, 1.0);
const LABEL_COLOR: Color = Color::new(0.65, 0.65, 0.75, 1.0);

// Amounts indexed by position in RESOURCES slice.
struct Amounts(Vec<u32>);

impl Amounts {
    fn new() -> Self { Self(vec![0; RESOURCES.len()]) }
}

fn world_to_tile(wx: f32, wy: f32) -> (i32, i32) {
    (wx.div_euclid(TILE_SIZE) as i32, wy.div_euclid(TILE_SIZE) as i32)
}

fn can_occupy(x: f32, y: f32, tile_set: &HashSet<(i32, i32)>) -> bool {
    let corners = [
        (x - PLAYER_HALF, y - PLAYER_HALF),
        (x + PLAYER_HALF - 0.001, y - PLAYER_HALF),
        (x - PLAYER_HALF, y + PLAYER_HALF - 0.001),
        (x + PLAYER_HALF - 0.001, y + PLAYER_HALF - 0.001),
    ];
    corners.iter().all(|&(cx, cy)| tile_set.contains(&world_to_tile(cx, cy)))
}

fn plus_tiles() -> Vec<(i32, i32)> {
    let mut tiles = Vec::new();
    let blocks: &[(i32, i32)] = &[
        (0, 0),  // center
        (0, -3), // top
        (0, 3),  // bottom
        (-3, 0), // left
        (3, 0),  // right
    ];
    for &(bx, by) in blocks {
        for row in 0..3i32 {
            for col in 0..3i32 {
                tiles.push((bx + col, by + row));
            }
        }
    }
    tiles
}

fn draw_panel(total: &Amounts, inventory: &Amounts, textures: &[Option<Texture2D>]) {
    let h = screen_height();
    let half = h / 2.0;
    let pad = 8.0;
    let icon_size = 16.0;
    let row_h = 20.0;
    let font_size = 13u16;

    draw_rectangle(0.0, 0.0, PANEL_W, h, PANEL_BG);
    draw_line(0.0, half, PANEL_W, half, 1.0, PANEL_DIVIDER);
    draw_line(PANEL_W, 0.0, PANEL_W, h, 1.0, PANEL_DIVIDER);

    // --- RESOURCES (top half) ---
    draw_text_ex("RESOURCES", pad, pad + row_h * 0.85, TextParams {
        font_size, color: LABEL_COLOR, ..Default::default()
    });
    draw_line(pad, pad + row_h, PANEL_W - pad, pad + row_h, 1.0, PANEL_DIVIDER);

    let mut row = 0;
    for (i, res) in RESOURCES.iter().enumerate() {
        let tex = match textures.get(i) { Some(Some(t)) => t, _ => continue };
        let amt = total.0[i];
        let ry = pad + row_h * (1.8 + row as f32);
        if ry + row_h > half { break; }

        draw_texture_ex(tex, pad, ry - icon_size * 0.75, WHITE, DrawTextureParams {
            dest_size: Some(Vec2::new(icon_size, icon_size)),
            ..Default::default()
        });
        draw_text_ex(res.name, pad + icon_size + 4.0, ry, TextParams {
            font_size, color: LABEL_COLOR, ..Default::default()
        });
        draw_text_ex(&amt.to_string(), PANEL_W - pad - 24.0, ry, TextParams {
            font_size, color: WHITE, ..Default::default()
        });
        row += 1;
    }

    // --- INVENTORY (bottom half, 3-col × 10-row grid) ---
    let inv_top = half;
    draw_text_ex("INVENTORY", pad, inv_top + pad + row_h * 0.85, TextParams {
        font_size, color: LABEL_COLOR, ..Default::default()
    });
    draw_line(pad, inv_top + pad + row_h, PANEL_W - pad, inv_top + pad + row_h, 1.0, PANEL_DIVIDER);

    const COLS: usize = 3;
    const ROWS: usize = 10;
    let grid_pad = 6.0;
    let cell_size = (PANEL_W - grid_pad * 2.0) / COLS as f32;
    let grid_top = inv_top + pad + row_h * 1.4;
    let cell_h = (h - grid_top - grid_pad) / ROWS as f32;

    // Build sorted list of (resource_index, stacks) — one entry per full+partial stack
    let mut slots: Vec<(usize, u32)> = Vec::new();
    for (i, res) in RESOURCES.iter().enumerate() {
        let mut remaining = inventory.0[i];
        if remaining == 0 { continue; }
        while remaining > 0 {
            let stack = remaining.min(res.stack_limit);
            slots.push((i, stack));
            remaining -= stack;
        }
    }

    let cell_bg   = Color::new(0.15, 0.15, 0.18, 1.0);
    let cell_border = Color::new(0.28, 0.28, 0.33, 1.0);

    for grid_slot in 0..(COLS * ROWS) {
        let col = (grid_slot % COLS) as f32;
        let row = (grid_slot / COLS) as f32;
        let cx = grid_pad + col * cell_size;
        let cy = grid_top + row * cell_h;

        draw_rectangle(cx, cy, cell_size - 1.0, cell_h - 1.0, cell_bg);
        draw_rectangle_lines(cx, cy, cell_size - 1.0, cell_h - 1.0, 1.0, cell_border);

        if let Some(&(res_idx, stack)) = slots.get(grid_slot) {
            let icon_draw_size = cell_h.min(cell_size) - 6.0;
            let ix = cx + (cell_size - icon_draw_size) / 2.0;
            let iy = cy + (cell_h - icon_draw_size) / 2.0;

            if let Some(Some(tex)) = textures.get(res_idx) {
                draw_texture_ex(tex, ix, iy, WHITE, DrawTextureParams {
                    dest_size: Some(Vec2::new(icon_draw_size, icon_draw_size)),
                    ..Default::default()
                });
            }

            let res = &RESOURCES[res_idx];
            let count_str = stack.to_string();
            let count_color = if stack == res.stack_limit { Color::new(1.0, 0.85, 0.3, 1.0) } else { WHITE };
            draw_text_ex(&count_str, cx + cell_size - 2.0 - count_str.len() as f32 * 7.0, cy + cell_h - 3.0, TextParams {
                font_size: 10,
                color: count_color,
                ..Default::default()
            });
        }
    }
}

#[macroquad::main("Gas Giant")]
async fn main() {
    let mut bg = Background::new();

    let tiles = plus_tiles();
    let condenser_tiles: HashSet<(i32, i32)> = [(1, -2), (1, 4), (-2, 1), (4, 1)].iter().cloned().collect();
    let tile_set: HashSet<(i32, i32)> = tiles.iter().cloned()
        .filter(|t| !condenser_tiles.contains(t))
        .collect();

    let mut zoom: f32 = 1.0;
    let mut zoom_target: f32 = 1.0;
    let mut zoom_anchor: (f32, f32) = (0.0, 0.0);
    let mut cam_x: f32 = 0.0;
    let mut cam_y: f32 = 0.0;
    let mut drag_start: Option<(f32, f32, f32, f32)> = None;

    let mut player_x: f32 = TILE_SIZE * 1.5;
    let mut player_y: f32 = TILE_SIZE * 1.5;

    let mut total = Amounts::new();
    let mut inventory = Amounts::new();
    // placeholder totals
    total.0[0] = 120; total.0[1] = 45; total.0[2] = 8; total.0[3] = 3;

    // load resource textures (None if sprite path not set or file missing)
    let mut resource_textures: Vec<Option<Texture2D>> = Vec::new();
    for res in RESOURCES.iter() {
        let tex = if let Some(path) = res.sprite {
            load_texture(path).await.ok().map(|t| { t.set_filter(FilterMode::Nearest); t })
        } else {
            None
        };
        resource_textures.push(tex);
    }

    // load floor tile variants and assign one randomly to each tile
    let mut floor_textures: Vec<Texture2D> = Vec::new();
    for i in 1..=6 {
        if let Ok(t) = load_texture(&format!("assets/sprites/floor/floor_{}.png", i)).await {
            t.set_filter(FilterMode::Nearest);
            floor_textures.push(t);
        }
    }
    let tile_variants: Vec<usize> = tiles.iter()
        .map(|_| rand::gen_range(0, floor_textures.len().max(1)))
        .collect();

    let mut condensers = vec![
        Condenser::new( 1, -2).await, // top
        Condenser::new( 1,  4).await, // bottom
        Condenser::new(-2,  1).await, // left
        Condenser::new( 4,  1).await, // right
    ];

    loop {
        let dt = get_frame_time();

        // --- zoom ---
        let scroll = mouse_wheel().1;
        if scroll != 0.0 {
            let (mx, my) = mouse_position();
            zoom_target = (zoom_target * (1.0 + scroll * ZOOM_SPEED)).clamp(ZOOM_MIN, ZOOM_MAX);
            zoom_anchor = (mx, my);
        }
        if (zoom_target - zoom).abs() > 0.0001 {
            let prev_zoom = zoom;
            zoom += (zoom_target - zoom) * ZOOM_LERP;
            let (mx, my) = zoom_anchor;
            let screen_cx = screen_width() / 2.0;
            let screen_cy = screen_height() / 2.0;
            let world_x = cam_x + (mx - screen_cx) / prev_zoom;
            let world_y = cam_y + (my - screen_cy) / prev_zoom;
            cam_x = world_x - (mx - screen_cx) / zoom;
            cam_y = world_y - (my - screen_cy) / zoom;
        }

        // --- pan ---
        if is_mouse_button_pressed(MouseButton::Left)
            || is_mouse_button_pressed(MouseButton::Right)
            || is_mouse_button_pressed(MouseButton::Middle)
        {
            let (mx, my) = mouse_position();
            drag_start = Some((mx, my, cam_x, cam_y));
        }
        if is_mouse_button_released(MouseButton::Left)
            || is_mouse_button_released(MouseButton::Right)
            || is_mouse_button_released(MouseButton::Middle)
        {
            drag_start = None;
        }
        if let Some((sx, sy, scx, scy)) = drag_start {
            let (mx, my) = mouse_position();
            cam_x = scx - (mx - sx) / zoom;
            cam_y = scy - (my - sy) / zoom;
        }

        // --- condenser tick ---
        for c in &mut condensers { c.update(); }

        // --- collection ---
        if is_key_pressed(KeyCode::Space) {
            for c in &mut condensers {
                if c.player_in_range(player_x, player_y) {
                    let amount = c.collect();
                    inventory.0[1] += amount as u32; // helium index 1
                }
            }
        }

        // --- player movement ---
        let moving_x = is_key_down(KeyCode::A) || is_key_down(KeyCode::D);
        let moving_y = is_key_down(KeyCode::W) || is_key_down(KeyCode::S);
        let speed = if moving_x && moving_y {
            PLAYER_SPEED * std::f32::consts::FRAC_1_SQRT_2
        } else {
            PLAYER_SPEED
        };

        let dx = if is_key_down(KeyCode::D) { speed * dt } else if is_key_down(KeyCode::A) { -speed * dt } else { 0.0 };
        let dy = if is_key_down(KeyCode::S) { speed * dt } else if is_key_down(KeyCode::W) { -speed * dt } else { 0.0 };

        if can_occupy(player_x + dx, player_y, &tile_set) { player_x += dx; }
        if can_occupy(player_x, player_y + dy, &tile_set) { player_y += dy; }

        // --- draw world ---
        bg.update(dt);
        bg.draw();

        // world origin is screen center, offset by camera
        let screen_cx = screen_width() / 2.0;
        let screen_cy = screen_height() / 2.0;

        for (idx, &(col, row)) in tiles.iter().enumerate() {
            if condenser_tiles.contains(&(col, row)) { continue; }
            let wx = col as f32 * TILE_SIZE;
            let wy = row as f32 * TILE_SIZE;
            let sx = screen_cx + (wx - cam_x) * zoom;
            let sy = screen_cy + (wy - cam_y) * zoom;
            let sz = TILE_SIZE * zoom;
            if !floor_textures.is_empty() {
                let tex = &floor_textures[tile_variants[idx]];
                draw_texture_ex(tex, sx, sy, WHITE, DrawTextureParams {
                    dest_size: Some(Vec2::new(sz, sz)),
                    ..Default::default()
                });
            } else {
                draw_rectangle(sx, sy, sz, sz, GRAY);
                draw_rectangle_lines(sx, sy, sz, sz, 1.5, DARKGRAY);
            }
        }

        for c in &condensers {
            let in_range = c.player_in_range(player_x, player_y);
            c.draw(screen_cx, screen_cy, cam_x, cam_y, zoom, in_range);
        }

        let player_size = TILE_SIZE * 0.6;
        let psx = screen_cx + (player_x - player_size / 2.0 - cam_x) * zoom;
        let psy = screen_cy + (player_y - player_size / 2.0 - cam_y) * zoom;
        let psz = player_size * zoom;
        draw_rectangle(psx, psy, psz, psz, YELLOW);

        // --- draw UI (always on top, screen-space) ---
        draw_panel(&total, &inventory, &resource_textures);

        next_frame().await;
    }
}
