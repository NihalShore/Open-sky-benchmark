import test from "node:test";
import assert from "node:assert/strict";
import { HIPS_MAX_TILE,HIPS_ORDER,raDecToHipsTile } from "../healpix.mjs";

test("Norder 5 returns an in-range tile for representative sky positions",()=>{
 for(const [ra,dec] of [[0,0],[127.69444,-39.1776],[133.795,-7.245],[269.452,4.693],[330.84,-56.786],[359.999,89.9],[12.5,-89.9]]){
  const tile=raDecToHipsTile(ra,dec);
  assert.ok(Number.isInteger(tile)&&tile>=0&&tile<=HIPS_MAX_TILE);
 }
 assert.equal(HIPS_ORDER,5);
});
test("right ascension wraps across 360 degrees",()=>{
 assert.equal(raDecToHipsTile(0,12),raDecToHipsTile(360,12));
 assert.equal(raDecToHipsTile(-1,12),raDecToHipsTile(359,12));
});
test("rejects invalid coordinates and unsupported nside",()=>{
 assert.throws(()=>raDecToHipsTile(Number.NaN,0),/finite/);
 assert.throws(()=>raDecToHipsTile(0,91),/Declination/);
 assert.throws(()=>raDecToHipsTile(0,0,3),/power of two/);
});

test("matches the published IRSA SPHEREx Norder 5 reference tile",()=>{
 assert.equal(HIPS_ORDER,5);
 assert.equal(HIPS_MAX_TILE,12287);
 assert.equal(raDecToHipsTile(60.8109955,51.3404038),445);
});
