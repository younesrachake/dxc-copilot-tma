import { Injectable } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class ThemeService {
  private _isDark = true;

  constructor() {
    // Dark is the product default — light only when explicitly chosen
    const saved = localStorage.getItem('dxc-theme');
    this._isDark = saved !== 'light';
    this.apply();
  }

  get isDark(): boolean { return this._isDark; }

  toggle(): void {
    this._isDark = !this._isDark;
    localStorage.setItem('dxc-theme', this._isDark ? 'dark' : 'light');
    this.apply();
  }

  setTheme(theme: 'light' | 'dark'): void {
    this._isDark = theme === 'dark';
    localStorage.setItem('dxc-theme', theme);
    this.apply();
  }

  private apply(): void {
    document.body.classList.toggle('dark-mode', this._isDark);
  }
}
