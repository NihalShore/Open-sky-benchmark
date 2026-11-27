import test from "node:test";
import assert from "node:assert/strict";

import {
  catalogAssociationsFor,
  passesIrsaQualityScreen,
  summarizeCatalogAssociations,
} from "../neowise.mjs";

const cleanDetection = {
  photometric_quality: "BX",
  frame_quality: 8,
  quality_info_factor: 1,
  saa_separation_deg: 12.5,
  moon_masked: "00",
  contamination_flags: "0000",
  w1_transient_flags: "0000",
  w2_transient_flags: "0000",
};

test("strict IRSA quality screen accepts a good single-band detection", () => {
  assert.equal(passesIrsaQualityScreen(cleanDetection), true);
  assert.equal(passesIrsaQualityScreen({ ...cleanDetection, photometric_quality: "XAXX" }), true);
});

test("strict IRSA quality screen rejects frame, SAA, moon and transient problems", () => {
  for (const row of [
    { ...cleanDetection, frame_quality: 0 },
    { ...cleanDetection, quality_info_factor: 0 },
    { ...cleanDetection, saa_separation_deg: 0 },
    { ...cleanDetection, moon_masked: "10" },
    { ...cleanDetection, contamination_flags: "0P00" },
    { ...cleanDetection, w1_transient_flags: "1000" },
    { ...cleanDetection, w2_transient_flags: "0001" },
    { ...cleanDetection, photometric_quality: "UXXX" },
  ]) {
    assert.equal(passesIrsaQualityScreen(row), false);
  }
});

test("catalog association helper preserves ambiguity and missing separation", () => {
  const matches = catalogAssociationsFor({
    allwise_source_id: 123,
    allwise_match_count: 2,
    allwise_separation_arcsec: 1.2,
    tmass_source_id: 456,
    tmass_match_count: 1,
    tmass_separation_arcsec: null,
  });

  assert.deepEqual(matches, [
    { type: "AllWISE", id: "123", count: 2, separationArcsec: 1.2, unique: false },
    { type: "2MASS", id: "456", count: 1, separationArcsec: null, unique: false },
  ]);
});

test("association summary groups only repeated unique positional matches", () => {
  const rows = [
    { allwise_source_id: 123, allwise_match_count: 1, allwise_separation_arcsec: 1.2 },
    { allwise_source_id: 123, allwise_match_count: 1, allwise_separation_arcsec: 0.8 },
    { allwise_source_id: 789, allwise_match_count: 2, allwise_separation_arcsec: 0.4 },
    { tmass_source_id: 456, tmass_match_count: 1, tmass_separation_arcsec: 0.7 },
    { tmass_source_id: 456, tmass_match_count: 1, tmass_separation_arcsec: 1.1 },
  ];

  assert.deepEqual(summarizeCatalogAssociations(rows), {
    allwiseMatches: 3,
    tmassMatches: 2,
    repeatedGroupCount: 2,
    repeatedDetectionCount: 4,
  });
});
