use macroquad::prelude::*;

#[derive(Clone, Debug, PartialEq)]
pub enum ResourceIcon {
    Blend,
    Molecule,
    Isotope { rings: u8 },
}

#[derive(Clone, Debug)]
pub struct Resource {
    pub name: &'static str,
    pub icon: ResourceIcon,
    pub color: Color,
    pub sprite: Option<&'static str>, // path relative to assets/sprites/
}

fn lighten(c: Color) -> Color {
    Color::new((c.r * 1.3).min(1.0), (c.g * 1.3).min(1.0), (c.b * 1.3).min(1.0), 1.0)
}

macro_rules! c {
    ($r:expr, $g:expr, $b:expr) => {
        Color { r: $r as f32 / 255.0, g: $g as f32 / 255.0, b: $b as f32 / 255.0, a: 1.0 }
    };
}

pub const RESOURCES: &[Resource] = &[
    // Blends
    Resource { name: "Hydrogen", icon: ResourceIcon::Blend, color: c!(0xe8, 0x79, 0xa0), sprite: Some("assets/sprites/resources/hydrogen_blend.png") },
    Resource { name: "Helium",   icon: ResourceIcon::Blend, color: c!(0xe0, 0x78, 0x20), sprite: Some("assets/sprites/resources/helium_blend.png")   },
    Resource { name: "Methane",  icon: ResourceIcon::Blend, color: c!(0x1a, 0x90, 0x80), sprite: Some("assets/sprites/resources/methane_blend.png")  },
    Resource { name: "Sulfur",   icon: ResourceIcon::Blend, color: c!(0xc8, 0xa8, 0x00), sprite: Some("assets/sprites/resources/sulfur_blend.png")   },
    // Molecules
    Resource { name: "CH4",   icon: ResourceIcon::Molecule,             color: c!(0x1a, 0x90, 0x80), sprite: None },
    Resource { name: "NH3",   icon: ResourceIcon::Molecule,             color: c!(0x2a, 0x88, 0x30), sprite: None },
    Resource { name: "H2S",   icon: ResourceIcon::Molecule,             color: c!(0x7a, 0x98, 0x00), sprite: None },
    Resource { name: "NH4SH", icon: ResourceIcon::Molecule,             color: c!(0x6b, 0x70, 0x20), sprite: None },
    Resource { name: "H2O",   icon: ResourceIcon::Molecule,             color: c!(0x18, 0x60, 0xc0), sprite: None },
    Resource { name: "O2",    icon: ResourceIcon::Molecule,             color: c!(0x08, 0x98, 0xb8), sprite: None },
    Resource { name: "N2",    icon: ResourceIcon::Molecule,             color: c!(0x58, 0x40, 0xb0), sprite: None },
    Resource { name: "CO2",   icon: ResourceIcon::Molecule,             color: c!(0x50, 0x50, 0x50), sprite: None },
    Resource { name: "C",     icon: ResourceIcon::Molecule,             color: c!(0x28, 0x28, 0x28), sprite: None },
    Resource { name: "S",     icon: ResourceIcon::Molecule,             color: c!(0xc8, 0xa8, 0x00), sprite: None },
    Resource { name: "PH3",   icon: ResourceIcon::Molecule,             color: c!(0xc0, 0x30, 0x10), sprite: None },
    // Isotopes
    Resource { name: "H1",  icon: ResourceIcon::Isotope { rings: 0 }, color: c!(0xe8, 0x79, 0xa0), sprite: None },
    Resource { name: "H2",  icon: ResourceIcon::Isotope { rings: 1 }, color: c!(0xe8, 0x79, 0xa0), sprite: None },
    Resource { name: "H3",  icon: ResourceIcon::Isotope { rings: 2 }, color: c!(0xe8, 0x79, 0xa0), sprite: None },
    Resource { name: "He4", icon: ResourceIcon::Isotope { rings: 0 }, color: c!(0xe0, 0x78, 0x20), sprite: None },
    Resource { name: "He3", icon: ResourceIcon::Isotope { rings: 1 }, color: c!(0xe0, 0x78, 0x20), sprite: None },
];

// Hex vertices for a flat-top hexagon (0°, 60°, 120°, ...)
fn hex_pts(cx: f32, cy: f32, r: f32) -> [(f32, f32); 6] {
    let mut pts = [(0.0f32, 0.0f32); 6];
    for i in 0..6 {
        let a = std::f32::consts::PI / 3.0 * i as f32;
        pts[i] = (cx + r * a.cos(), cy + r * a.sin());
    }
    pts
}

pub fn draw_resource_icon(icon: &ResourceIcon, color: Color, x: f32, y: f32, size: f32) {
    let radius = size / 2.0;
    let stroke = lighten(color);
    let sw = 1.5;

    match icon {
        ResourceIcon::Blend => {
            // filled flat-top hexagon via triangle fan
            let pts = hex_pts(x, y, radius);
            for i in 0..6 {
                let a = pts[i];
                let b = pts[(i + 1) % 6];
                draw_triangle(Vec2::new(x, y), Vec2::new(a.0, a.1), Vec2::new(b.0, b.1), color);
            }
            // stroke outline
            for i in 0..6 {
                let a = pts[i];
                let b = pts[(i + 1) % 6];
                draw_line(a.0, a.1, b.0, b.1, sw, stroke);
            }
        }
        ResourceIcon::Molecule => {
            draw_circle(x, y, radius, color);
            draw_circle_lines(x, y, radius, sw, stroke);
        }
        ResourceIcon::Isotope { rings } => {
            let inner_r = size * 0.4;
            draw_circle(x, y, inner_r, color);
            draw_circle_lines(x, y, inner_r, sw, stroke);
            for i in 1..=(*rings) {
                let ring_r = inner_r + size * 0.15 * i as f32;
                draw_circle_lines(x, y, ring_r, sw, stroke);
            }
        }
    }
}
