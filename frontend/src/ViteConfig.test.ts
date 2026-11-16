import { describe, expect, test } from "vitest";
import { parseAdditionalServerAllowedHosts } from "./viteAllowedHosts";

describe("public Demo Vite allowed hosts", () => {
  test("accepts one or multiple exact TryCloudflare hostnames", () => {
    expect(parseAdditionalServerAllowedHosts("exact-name.trycloudflare.com")).toEqual([
      "exact-name.trycloudflare.com",
    ]);
    expect(parseAdditionalServerAllowedHosts(
      "second.trycloudflare.com, exact-name.trycloudflare.com,second.trycloudflare.com",
    )).toEqual(["exact-name.trycloudflare.com", "second.trycloudflare.com"]);
    expect(parseAdditionalServerAllowedHosts(undefined)).toEqual([]);
  });

  test.each([
    "https://exact-name.trycloudflare.com",
    "exact-name.trycloudflare.com/path",
    "exact-name.trycloudflare.com:443",
    "*.trycloudflare.com",
    ".trycloudflare.com",
    "trycloudflare.com",
    "exact-name.trycloudflare.com.evil.example",
    "example.com",
    "Exact-Name.trycloudflare.com",
    "exact-name.trycloudflare.com,",
  ])("rejects a non-canonical or broad host: %s", (hostname) => {
    expect(() => parseAdditionalServerAllowedHosts(hostname)).toThrow(
      "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS",
    );
  });
});
