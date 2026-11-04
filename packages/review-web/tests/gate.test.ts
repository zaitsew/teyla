import { test } from "node:test";
import assert from "node:assert/strict";
import { decide, flagIsOn, hostMatches } from "../src/gate.ts";

test("only 1 and true switch the build flag on", () => {
  for (const on of ["1", "true", "TRUE", " 1 ", true, 1]) assert.equal(flagIsOn(on), true, String(on));
  for (const off of [undefined, null, "", "0", "false", "yes", "on", 2, 0, false, {}, []]) assert.equal(flagIsOn(off), false, String(off));
});

test("a host matches exactly, or as a subdomain of a wildcard", () => {
  assert.equal(hostMatches("test.example.com", "test.example.com"), true);
  assert.equal(hostMatches("TEST.example.com.", "test.example.com"), true);
  assert.equal(hostMatches("a.test.example.com", "*.test.example.com"), true);
  assert.equal(hostMatches("a.b.test.example.com", "*.test.example.com"), true);
  assert.equal(hostMatches("test.example.com", "*.test.example.com"), false, "the apex is not a subdomain");
  assert.equal(hostMatches("localhost", "localhost"), true);
  assert.equal(hostMatches("[::1]", "[::1]"), true);
  assert.equal(hostMatches("127.0.0.1", "127.0.0.1"), true);
});

test("a production host never matches a test pattern", () => {
  assert.equal(hostMatches("example.com", "test.example.com"), false);
  assert.equal(hostMatches("www.example.com", "*.test.example.com"), false);
  assert.equal(hostMatches("evil-test.example.com.attacker.io", "*.test.example.com"), false);
  assert.equal(hostMatches("test.example.com.attacker.io", "test.example.com"), false);
  assert.equal(hostMatches("xtest.example.com", "*.test.example.com"), false);
});

test("a bare star, a TLD wildcard, a scheme, a port or a path is not a pattern", () => {
  for (const p of ["*", "*.com", "*.", "", "https://test.example.com", "test.example.com:8080", "test.example.com/app", "*test.example.com", "tes*.example.com"]) {
    assert.equal(hostMatches("test.example.com", p), false, p);
    assert.equal(hostMatches("a.com", p), false, p);
  }
});

test("all three conditions are needed", () => {
  const ok = { flag: "1", hosts: ["test.example.com"], hostname: "test.example.com" };
  assert.deepEqual(decide(ok), { on: true });
  assert.deepEqual(decide({ ...ok, flag: undefined }), { on: false, reason: "flag-off" });
  assert.deepEqual(decide({ ...ok, flag: "0" }), { on: false, reason: "flag-off" });
  assert.deepEqual(decide({ ...ok, hosts: [] }), { on: false, reason: "no-hosts" });
  assert.deepEqual(decide({ ...ok, hosts: undefined }), { on: false, reason: "no-hosts" });
  assert.deepEqual(decide({ ...ok, hostname: "example.com" }), { on: false, reason: "host-not-allowed" });
  assert.deepEqual(decide({ ...ok, hostname: undefined }), { on: false, reason: "no-hostname" });
  assert.deepEqual(decide({ ...ok, hostname: "" }), { on: false, reason: "no-hostname" });
});

test("a flag that is on with a production host stays off", () => {
  assert.equal(decide({ flag: "1", hosts: ["*.test.example.com", "localhost"], hostname: "app.example.com" }).on, false);
});
