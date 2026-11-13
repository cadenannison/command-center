/** Save text as a file through a Blob and a temporary link. Needs no network, so it fits the strict CSP (decision 0301). */
export function downloadText(filename: string, content: string, type = "application/json"): void {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoked on the next turn so the browser has started reading the Blob.
  setTimeout(() => {
    URL.revokeObjectURL(url);
  }, 0);
}
