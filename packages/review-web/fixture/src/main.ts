// A product's entry file, as the README tells it: one init call, gated by the build flag.
import { init } from "../../src/index.ts";

void init({
  product: "fixture-app",
  hosts: ["localhost", "127.0.0.1", "*.test.example.com"],
  version: "1.0.0",
  build: "7",
  name: "Fixture",
  speech: true,
});
