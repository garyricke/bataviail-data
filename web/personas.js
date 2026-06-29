/* Persona config + matching seam (Stage 1).
 *
 * See plan/persona-evolution.md. The whole point of this file is to be the ONE
 * place that changes as matching gets smarter:
 *   - PERSONAS: data, not markup (later: a `personas` table).
 *   - rankForPersona(): the matching seam — today a client-side category score,
 *     later a Supabase RPC (pgvector + behavior). Callers never change.
 *   - logInteraction(): the Stage-2 behavioral hook — wired now so we collect a
 *     corpus from day one. Degrades to a silent no-op until the table exists.
 */
(function () {
  // key · label · tagline · accent color · category bundle (matched against the
  // real `categories` on entities). An org can match several personas.
  window.PERSONAS = [
    { key: "family", label: "Family with Kids", tagline: "Schools, play & family-friendly spots", color: "#60C560",
      categories: ["Schools", "Recreation", "Healthcare", "Dentists", "Pediatric", "Pet Services",
        "Restaurants & Taverns", "Food, Specialty", "Grocery / Retail", "Arts & Entertainment", "Sporting Goods"] },
    { key: "teen", label: "Teen & Student", tagline: "Skills, creativity & community impact", color: "#00ADEF",
      categories: ["Training & Development", "Schools", "Arts & Entertainment", "Recreation", "Sports Training",
        "Sporting Goods", "Non-Profit", "Service Organizations", "Coaching"] },
    { key: "socialite", label: "Downtown Socialite", tagline: "Nightlife, dining & culture on the Fox", color: "#8b5cf6",
      categories: ["Restaurants & Taverns", "Bar, Brewery, Winery and Taverns", "Tavern", "Arts & Entertainment",
        "Wellness", "Health & Wellness Products & Services", "Tourism", "Catering", "Banquet Facilities", "Jeweler / Jewelry"] },
    { key: "settler", label: "New to Batavia", tagline: "Plug into the community fast", color: "#f59e0b",
      categories: ["Schools", "Banks", "Real Estate/Residential", "Apartments", "Insurance", "Government",
        "Healthcare", "Grocery / Retail", "Association", "Churches/Ministries", "Moving & Storage"] },
    { key: "senior", label: "Senior & Care Circle", tagline: "Independence, health & connection", color: "#06b6d4",
      categories: ["Senior Services", "Retirement & Nursing Homes", "Assisted Living", "Healthcare", "Physical Therapy",
        "Counseling", "Home Furnishings", "Financial Planners & Advisors", "Service Organizations", "Churches/Ministries"] },
    { key: "business", label: "Business Builder", tagline: "Grow, connect & thrive in Batavia", color: "#ef4444",
      categories: ["Business Services", "Consultants", "Marketing / Social Media", "Information Technology",
        "Information Technology Managed Services", "Accounting Services", "Financial Services", "Banks", "Attorneys",
        "Real Estate/Commercial", "Promotional Items", "Printing and Copying", "Web Design",
        "Advertising & Graphic Design", "Association", "Manufacturing", "Distributors"] },
    { key: "volunteer", label: "Community Helper", tagline: "Give back to the town you love", color: "#10b981",
      categories: ["Non-Profit", "Social Services", "Service Organizations", "Churches/Ministries", "Association",
        "Government", "Counseling"] },
  ];

  window.personaByKey = function (key) {
    return window.PERSONAS.find(function (p) { return p.key === key; }) || null;
  };

  /* THE MATCHING SEAM.
   * Returns entities scored & sorted for a persona (score = how many of the
   * org's categories fall in the persona bundle). Score-based, never boolean —
   * so Stage 3/4 just add terms here (or this becomes an RPC call) with no
   * change to callers. Returns [{ ...entity, _score }] with _score > 0. */
  window.rankForPersona = function (personaKey, entities) {
    var p = window.personaByKey(personaKey);
    if (!p) return entities.slice();
    var bundle = {};
    p.categories.forEach(function (c) { bundle[c.toLowerCase()] = true; });
    return entities
      .map(function (e) {
        var score = (e.categories || []).reduce(function (s, c) {
          return s + (bundle[(c || "").toLowerCase()] ? 1 : 0);
        }, 0);
        return Object.assign({ _score: score }, e);
      })
      .filter(function (e) { return e._score > 0; })
      .sort(function (a, b) {
        if (b._score !== a._score) return b._score - a._score;            // best match first
        var ra = a.hero && a.hero.kind === "community" ? 0 : (a.hero ? 1 : 2);
        var rb = b.hero && b.hero.kind === "community" ? 0 : (b.hero ? 1 : 2);
        return ra - rb || a.name.localeCompare(b.name);
      });
  };

  /* STAGE-2 HOOK: fire-and-forget behavioral logging. Wired now so we build a
   * corpus from day one; silently no-ops until interaction_log + RLS exist
   * (migration 0013). Never blocks or throws into the UI. */
  window.logInteraction = function (eventType, payload) {
    try {
      var url = window.SUPABASE_URL, key = window.ANON_KEY;
      if (!url || !key) return;
      fetch(url + "/rest/v1/interaction_log", {
        method: "POST",
        headers: { apikey: key, Authorization: "Bearer " + key,
                   "Content-Type": "application/json", Prefer: "return=minimal" },
        body: JSON.stringify({ event_type: eventType, payload: payload || {} }),
        keepalive: true,
      }).catch(function () {});
    } catch (_) {}
  };
})();
