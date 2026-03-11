---
name: tru-brand-guide
description: Thompson Rivers University (TRU) brand and web style guide. Use this skill whenever creating, designing, or writing content for TRU websites, web pages, digital materials, or any TRU-branded output. Triggers on any mention of TRU, Thompson Rivers University, tru.ca, or when the user asks about brand colours, fonts, tone, or web style for TRU. Also use when the user asks you to "follow TRU branding", "make it look like TRU", or "use TRU style".
---

# Thompson Rivers University — Brand & Web Style Guide

This skill ensures all TRU web content, design, and copy aligns with official TRU brand standards sourced from https://www.tru.ca/marcom/brandguide.html and https://www.tru.ca/marcom/styleguide.html

---

## Brand Personality

TRU's brand attributes — always reflect these in tone and design:

- **Purposeful** — Everything exists as part of a bigger design, with a drive to learn and grow
- **Empowering** — Guides and supports people to take ownership of their future
- **Collaborative** — Works together with students, staff, community
- **Open** — Inclusive, accessible, meeting people where they are
- **Visionary** — Courageous and innovative, proud to be a new model of university

Brand promise: *"Diverse pathways to living your potential."*
Brand purpose: *"Everyone has the right to seek their potential."*

---

## Colour Palette

TRU colours are inspired by the landscape of Kamloops, BC.

### Primary Colours

| Name       | Hex       | RGB           | Pantone | Use |
|------------|-----------|---------------|---------|-----|
| **Blue**   | `#003e51` | 0, 62, 81     | 3035    | Primary brand colour; headers, nav, CTAs |
| **Teal**   | `#00b0b9` | 0, 176, 185   | 7466    | Accent, highlights, links |
| **Sage**   | `#bad1ba` | 186, 209, 186 | 5565    | Backgrounds, secondary panels |
| **Grey**   | `#9ab7c1` | 122, 153, 172 | 5425    | Supporting backgrounds, borders |
| **Yellow** | `#ffcd00` | 255, 205, 0   | 116     | Accent, callouts, highlights |

### Colour Usage Rules

- Blue (`#003e51`) is the dominant brand colour — use for headers, nav bars, primary buttons, and key UI elements
- Teal (`#00b0b9`) works for links, secondary buttons, accents
- Yellow (`#ffcd00`) is a "punch of colour" — use sparingly for callouts, highlights, not for large blocks
- Sage and Grey are calm background/supporting colours
- **Avoid large areas of black** — use a brand colour instead
- Always use the white (reversed) logo version on dark/coloured backgrounds
- Never make the blue logo white — use the proper reversed version

### CSS Custom Properties (recommended)

```css
:root {
  --tru-blue:   #003e51;
  --tru-teal:   #00b0b9;
  --tru-sage:   #bad1ba;
  --tru-grey:   #9ab7c1;
  --tru-yellow: #ffcd00;
  --tru-white:  #ffffff;
}
```

---

## Typography

### Primary Typefaces

| Font         | Role | Fallback |
|--------------|------|----------|
| **Adelle**   | Body copy, headlines, subheads — conveys open and collaborative personality | Roboto Slab Light |
| **Adelle Sans** | Body copy, headlines, subheads — clean and modern | Roboto Light |

- Both Adelle and Adelle Sans are suitable for headlines, subheads, and body copy
- Maximize readability — follow accessibility contrast standards
- When brand fonts aren't available, use the specified Google Fonts fallbacks (both available free via Google Fonts)

### Web Font Stack (CSS)

```css
body {
  font-family: 'Adelle Sans', 'Roboto', sans-serif;
}

h1, h2, h3 {
  font-family: 'Adelle', 'Roboto Slab', serif;
}
```

---

## Voice & Tone

### Voice (Consistent Personality)

TRU's voice is consistent across all communications. Write as if TRU is:
- Confident but not arrogant
- Warm, welcoming, and inclusive
- Direct and action-oriented
- Authentic — speak from actual values, not corporate-speak

### Tone (Adjusts by Audience)

Adjust tone based on audience while keeping the same voice:

| Audience | Tone |
|----------|------|
| Prospective students | Inspiring, hopeful, empowering |
| Current students | Practical, supportive, friendly |
| Alumni/donors | Pride-focused, impactful, warm |
| Media/public | Professional, credible, factual |
| Internal/faculty | Collegial, direct, collaborative |

### Writing Style Rules

1. **Follow Canadian Press (CP) style** — TRU's primary style reference
2. **Canadian Oxford Dictionary** for words not in CP
3. **Predominantly lowercase** — CP style, easier to read; avoid over-capitalization
4. **Inclusive language** — Be mindful of impact; see inclusive language guidelines
5. **Indigenous language** — Use Tk'emlúps dialect/spelling for Secwépemc words; *Elements of Indigenous Style* overrides CP for Indigenous references. TRU's First House is Tk'emlúps te Secwépemc
6. **Name references** — Full name on first reference; last name for formal (news releases); first name for informal (social media) on subsequent references
7. **Address format** — Canada Post style, no punctuation, two spaces between province and postal code:
   ```
   Thompson Rivers University
   805 TRU Way
   Kamloops BC  V2C 0C8
   Canada
   ```

### Writing Do's and Don'ts

✅ **Do:**
- Write with purpose and direction
- Empower the reader — frame around their journey and potential
- Be direct and clear; avoid jargon
- Reflect diversity and inclusion naturally
- Use active voice

❌ **Don't:**
- Use overly academic or bureaucratic language
- Over-capitalize (follow CP lowercase style)
- Use large areas of black in design
- Isolate the TRU logo from its required clear space
- Write in a way that excludes or marginalizes any audience

---

## Logo Usage

- **Clear space:** Surround logo with space equal to or greater than the height of the "T" in TRU
- **Minimum size:** At least 1 inch wide
- **Never:** Stretch, recolour (other than approved versions), add text within clear space, or use the shield alone without "Thompson Rivers University"
- **On dark backgrounds:** Use the white/reversed version — never white-out the blue version
- **File formats:**
  - EPS → print, signage, embroidery, InDesign
  - PNG → web, Word, PowerPoint, Microsoft apps

---

## Web-Specific Guidelines

### Grid & Layout

- TRU uses a standard grid system for web — keep content structured and scannable
- Use columns to organize content; avoid walls of text
- White space is your friend — don't crowd content

### Links

- Links should be descriptive (not "click here")
- Use teal (`#00b0b9`) or the site's default link colour for inline links

### Buttons

- Primary buttons: TRU Blue (`#003e51`) background, white text
- Secondary buttons: outlined or teal (`#00b0b9`)
- CTAs should be action-oriented: "Apply Now", "Register", "Learn More"

### Images & Photography

- Use authentic, diverse imagery representing real TRU students, staff, and campus
- Avoid staged or stock-photo-looking images
- On-brand photography supports the brand colours and personality
- Images of people should reflect TRU's diverse community

### Accessibility

- Maintain WCAG 2.1 AA contrast ratios minimum
- All images need descriptive alt text
- Use semantic HTML heading hierarchy (H1 → H2 → H3)
- Ensure keyboard navigability

### Content Components Available

TRU's web system includes these standard components — use them consistently:
- Banners & sliders
- Panels and alert boxes
- Expandable sections and tabs
- Modal windows
- Parallax images
- Image rows and columns
- Step indicators

---
