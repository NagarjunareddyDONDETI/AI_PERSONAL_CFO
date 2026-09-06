import { ReactNode } from "react";

/**
 * Renders the small subset of Markdown that the LLM actually produces:
 * **bold**, *italic*, `code`, bullet and numbered lists, and paragraph breaks.
 *
 * Deliberately hand-rolled rather than react-markdown:
 *
 * - It builds React elements, never HTML strings, so there is no
 *   dangerouslySetInnerHTML anywhere. That matters because this text originates
 *   from an LLM that echoes transaction descriptions — attacker-influenced
 *   content — straight back into the page.
 * - The full CommonMark surface (tables, images, links, HTML blocks) is not
 *   wanted here; supporting it would mean sanitising it.
 *
 * Anything unsupported degrades to plain text rather than showing raw syntax.
 */

// One pass over the inline markers. Order matters: ** before * so bold wins.
const INLINE_PATTERN =
  /(\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*|(?<![A-Za-z0-9])_[^_\n]+_(?![A-Za-z0-9])|`[^`]+`)/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  // Some models escape their own markers ("\*\*120\*\*"); unescape first so the
  // markers are recognised instead of printed.
  const source = text.replace(/\\([*_`])/g, "$1");
  const nodes: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  INLINE_PATTERN.lastIndex = 0;

  while ((match = INLINE_PATTERN.exec(source)) !== null) {
    if (match.index > last) nodes.push(source.slice(last, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${match.index}`;

    if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(
        <strong key={key} className="font-semibold text-white">
          {token.slice(2, -2)}
        </strong>
      );
    } else if (token.startsWith("`")) {
      nodes.push(
        <code
          key={key}
          className="rounded bg-black/40 px-1 py-0.5 font-mono text-[0.92em] text-teal-accent"
        >
          {token.slice(1, -1)}
        </code>
      );
    } else {
      nodes.push(
        <em key={key} className="italic">
          {token.slice(1, -1)}
        </em>
      );
    }
    last = match.index + token.length;
  }
  if (last < source.length) nodes.push(source.slice(last));
  return nodes;
}

type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "ul" | "ol"; items: string[] };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

function toBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  let current: Block | null = null;
  const flush = () => {
    if (current) blocks.push(current);
    current = null;
  };

  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      flush();
      continue;
    }

    const bullet = line.match(BULLET);
    const numbered = line.match(NUMBERED);
    const heading = line.match(HEADING);

    if (bullet) {
      if (current?.kind !== "ul") {
        flush();
        current = { kind: "ul", items: [] };
      }
      (current as { kind: "ul"; items: string[] }).items.push(bullet[1]);
    } else if (numbered) {
      if (current?.kind !== "ol") {
        flush();
        current = { kind: "ol", items: [] };
      }
      (current as { kind: "ol"; items: string[] }).items.push(numbered[1]);
    } else if (heading) {
      // Chat answers do not need real heading levels; treat as an emphasised
      // line so it reads correctly without disrupting the type scale.
      flush();
      blocks.push({ kind: "p", lines: [`**${heading[1]}**`] });
    } else {
      if (current?.kind !== "p") {
        flush();
        current = { kind: "p", lines: [] };
      }
      (current as { kind: "p"; lines: string[] }).lines.push(line);
    }
  }
  flush();
  return blocks;
}

export default function Markdown({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  if (!text?.trim()) return null;
  const blocks = toBlocks(text);

  return (
    <div className={`space-y-2 leading-relaxed ${className}`}>
      {blocks.map((block, bi) => {
        if (block.kind === "p") {
          return (
            <p key={bi}>
              {block.lines.map((line, li) => (
                <span key={li}>
                  {li > 0 && <br />}
                  {renderInline(line, `${bi}-${li}`)}
                </span>
              ))}
            </p>
          );
        }
        const ListTag = block.kind === "ul" ? "ul" : "ol";
        return (
          <ListTag
            key={bi}
            className={`ml-4 space-y-1 ${
              block.kind === "ul" ? "list-disc" : "list-decimal"
            } marker:text-slate-500`}
          >
            {block.items.map((item, ii) => (
              <li key={ii} className="pl-0.5">
                {renderInline(item, `${bi}-${ii}`)}
              </li>
            ))}
          </ListTag>
        );
      })}
    </div>
  );
}

/**
 * Plain-text version, for text-to-speech and anywhere a single line is needed.
 * Without this the voice assistant reads the markers out loud.
 */
export function stripMarkdown(text: string): string {
  return (text || "")
    .replace(/\\([*_`])/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/\*([^*\n]+)\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/^\s*#{1,6}\s+/gm, "")
    .replace(/^\s*[-*•]\s+/gm, "")
    .replace(/^\s*\d+[.)]\s+/gm, "")
    .replace(/\n{2,}/g, ". ")
    .replace(/\s{2,}/g, " ")
    .trim();
}
