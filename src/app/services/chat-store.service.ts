import { Injectable } from '@angular/core';
import { BehaviorSubject, Subject } from 'rxjs';

@Injectable({ providedIn: 'root' })
export class ChatStoreService {
  private _activeChatId$ = new BehaviorSubject<number>(0);
  readonly activeChatId$ = this._activeChatId$.asObservable();

  private _activeBackendSessionId$ = new BehaviorSubject<string | null>(null);
  readonly activeBackendSessionId$ = this._activeBackendSessionId$.asObservable();

  private _sessionCreated$ = new Subject<{id: string, title: string}>();
  readonly sessionCreated$ = this._sessionCreated$.asObservable();

  get activeChatId(): number { return this._activeChatId$.getValue(); }
  set activeChatId(id: number) { this._activeChatId$.next(id); }

  /** Select a real backend session by UUID — triggers chat component to load from API. */
  selectBackendSession(sessionId: string): void {
    this._activeBackendSessionId$.next(sessionId);
    this._activeChatId$.next(0);
  }

  /** Clear the active session (new conversation). */
  selectChat(id: number): void {
    this._activeBackendSessionId$.next(null);
    this._activeChatId$.next(id);
  }

  emitSessionCreated(id: string, title: string): void {
    this._sessionCreated$.next({ id, title });
  }

  private _sessionRenamed$ = new Subject<{id: string, title: string}>();
  readonly sessionRenamed$ = this._sessionRenamed$.asObservable();

  /** Backend auto-titled the session — the sidebar patches its history item. */
  emitSessionRenamed(id: string, title: string): void {
    this._sessionRenamed$.next({ id, title });
  }
}
