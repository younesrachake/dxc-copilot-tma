import { Injectable } from '@angular/core';
import { ApiService } from './api.service';
import { ThemeService } from './theme.service';

/**
 * Applies the admin "Apparence" settings section to the live app.
 *
 * The admin Settings page persists an `appearance` object (theme, colours,
 * font, radius, custom CSS…). On its own that only stores data — this service
 * projects it onto the document so saving actually re-themes the product.
 *
 * Loaded once at app start and re-applied immediately whenever the admin saves
 * the Appearance section (see AdminSettingsComponent.save).
 */
@Injectable({ providedIn: 'root' })
export class AppearanceService {
  private readonly BORDER_RADIUS: Record<string, { sm: string; md: string; lg: string }> = {
    none:   { sm: '0',    md: '0',    lg: '0'    },
    small:  { sm: '4px',  md: '6px',  lg: '8px'  },
    medium: { sm: '6px',  md: '10px', lg: '14px' },
    large:  { sm: '10px', md: '16px', lg: '22px' },
  };

  constructor(private api: ApiService, private theme: ThemeService) {}

  /** Fetch persisted appearance settings and apply them. Best-effort.
   *  Uses the public endpoint so the theme applies to every user, not just admins. */
  init(): void {
    this.api.getPublicAppearance().subscribe({
      next: (res: any) => {
        const a = res?.appearance;
        if (a && Object.keys(a).length) this.apply(a);
      },
      error: () => { /* backend unreachable — leave stylesheet defaults */ }
    });
  }

  /** Apply an appearance settings object to the document, live. */
  apply(a: any): void {
    if (!a || typeof a !== 'object') return;
    const root = document.documentElement;

    // ── Theme ──────────────────────────────────────────────
    if (a.theme === 'light' || a.theme === 'dark') {
      this.theme.setTheme(a.theme);
    } else if (a.theme === 'auto') {
      const prefersDark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;
      this.theme.setTheme(prefersDark ? 'dark' : 'light');
    }

    // ── Accent colours ─────────────────────────────────────
    if (a.primaryColor) {
      root.style.setProperty('--accent', a.primaryColor);
      root.style.setProperty('--accent-ring', this.withAlpha(a.primaryColor, 0.3));
      root.style.setProperty('--accent-soft', this.withAlpha(a.primaryColor, 0.12));
      root.style.setProperty('--dxc-purple', a.primaryColor);
    }
    if (a.secondaryColor) {
      root.style.setProperty('--accent-hover', a.secondaryColor);
      root.style.setProperty('--dxc-purple-light', a.secondaryColor);
    }
    if (a.accentColor) {
      root.style.setProperty('--accent-ink', a.accentColor);
    }

    // ── Typography ─────────────────────────────────────────
    if (a.fontFamily) {
      root.style.setProperty(
        '--font-sans',
        `'${a.fontFamily}', 'InterVariable', 'Segoe UI', system-ui, sans-serif`
      );
    }

    // ── Border radius scale ────────────────────────────────
    const radius = this.BORDER_RADIUS[a.borderRadius];
    if (radius) {
      root.style.setProperty('--radius-sm', radius.sm);
      root.style.setProperty('--radius-md', radius.md);
      root.style.setProperty('--radius-lg', radius.lg);
    }

    // ── Sidebar style ──────────────────────────────────────
    if (a.sidebarStyle === 'light') {
      root.style.setProperty('--sb-bg', '#FFFFFF');
      root.style.setProperty('--sb-ink', '#1A1A24');
      root.style.setProperty('--sb-ink-dim', '#6B6B76');
      root.style.setProperty('--sb-hover', 'rgba(0, 0, 0, 0.05)');
      root.style.setProperty('--sb-border', 'rgba(0, 0, 0, 0.09)');
    } else if (a.sidebarStyle === 'colored') {
      const base = a.primaryColor || '#5F259F';
      root.style.setProperty('--sb-bg', base);
      root.style.setProperty('--sb-ink', '#FFFFFF');
      root.style.setProperty('--sb-ink-dim', 'rgba(255, 255, 255, 0.7)');
      root.style.setProperty('--sb-hover', 'rgba(255, 255, 255, 0.12)');
      root.style.setProperty('--sb-border', 'rgba(255, 255, 255, 0.15)');
    } else if (a.sidebarStyle === 'dark') {
      // Revert to the stylesheet defaults by clearing inline overrides.
      ['--sb-bg', '--sb-ink', '--sb-ink-dim', '--sb-hover', '--sb-border']
        .forEach(v => root.style.removeProperty(v));
    }

    // ── Interface behaviour toggles ────────────────────────
    document.body.classList.toggle('compact-mode', !!a.compactMode);
    document.body.classList.toggle('no-animations', a.animationsEnabled === false);

    // ── Custom CSS injection ───────────────────────────────
    this.applyCustomCss(a.customCss || '');

    // ── Favicon ────────────────────────────────────────────
    if (a.faviconUrl) this.setFavicon(a.faviconUrl);
  }

  private applyCustomCss(css: string): void {
    let el = document.getElementById('dxc-custom-css') as HTMLStyleElement | null;
    if (!css.trim()) {
      if (el) el.remove();
      return;
    }
    if (!el) {
      el = document.createElement('style');
      el.id = 'dxc-custom-css';
      document.head.appendChild(el);
    }
    el.textContent = css;
  }

  private setFavicon(url: string): void {
    let link = document.querySelector<HTMLLinkElement>('link[rel~="icon"]');
    if (!link) {
      link = document.createElement('link');
      link.rel = 'icon';
      document.head.appendChild(link);
    }
    link.href = url;
  }

  /** Convert a #rrggbb hex to an rgba() string with the given alpha. */
  private withAlpha(hex: string, alpha: number): string {
    const m = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex.trim());
    if (!m) return hex;
    const r = parseInt(m[1], 16), g = parseInt(m[2], 16), b = parseInt(m[3], 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
}
