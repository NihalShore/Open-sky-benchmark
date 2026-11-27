const BAND_QUALITIES = new Set(["A", "B", "C"]);

export function passesIrsaQualityScreen(row) {
  const photometricQuality = String(row?.photometric_quality ?? "").trim().toUpperCase();
  const hasBandDetection =
    BAND_QUALITIES.has(photometricQuality[0]) ||
    BAND_QUALITIES.has(photometricQuality[1]);

  return Number(row?.frame_quality) > 0
    && Number(row?.quality_info_factor) > 0
    && Number(row?.saa_separation_deg) > 0
    && String(row?.moon_masked ?? "").trim() === "00"
    && String(row?.contamination_flags ?? "").trim().toUpperCase().startsWith("00")
    && String(row?.w1_transient_flags ?? "").trim() === "0000"
    && String(row?.w2_transient_flags ?? "").trim() === "0000"
    && hasBandDetection;
}

const ASSOCIATION_FIELDS = [
  {
    type: "AllWISE",
    id: "allwise_source_id",
    separation: "allwise_separation_arcsec",
    count: "allwise_match_count",
  },
  {
    type: "2MASS",
    id: "tmass_source_id",
    separation: "tmass_separation_arcsec",
    count: "tmass_match_count",
  },
];

export function catalogAssociationsFor(row) {
  const matches = [];

  for (const fields of ASSOCIATION_FIELDS) {
    const id = row?.[fields.id];
    const count = Number(row?.[fields.count]);
    const rawSeparation = row?.[fields.separation];
    const separation = rawSeparation === null || rawSeparation === undefined || rawSeparation === ""
      ? null
      : Number(rawSeparation);

    if (
      id === null ||
      id === undefined ||
      String(id).trim() === "" ||
      !Number.isFinite(count) ||
      count <= 0
    ) {
      continue;
    }

    matches.push({
      type: fields.type,
      id: String(id),
      count,
      separationArcsec: Number.isFinite(separation) ? separation : null,
      unique: count === 1 && Number.isFinite(separation) && separation >= 0 && separation <= 3,
    });
  }

  return matches;
}

export function summarizeCatalogAssociations(rows) {
  const totals = { AllWISE: 0, "2MASS": 0 };
  const groups = new Map();

  for (const row of rows ?? []) {
    for (const match of catalogAssociationsFor(row)) {
      totals[match.type] += 1;
      if (!match.unique) continue;

      const key = match.type + ":" + match.id;
      groups.set(key, (groups.get(key) ?? 0) + 1);
    }
  }

  const repeatedCounts = [...groups.values()].filter(count => count > 1);

  return {
    allwiseMatches: totals.AllWISE,
    tmassMatches: totals["2MASS"],
    repeatedGroupCount: repeatedCounts.length,
    repeatedDetectionCount: repeatedCounts.reduce((sum, count) => sum + count, 0),
  };
}
