/* Theme registry + picking seam (Tier 2/3 of the landing-page ladder).
 *
 * See web/plan-landing-pages.html. Mirrors the personas.js pattern: themes are
 * DATA (later: a `themes` table + entities.theme column), and this file is the
 * ONE place that changes as the library grows:
 *   - THEMES: token set + font pairing + hero variant + section order.
 *   - CATEGORY_THEMES: ordered keyword rules mapping real chamber categories
 *     to a theme. First match wins; unknown categories fall back to "profile".
 *   - pickTheme(entity): the seam. Today keyword rules; later reads
 *     entities.theme (claim-time override) with rules as fallback. Callers
 *     (landing.html) never change.
 *
 * A theme is the whole design: palette, type, hero treatment, and which
 * sections render in what order. "profile" reproduces the Tier-1 entity.html
 * baseline inside the engine so the ladder starts from a common rung.
 * "bespoke" is Tier 3 — never auto-picked, only explicit (?theme= or, later,
 * a paid entity.theme).
 */
(function () {
  window.THEMES = {
    profile: {
      key: "profile", label: "Profile", tier: 1,
      blurb: "The universal baseline — one clean layout, brand-tokened per entity.",
      dark: false, useBrand: true,
      tokens: { bg: "#f4f5f8", surface: "#ffffff", ink: "#1c2030", muted: "#7E7F81",
                line: "#e7e9f0", accent: "#292F7B", accent2: "#00ADEF" },
      fonts: { display: "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif",
               body: "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif",
               google: [] },
      hero: "immersive", servicesStyle: "chips",
      sections: ["about", "services", "events", "hours", "contact", "gallery"],
    },

    bold: {
      key: "bold", label: "Bold", tier: 2,
      blurb: "Iron, gold and grit — gyms, trades, auto, anything that sweats.",
      dark: true, useBrand: false,
      tokens: { bg: "#16171b", surface: "#1f2127", ink: "#f0eee8", muted: "#9a9890",
                line: "#2c2e35", accent: "#e0a32e", accent2: "#3fb8af" },
      fonts: { display: "'Bebas Neue',Impact,sans-serif",
               body: "'Barlow',-apple-system,sans-serif",
               google: ["Bebas+Neue", "Barlow:wght@400;500;600;700"] },
      hero: "poster", servicesStyle: "cards",
      sections: ["services", "about", "gallery", "hours", "events", "contact"],
    },

    warm: {
      key: "warm", label: "Warm", tier: 2,
      blurb: "Cream, espresso and slab type — food, retail and maker spaces.",
      dark: false, useBrand: false,
      tokens: { bg: "#f6efe3", surface: "#fffaf1", ink: "#362a1e", muted: "#7d6f5d",
                line: "#e6dcc9", accent: "#b4552d", accent2: "#667c50" },
      fonts: { display: "'Alfa Slab One',Georgia,serif",
               body: "'Karla',-apple-system,sans-serif",
               google: ["Alfa+Slab+One", "Karla:wght@400;500;700"] },
      hero: "immersive", servicesStyle: "chips",
      sections: ["about", "gallery", "services", "hours", "events", "contact"],
    },

    civic: {
      key: "civic", label: "Civic", tier: 2,
      blurb: "Light editorial serif — nonprofits, government, schools, culture.",
      dark: false, useBrand: false,
      tokens: { bg: "#f7f6f1", surface: "#ffffff", ink: "#1f2d26", muted: "#6b7468",
                line: "#e2e0d4", accent: "#2e6b4f", accent2: "#a8842c" },
      fonts: { display: "'Fraunces',Georgia,serif",
               body: "'Public Sans',-apple-system,sans-serif",
               google: ["Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700", "Public+Sans:wght@400;500;600"] },
      hero: "editorial", servicesStyle: "chips",
      sections: ["about", "events", "services", "contact", "hours", "gallery"],
    },

    bespoke: {
      key: "bespoke", label: "Bespoke", tier: 3,
      blurb: "The Pro page — full-bleed hero, stat band, pull quote, real CTA.",
      dark: true, useBrand: true,
      tokens: { bg: "#0e1018", surface: "#171a26", ink: "#f2f3f8", muted: "#9aa0b5",
                line: "#262a3a", accent: "#c9a24a", accent2: "#00ADEF" },
      fonts: { display: "'Instrument Serif',Georgia,serif",
               body: "'Instrument Sans',-apple-system,sans-serif",
               google: ["Instrument+Serif:ital@0;1", "Instrument+Sans:wght@400;500;600"] },
      hero: "fullbleed", servicesStyle: "cards",
      sections: ["stats", "about", "quote", "services", "gallery", "events", "hours", "cta"],
    },
  };

  // Demo/ladder order (also the order the switcher shows).
  window.THEME_ORDER = ["profile", "bold", "warm", "civic", "bespoke"];

  /* Ordered keyword rules against real chamber category names (substring,
   * case-insensitive). First rule whose pattern hits any category wins.
   * "bespoke" is intentionally absent — Tier 3 is opt-in, never inferred. */
  var CATEGORY_THEMES = [
    { theme: "warm", pat: ["restaurant", "tavern", "brewer", "winery", "coffee", "cafe",
        "bak", "food", "catering", "banquet", "grocery", "retail", "florist",
        "ice cream", "candy", "butcher", "deli"] },
    { theme: "bold", pat: ["fitness", "gym", "sport", "athletic", "martial", "auto",
        "tire", "towing", "construction", "contractor", "roofing", "plumb",
        "electrical", "heating", "hvac", "landscap", "manufactur", "weld",
        "excavat", "paving", "garage"] },
    { theme: "civic", pat: ["non-profit", "nonprofit", "government", "school", "education",
        "church", "ministr", "museum", "library", "social service",
        "service organization", "association", "senior service", "tourism",
        "historical", "arts & entertainment", "civic"] },
  ];

  /* THE PICKING SEAM.
   * entity.theme (future column / claim override) > category rules > profile.
   * Accepts anything with a `categories` array — entity_full or entities_summary. */
  window.pickTheme = function (entity) {
    if (entity && entity.theme && window.THEMES[entity.theme]) return entity.theme;
    var cats = ((entity && entity.categories) || []).map(function (c) { return (c || "").toLowerCase(); });
    for (var i = 0; i < CATEGORY_THEMES.length; i++) {
      var rule = CATEGORY_THEMES[i];
      for (var j = 0; j < cats.length; j++) {
        for (var k = 0; k < rule.pat.length; k++) {
          if (cats[j].indexOf(rule.pat[k]) !== -1) return rule.theme;
        }
      }
    }
    return "profile";
  };

  window.themeByKey = function (key) {
    return window.THEMES[key] || window.THEMES.profile;
  };

  // One <link> href covering a theme's Google fonts (empty string if none).
  window.themeFontsHref = function (theme) {
    if (!theme.fonts.google.length) return "";
    return "https://fonts.googleapis.com/css2?" +
      theme.fonts.google.map(function (f) { return "family=" + f; }).join("&") +
      "&display=swap";
  };
})();
