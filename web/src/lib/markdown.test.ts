import { describe, expect, it } from "vitest";
import { mdToHtml } from "./markdown";

describe("mdToHtml", () => {
  it("заголовки h1–h3 с классами", () => {
    expect(mdToHtml("# Титул")).toBe(
      '<h1 class="mt-3 mb-1 text-lg font-semibold">Титул</h1>',
    );
    expect(mdToHtml("## Подзаг.")).toBe(
      '<h2 class="mt-3 mb-1 text-base font-semibold">Подзаг.</h2>',
    );
    expect(mdToHtml("### Мелкий")).toBe(
      '<h3 class="mt-3 mb-1 text-sm font-semibold">Мелкий</h3>',
    );
  });

  it("жирный, курсив и инлайн-код", () => {
    const html = mdToHtml("**жирный** и *курсив* и `код`");
    expect(html).toContain("<strong class=\"font-semibold\">жирный</strong>");
    expect(html).toContain("<em>курсив</em>");
    expect(html).toContain(
      '<code class="rounded bg-panel2 px-1 py-0.5 font-mono text-xs">код</code>',
    );
    // разметка внутри `код` не работает
    const code = mdToHtml("`**не жирный**`");
    expect(code).not.toContain("<strong");
    expect(code).not.toContain("<em");
  });

  it("ссылки: http(s)/mailto/относительные разрешены", () => {
    const http = mdToHtml("[текст](https://example.com/x)");
    expect(http).toBe(
      '<p class="leading-relaxed"><a class="text-accent underline underline-offset-2" href="https://example.com/x">текст</a></p>',
    );
    expect(mdToHtml("[м](mailto:a@b.ru)")).toContain('href="mailto:a@b.ru"');
    expect(mdToHtml("[о](/notes)")).toContain('href="/notes"');
    expect(mdToHtml("[я](./x.md)")).toContain('href="./x.md"');
  });

  it("ссылки: опасные схемы не становятся <a>", () => {
    const html = mdToHtml("[x](javascript:alert(1))");
    expect(html).not.toContain("<a");
    expect(html).not.toContain('href="javascript');
  });

  it("fenced-код: экранирован, без инлайн-разметки", () => {
    const html = mdToHtml("```\n<b>&ok</b>\n```");
    expect(html).toContain(
      '<pre class="overflow-x-auto rounded-lg border border-line bg-panel2 p-3 font-mono text-xs">&lt;b&gt;&amp;ok&lt;/b&gt;</pre>',
    );
  });

  it("списки ul/ol", () => {
    expect(mdToHtml("- раз\n- два")).toBe(
      '<ul class="my-1 list-disc space-y-1 pl-5"><li>раз</li><li>два</li></ul>',
    );
    expect(mdToHtml("1. раз\n2) два")).toBe(
      '<ol class="my-1 list-decimal space-y-1 pl-5"><li>раз</li><li>два</li></ol>',
    );
  });

  it("цитата и hr", () => {
    expect(mdToHtml("> строка")).toBe(
      '<blockquote class="border-l-2 border-line pl-3 text-muted">строка</blockquote>',
    );
    expect(mdToHtml("---")).toBe('<hr class="my-3 border-line"/>');
  });

  it("абзац: строки склеиваются через <br/>, пустые строки разбивают", () => {
    expect(mdToHtml("а\nб\n\nв")).toBe(
      '<p class="leading-relaxed">а<br/>б</p><p class="leading-relaxed">в</p>',
    );
  });

  it("CRLF нормализуется", () => {
    expect(mdToHtml("а\r\nб")).toContain("а<br/>б");
  });
});
