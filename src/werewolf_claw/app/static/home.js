/* 首页只做一件事：把聊天页存的夜间模式和字体设置套用过来，
   这样从首页点进聊天页时外观是连贯的。 */

const THEME_KEY = "werewolf-claw-theme";
const FONT_KEY = "werewolf-claw-font";
const FONT_SIZE_KEY = "werewolf-claw-font-size";
const FONT_DB = "werewolf-claw-fonts";
const DEFAULT_FONT = '"Segoe UI", "Microsoft YaHei", system-ui, sans-serif';

function applyTheme() {
  document.body.classList.toggle("dark", localStorage.getItem(THEME_KEY) === "dark");
}

function applyFontSettings() {
  const family = localStorage.getItem(FONT_KEY) || "";
  const size = localStorage.getItem(FONT_SIZE_KEY) || "14";
  document.documentElement.style.setProperty(
    "--chat-font",
    family ? `"${family}", ${DEFAULT_FONT}` : DEFAULT_FONT,
  );
  document.documentElement.style.setProperty("--chat-font-size", `${size}px`);
}

/* 用户导入过的字体存在浏览器本地，首页要用同一个字体就得自己读一次。
   读不到不影响页面，退回系统字体。 */
async function applyStoredFont() {
  const family = localStorage.getItem(FONT_KEY);
  if (!family) {
    return;
  }
  try {
    const record = await new Promise((resolve, reject) => {
      const request = indexedDB.open(FONT_DB, 1);
      request.onupgradeneeded = () => request.result.createObjectStore("fonts", { keyPath: "name" });
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const store = request.result.transaction("fonts", "readonly").objectStore("fonts");
        const get = store.get(family);
        get.onsuccess = () => resolve(get.result);
        get.onerror = () => reject(get.error);
      };
    });
    if (!record) {
      return;
    }
    const face = new FontFace(record.name, record.data);
    await face.load();
    document.fonts.add(face);
  } catch {
    /* 字体读不到就用系统字体，这里不需要提示 */
  }
}

applyTheme();
applyFontSettings();
applyStoredFont();
