import { ThemeService } from './theme.service';

describe('ThemeService', () => {
  beforeEach(() => {
    localStorage.removeItem('dxc-theme');
    document.body.classList.remove('dark-mode');
  });

  it('defaults to dark mode (product default)', () => {
    const svc = new ThemeService();
    expect(svc.isDark).toBeTrue();
    expect(document.body.classList.contains('dark-mode')).toBeTrue();
  });

  it('restores light mode from localStorage', () => {
    localStorage.setItem('dxc-theme', 'light');
    const svc = new ThemeService();
    expect(svc.isDark).toBeFalse();
    expect(document.body.classList.contains('dark-mode')).toBeFalse();
  });

  it('toggle flips theme and persists it', () => {
    const svc = new ThemeService();  // starts dark
    svc.toggle();
    expect(svc.isDark).toBeFalse();
    expect(localStorage.getItem('dxc-theme')).toBe('light');
    svc.toggle();
    expect(svc.isDark).toBeTrue();
    expect(localStorage.getItem('dxc-theme')).toBe('dark');
  });

  it('setTheme applies an explicit theme', () => {
    const svc = new ThemeService();
    svc.setTheme('dark');
    expect(document.body.classList.contains('dark-mode')).toBeTrue();
    svc.setTheme('light');
    expect(document.body.classList.contains('dark-mode')).toBeFalse();
  });
});
