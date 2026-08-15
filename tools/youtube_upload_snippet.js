// Run in the YouTube Studio tab (studio.youtube.com/channel/<id>/videos/upload?d=ud) via the browser bridge.
// Fetches a finished build from the CORS-enabled builds branch and hands it to Studio's hidden <input type=file>.
// Usage: set ID = "001-northvolt"; the rest is automatic. Then fill title/description from metadata.json and schedule.
(async () => {
  const ID = window.__NL_ID || "001-northvolt";
  const base = `https://raw.githubusercontent.com/vyrnixsoftware/nordic-ledger/builds/${ID}/`;
  const meta = await (await fetch(base + "metadata.json")).json();
  const blob = await (await fetch(base + "video.mp4")).blob();
  const file = new File([blob], `${ID}.mp4`, { type: "video/mp4" });
  const input = document.querySelector('input[type=file]');
  const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
  input.dispatchEvent(new Event("change", { bubbles: true }));
  window.__NL_META = meta;
  return { title: meta.title, bytes: blob.size, chapters: meta.chapters.length };
})();
