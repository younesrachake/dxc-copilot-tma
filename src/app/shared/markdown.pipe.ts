import { Pipe, PipeTransform } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

/**
 * Minimal, dependency-free markdown for bot replies.
 * SAFE BY CONSTRUCTION: the input is fully HTML-escaped first; only OUR OWN
 * tags are inserted afterwards, so no user/LLM HTML can ever reach the DOM.
 * Supported: **bold**, *italic*, `inline code`, ### headings, ordered and
 * bullet lists, paragraphs/line breaks.
 */
export function renderMarkdownLite(raw: string): string {
  if (!raw || !raw.trim()) return '';

  // 1) Escape everything
  let s = raw
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

  // 2) Inline styles
  s = s.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  s = s.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/(^|[\s(])\*([^*\n]+)\*(?=[\s).,;:!?]|$)/g, '$1<em>$2</em>');

  // 3) Block structure, line by line
  const lines = s.split('\n');
  const out: string[] = [];
  let listType: 'ol' | 'ul' | null = null;

  const closeList = () => {
    if (listType) { out.push(`</${listType}>`); listType = null; }
  };

  for (const line of lines) {
    const trimmed = line.trim();

    const heading = /^#{1,4}\s+(.*)$/.exec(trimmed);
    const ordered = /^\d+[.)]\s+(.*)$/.exec(trimmed);
    const bullet = /^[-•]\s+(.*)$/.exec(trimmed);

    if (heading) {
      closeList();
      out.push(`<p class="md-h">${heading[1]}</p>`);
    } else if (ordered) {
      if (listType !== 'ol') { closeList(); out.push('<ol>'); listType = 'ol'; }
      out.push(`<li>${ordered[1]}</li>`);
    } else if (bullet) {
      if (listType !== 'ul') { closeList(); out.push('<ul>'); listType = 'ul'; }
      out.push(`<li>${bullet[1]}</li>`);
    } else if (trimmed === '') {
      closeList();
      out.push('<span class="md-gap"></span>');
    } else {
      closeList();
      out.push(`<p>${line}</p>`);
    }
  }
  closeList();
  return out.join('');
}

@Pipe({ name: 'markdownLite', standalone: true })
export class MarkdownLitePipe implements PipeTransform {
  constructor(private sanitizer: DomSanitizer) {}

  transform(value: string | null | undefined): SafeHtml {
    // Safe: renderMarkdownLite escapes all input before inserting our tags
    return this.sanitizer.bypassSecurityTrustHtml(renderMarkdownLite(value ?? ''));
  }
}
