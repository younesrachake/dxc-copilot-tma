import { Injectable } from '@angular/core';
import { BehaviorSubject } from 'rxjs';

const EXPIRY_KEY = 'dxc_session_expiry';
/** Access token lifetime in minutes — must match backend ACCESS_TOKEN_EXPIRE_MINUTES */
const TOKEN_LIFETIME_MS = 30 * 60 * 1000;
const WARN_BEFORE_MS = 2 * 60 * 1000;

@Injectable({ providedIn: 'root' })
export class SessionExpiryService {
  private _showWarning$ = new BehaviorSubject<boolean>(false);
  readonly showWarning$ = this._showWarning$.asObservable();

  private warnTimeout: ReturnType<typeof setTimeout> | null = null;
  private expireTimeout: ReturnType<typeof setTimeout> | null = null;

  /** Call this immediately after a successful login. */
  recordLogin(): void {
    const expiresAt = Date.now() + TOKEN_LIFETIME_MS;
    sessionStorage.setItem(EXPIRY_KEY, String(expiresAt));
    this._scheduleWarning(expiresAt);
  }

  /** Call this on app init to re-arm the warning if a session is already active. */
  init(): void {
    const stored = sessionStorage.getItem(EXPIRY_KEY);
    if (!stored) return;
    const expiresAt = Number(stored);
    if (expiresAt > Date.now()) {
      this._scheduleWarning(expiresAt);
    } else {
      sessionStorage.removeItem(EXPIRY_KEY);
    }
  }

  /** Call on logout to cancel timers and clear state. */
  clear(): void {
    sessionStorage.removeItem(EXPIRY_KEY);
    if (this.warnTimeout) { clearTimeout(this.warnTimeout); this.warnTimeout = null; }
    if (this.expireTimeout) { clearTimeout(this.expireTimeout); this.expireTimeout = null; }
    this._showWarning$.next(false);
  }

  dismissWarning(): void {
    this._showWarning$.next(false);
  }

  private _scheduleWarning(expiresAt: number): void {
    if (this.warnTimeout) clearTimeout(this.warnTimeout);
    if (this.expireTimeout) clearTimeout(this.expireTimeout);

    const warnAt = expiresAt - WARN_BEFORE_MS;
    const warnIn = warnAt - Date.now();
    const expireIn = expiresAt - Date.now();

    if (warnIn > 0) {
      this.warnTimeout = setTimeout(() => this._showWarning$.next(true), warnIn);
    } else if (expireIn > 0) {
      // Already in warning window
      this._showWarning$.next(true);
    }

    if (expireIn > 0) {
      this.expireTimeout = setTimeout(() => {
        this._showWarning$.next(false);
        sessionStorage.removeItem(EXPIRY_KEY);
      }, expireIn);
    }
  }
}
