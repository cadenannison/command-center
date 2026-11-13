import { afterEach, describe, expect, it, vi } from "vitest";
import { downloadText } from "./download";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("downloadText", () => {
  it("clicks a temporary link to a Blob with the file name, then removes it and revokes the URL", async () => {
    vi.useFakeTimers();
    const create = vi.fn<(blob: Blob) => string>(() => "blob:fake");
    const revoke = vi.fn<(url: string) => void>();
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }));
    const clicked: { download: string; href: string; attached: boolean }[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {
      const link = document.querySelector("a[download]");
      if (link instanceof HTMLAnchorElement) {
        clicked.push({ download: link.download, href: link.getAttribute("href") ?? "", attached: true });
      }
    });

    downloadText("a-layout.json", '{"version":1}');

    expect(clicked).toEqual([{ download: "a-layout.json", href: "blob:fake", attached: true }]);
    expect(document.querySelector("a[download]")).toBeNull();
    const blob = create.mock.calls[0]?.[0];
    expect(blob?.type).toBe("application/json");
    expect(await blob?.text()).toBe('{"version":1}');
    expect(revoke).not.toHaveBeenCalled();
    await vi.runAllTimersAsync();
    expect(revoke).toHaveBeenCalledWith("blob:fake");
    vi.unstubAllGlobals();
  });
});
