const publicDemoSuffix = ".trycloudflare.com";
const dnsLabel = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;

export function parseAdditionalServerAllowedHosts(raw: string | undefined): string[] {
  if (!raw?.trim()) return [];
  const hosts = new Set<string>();
  for (const entry of raw.split(",")) {
    const hostname = entry.trim();
    const labels = hostname.split(".");
    const prefix = hostname.endsWith(publicDemoSuffix)
      ? hostname.slice(0, -publicDemoSuffix.length)
      : "";
    if (!hostname || hostname.length > 253 || !prefix ||
      !labels.every((label) => dnsLabel.test(label))) {
      throw new Error(
        "__VITE_ADDITIONAL_SERVER_ALLOWED_HOSTS must contain explicit lowercase " +
        "<subdomain>.trycloudflare.com hostnames without scheme, path, port, or wildcard",
      );
    }
    hosts.add(hostname);
  }
  return [...hosts].sort();
}
