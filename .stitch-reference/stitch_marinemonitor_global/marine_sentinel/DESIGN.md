---
name: Marine Sentinel
colors:
  surface: '#f7f9fb'
  surface-dim: '#d8dadc'
  surface-bright: '#f7f9fb'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f4f6'
  surface-container: '#eceef0'
  surface-container-high: '#e6e8ea'
  surface-container-highest: '#e0e3e5'
  on-surface: '#191c1e'
  on-surface-variant: '#45464d'
  inverse-surface: '#2d3133'
  inverse-on-surface: '#eff1f3'
  outline: '#76777d'
  outline-variant: '#c6c6cd'
  surface-tint: '#565e74'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#131b2e'
  on-primary-container: '#7c839b'
  inverse-primary: '#bec6e0'
  secondary: '#006a61'
  on-secondary: '#ffffff'
  secondary-container: '#86f2e4'
  on-secondary-container: '#006f66'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#002114'
  on-tertiary-container: '#069669'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dae2fd'
  primary-fixed-dim: '#bec6e0'
  on-primary-fixed: '#131b2e'
  on-primary-fixed-variant: '#3f465c'
  secondary-fixed: '#89f5e7'
  secondary-fixed-dim: '#6bd8cb'
  on-secondary-fixed: '#00201d'
  on-secondary-fixed-variant: '#005049'
  tertiary-fixed: '#85f8c4'
  tertiary-fixed-dim: '#68dba9'
  on-tertiary-fixed: '#002114'
  on-tertiary-fixed-variant: '#005137'
  background: '#f7f9fb'
  on-background: '#191c1e'
  surface-variant: '#e0e3e5'
typography:
  display-lg:
    fontFamily: Public Sans
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Public Sans
    fontSize: 32px
    fontWeight: '600'
    lineHeight: 40px
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Public Sans
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
  headline-sm:
    fontFamily: Public Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  body-lg:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  mono-sm:
    fontFamily: Courier Prime
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 16px
  margin-mobile: 16px
  margin-desktop: 32px
  sidebar-width: 260px
  map-panel-width: 380px
---

## Brand & Style
The design system is engineered for environmental precision and operational clarity. It targets a professional audience of marine biologists, field researchers, and environmental policy makers who require a high-density information environment that remains legible under varying field conditions.

The aesthetic blends **Modern Corporate** with **Geospatial Professionalism**. It prioritizes a systematic, utilitarian approach to data visualization while maintaining a sophisticated, high-trust feel. The UI uses sharp, deliberate alignments and a limited decorative palette to ensure that the user's focus remains on critical ecological data and geographic mapping. The emotional response is one of calm, authoritative control over complex, real-time datasets.

## Colors
The palette is grounded in "Deep Ocean Navy" to provide a strong typographic foundation and high-contrast headers. "Ocean Teal" serves as the functional primary color for interactive states and primary call-to-actions.

**Operational Semantics:**
- **Natural/Habitat:** Use "Sea Green" for any data related to stable environmental conditions or native habitat mapping.
- **Priority Scale:** Monitoring urgency is represented by a sequential Purple scale. This prevents confusion with habitat data.
- **Status Indicators:** Use Amber for "Pending" or "In Review" states, and Muted Coral for "Critical Alerts" or "Confirmed Invasive" sightings.
- **Surfaces:** Backgrounds utilize a cool off-white to reduce eye strain, while cards and containers are pure white to elevate content against the neutral canvas.

## Typography
This design system employs a dual-font strategy. **Public Sans** is used for headlines and navigational elements to provide a sturdy, institutional feel. **Inter** is used for all body copy, data tables, and labels due to its exceptional legibility at small sizes and high information density.

For geospatial coordinates or scientific metadata, a secondary monospaced font may be used at small scales (label-sm) to ensure character distinction. Large headlines (32px+) should transition to the "headline-lg-mobile" (24px) on devices narrower than 768px.

## Layout & Spacing
The system utilizes a **Fixed Grid** approach for administrative dashboards and a **Fluid Overlay** model for geospatial views. 

- **Dashboard Layout:** 12-column grid with 24px gutters. Content is contained within a max-width of 1440px.
- **Geospatial Layout:** Full-bleed map view with a persistent left sidebar (260px). Information panels should float 16px from the edges of the map area.
- **Spacing Rhythm:** Based on a 4px baseline. Use 8px, 16px, and 24px increments for most component padding to maintain a tight, professional density suitable for scientific monitoring.

## Elevation & Depth
The design system uses a **Tonal Layering** approach combined with low-contrast outlines. 

- **Level 0 (Background):** #F8FAFC.
- **Level 1 (Cards/Sidebar):** White surface with a 1px solid border (#E2E8F0). No shadow.
- **Level 2 (Floating Map Panels):** White surface with 85% opacity backdrop-blur (20px), 1px border (#E2E8F0), and a soft, diffused ambient shadow (0px 4px 12px rgba(15, 23, 42, 0.08)).
- **Level 3 (Modals/Popovers):** White surface with a more pronounced shadow to indicate temporary interaction.

Avoid heavy shadows; use borders as the primary means of separation to maintain the "scientific" feel.

## Shapes
The shape language is "Rounded" (0.5rem / 8px) to soften the technical nature of the data while remaining professional.

- **Standard Buttons & Inputs:** 8px radius.
- **Cards & Map Panels:** 12px (rounded-lg) to provide a clear container hierarchy.
- **Status Badges:** Use 4px (soft) for standard tags, but use fully pill-shaped (rounded-xl) for "AI-Supported" labels to visually distinguish them from "Expert Confirmed" rectangular badges.

## Components
**Buttons:**
- **Primary:** Solid Ocean Teal (#0D9488) with white text.
- **Secondary:** Transparent with Ocean Teal border and text.
- **Ghost:** Primary Navy text with no background, used for low-priority map controls.

**Status Badges:**
- **Expert Confirmed:** Navy background, white text, 4px radius, includes a checkmark icon.
- **AI-Supported:** Teal border, light teal background, pill-shaped, includes a spark/AI icon.
- **Pending:** Amber border and text, 4px radius.

**Tables:**
- Row height: 48px.
- Header: Deep Navy background with white text or Light Gray (#F1F5F9) with Navy text for sub-tables.
- Grid lines: Horizontal only, 1px (#E2E8F0).

**Map UI:**
- Collapsible panels should feature a "grabber" handle at the top.
- Layers and filters use a checkbox list with 12px vertical spacing.
- Zoom/Navigation controls are vertically stacked in the bottom-right corner, white background, 1px border.

**Input Fields:**
- 1px border (#CBD5E1), 8px radius. Focus state: 2px Ocean Teal border with a soft glow.