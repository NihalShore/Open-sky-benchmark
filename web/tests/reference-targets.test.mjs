import test from "node:test";
import assert from "node:assert/strict";

import {
  REFERENCE_TARGET_EPOCH,
  REFERENCE_TARGET_PRESETS,
} from "../reference-targets.mjs";

test("RW Aur preset matches its SIMBAD ICRS J2000 field center", () => {
  assert.equal(REFERENCE_TARGET_EPOCH, "J2000");
  assert.ok(Math.abs(REFERENCE_TARGET_PRESETS.rwAur[0] - 76.9565260346) < 1e-9);
  assert.ok(Math.abs(REFERENCE_TARGET_PRESETS.rwAur[1] - 30.4014381739) < 1e-9);
});

test("R Dra preset matches its SIMBAD ICRS J2000 field center", () => {
  assert.equal(REFERENCE_TARGET_EPOCH, "J2000");
  assert.ok(Math.abs(REFERENCE_TARGET_PRESETS.rDra[0] - 248.1676108330) < 1e-9);
  assert.ok(Math.abs(REFERENCE_TARGET_PRESETS.rDra[1] - 66.7549794172) < 1e-9);
});

test("reference target coordinates satisfy the browser query bounds", () => {
  for (const [ra, dec] of Object.values(REFERENCE_TARGET_PRESETS)) {
    assert.ok(Number.isFinite(ra) && ra >= 0 && ra < 360);
    assert.ok(Number.isFinite(dec) && dec >= -90 && dec <= 90);
  }
});
