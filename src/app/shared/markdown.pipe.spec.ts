import { renderMarkdownLite } from './markdown.pipe';

describe('renderMarkdownLite', () => {
  it('escapes HTML before applying markdown (XSS-safe)', () => {
    const out = renderMarkdownLite('<script>alert(1)</script>');
    expect(out).not.toContain('<script>');
    expect(out).toContain('&lt;script&gt;');
  });

  it('renders bold and inline code', () => {
    const out = renderMarkdownLite('Voici **important** et `code`.');
    expect(out).toContain('<strong>important</strong>');
    expect(out).toContain('<code>code</code>');
  });

  it('renders ordered lists', () => {
    const out = renderMarkdownLite('1. Première\n2. Deuxième');
    expect(out).toContain('<ol>');
    expect(out).toContain('<li>Première</li>');
    expect(out).toContain('<li>Deuxième</li>');
  });

  it('renders bullet lists', () => {
    const out = renderMarkdownLite('- un\n- deux');
    expect(out).toContain('<ul>');
    expect(out).toContain('<li>un</li>');
  });

  it('renders headings as styled paragraphs', () => {
    const out = renderMarkdownLite('### Titre');
    expect(out).toContain('class="md-h"');
    expect(out).toContain('Titre');
  });

  it('handles empty input safely', () => {
    expect(renderMarkdownLite('')).toBe('');
    expect(renderMarkdownLite(null as any)).toBe('');
  });
});
