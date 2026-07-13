import { Component, Input, OnChanges } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { ICONS } from './icons.generated';

/**
 * Inline SVG icon (Lucide, self-hosted — CSP-safe, no CDN).
 * Usage: <app-icon name="send" [size]="18" />
 * Inherits color via `stroke="currentColor"`.
 */
@Component({
  selector: 'app-icon',
  standalone: true,
  template: `<svg
    xmlns="http://www.w3.org/2000/svg"
    [attr.width]="size"
    [attr.height]="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    [attr.stroke-width]="strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    [innerHTML]="svgContent"
  ></svg>`,
  styles: [`
    :host { display: inline-flex; align-items: center; justify-content: center; line-height: 0; flex-shrink: 0; }
  `],
})
export class IconComponent implements OnChanges {
  @Input({ required: true }) name!: string;
  @Input() size = 18;
  @Input() strokeWidth = 2;

  svgContent: SafeHtml = '';

  constructor(private sanitizer: DomSanitizer) {}

  ngOnChanges(): void {
    const raw = ICONS[this.name] ?? '';
    // Registry content is our own build-time constant (lucide-static), not user input
    this.svgContent = this.sanitizer.bypassSecurityTrustHtml(raw);
  }
}
