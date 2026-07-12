import { ThemeService } from './theme.service';

describe('ThemeService', () => {
  beforeEach(() => {
    localStorage.removeItem('dxc-theme');
    document.body.classList.remove('dark-mode');
  });

  it('defaults to light mode', () => {
    const svc = new ThemeService();
    expect(svc.isDark).toBeFalse();
    expect(document.body.classList.contains('dark-mode')).toBeFalse();
  });

  it('restores dark mode from localStorage', () => {
    localStorage.setItem('dxc-theme', 'dark');
    const svc = new ThemeService();
    expect(svc.isDark).toBeTrue();
    expect(document.body.classList.contains('dark-mode')).toBeTrue();
  });

  it('toggle flips theme and persists it', () => {
    const svc = new ThemeService();
    svc.toggle();
    expect(svc.isDark).toBeTrue();
    expect(localStorage.getItem('dxc-theme')).toBe('dark');
    svc.toggle();
    expect(svc.isDark).toBeFalse();
    expect(localStorage.getItem('dxc-theme')).toBe('light');
  });

  it('setTheme applies an explicit theme', () => {
    const svc = new ThemeService();
    svc.setTheme('dark');
    expect(document.body.classList.contains('dark-mode')).toBeTrue();
    svc.setTheme('light');
    expect(document.body.classList.contains('dark-mode')).toBeFalse();
  });
});
