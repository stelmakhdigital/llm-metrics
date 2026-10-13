/**
 * Минимальный markdown → HTML для превью заметки (вкладка «Note»).
 * Без зависимостей: заголовки, абзацы, списки, цитаты, fenced-code,
 * hr, ссылки, **жирный**, *курсив*, `код`. HTML во входе экранируется
 * (XSS-safe: сначала esc всего текста, разметку добавляем сами);
 * ссылки — только http(s)/mailto/относительные.
 */

const ENTITIES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
};

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ENTITIES[c]);
}

/** href без javascript:/data: схем (содержимое заметки авторим сами, но защита от случайностей). */
function safeHref(url: string): string | null {
  const t = url.trim();
  if (/^(https?:|mailto:|\/|\.\/|#)/i.test(t)) return t;
  return null;
}

/** Инлайн-разметка поверх уже экранированного текста. */
function inline(s: string): string {
  // `код` — сначала вынести, чтобы ** /* не работали внутри
  const codes: string[] = [];
  s = s.replace(/`([^`]+)`/g, (_, c) => {
    codes.push(`<code class="rounded bg-panel2 px-1 py-0.5 font-mono text-xs">${c}</code>`);
    return `\u0000${codes.length - 1}\u0000`;
  });
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong class="font-semibold">$1</strong>');
  s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, '$1<em>$2</em>');
  s = s.replace(
    /\[([^\]]+)\]\(([^)\s]+)\)/g,
    (m, t: string, u: string) => {
      const href = safeHref(u);
      return href
        ? `<a class="text-accent underline underline-offset-2" href="${href}">${t}</a>`
        : m;
    },
  );
  s = s.replace(/\u0000(\d+)\u0000/g, (_, i) => codes[Number(i)]);
  return s;
}

/** Блоки: фенсед-код, цитаты, списки, заголовки, hr, абзацы. */
export function mdToHtml(src: string): string {
  const out: string[] = [];
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  let i = 0;

  const flushParagraph = (buf: string[]) => {
    if (buf.length)
      out.push(
        `<p class="leading-relaxed">${inline(buf.join("<br/>"))}</p>`,
      );
  };
  let para: string[] = [];

  while (i < lines.length) {
    const line = lines[i];

    // fenced code
    if (/^```/.test(line)) {
      flushParagraph(para);
      para = [];
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !/^```/.test(lines[i])) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1; // закрывающий ```
      out.push(
        `<pre class="overflow-x-auto rounded-lg border border-line bg-panel2 p-3 font-mono text-xs">${esc(code.join("\n"))}</pre>`,
      );
      continue;
    }

    // заголовки (до 3 уровней — для заметки достаточно)
    const h = line.match(/^(#{1,3})\s+(.+)$/);
    if (h) {
      flushParagraph(para);
      para = [];
      const cls = [
        "text-lg font-semibold",
        "text-base font-semibold",
        "text-sm font-semibold",
      ][h[1].length - 1];
      out.push(`<h${h[1].length} class="mt-3 mb-1 ${cls}">${inline(h[2])}</h${h[1].length}>`);
      i += 1;
      continue;
    }

    // hr: --- / ***
    if (/^(---+|\*{3,})\s*$/.test(line)) {
      flushParagraph(para);
      para = [];
      out.push('<hr class="my-3 border-line"/>');
      i += 1;
      continue;
    }

    // цитата
    if (/^>\s?/.test(line)) {
      flushParagraph(para);
      para = [];
      const quote: string[] = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        quote.push(lines[i].replace(/^>\s?/, ""));
        i += 1;
      }
      out.push(
        `<blockquote class="border-l-2 border-line pl-3 text-muted">${inline(quote.join("<br/>"))}</blockquote>`,
      );
      continue;
    }

    // списки: «- » / «* » / «1. » (вложенность не поддерживаем — заметке не нужна)
    const ul = line.match(/^\s*[-*]\s+(.+)$/);
    const ol = line.match(/^\s*\d+[.)]\s+(.+)$/);
    if (ul || ol) {
      flushParagraph(para);
      para = [];
      const ordered = Boolean(ol);
      const items: string[] = [];
      while (i < lines.length) {
        const m = lines[i].match(ordered ? /^\s*\d+[.)]\s+(.+)$/ : /^\s*[-*]\s+(.+)$/);
        if (!m) break;
        items.push(m[1]);
        i += 1;
      }
      const cls = ordered
        ? "my-1 list-decimal space-y-1 pl-5"
        : "my-1 list-disc space-y-1 pl-5";
      out.push(
        `<${ordered ? "ol" : "ul"} class="${cls}">${items.map((t) => `<li>${inline(t)}</li>`).join("")}</${ordered ? "ol" : "ul"}>`,
      );
      continue;
    }

    // пустая строка — конец абзаца
    if (/^\s*$/.test(line)) {
      flushParagraph(para);
      para = [];
      i += 1;
      continue;
    }

    para.push(line);
    i += 1;
  }
  flushParagraph(para);
  return out.join("");
}
