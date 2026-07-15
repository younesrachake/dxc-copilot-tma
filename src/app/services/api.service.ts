import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError, BehaviorSubject } from 'rxjs';
import { catchError, tap } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { SessionExpiryService } from './session-expiry.service';

export interface LoginResponse {
  message: string;
  user: { id: number; email: string; full_name?: string };
}

export interface ChatCitation {
  index: number;
  source: string;
  snippet?: string;
}

export interface AgentStep {
  tool: string;
  label: string;
}

export interface ChatApiResponse {
  reply: string;
  session_id: string;
  guide_card?: any;
  sources?: string[];
  jira_ticket?: any;
  citations?: ChatCitation[];
  grounded?: boolean | null;
  intent?: string;
  cached?: boolean;
  session_title?: string | null;
}

export interface ChatStreamHandlers {
  onStatus?: (text: string) => void;
  onToken: (text: string) => void;
  onMeta: (meta: Partial<ChatApiResponse>) => void;
  onAgentStep?: (step: AgentStep) => void;
  onFollowups?: (items: string[]) => void;
  onDone: () => void;
  onError: (message: string) => void;
}

export interface ConversationSearchHit {
  session_id: string;
  session_title: string;
  message_id: number;
  sender: string;
  snippet: string;
  score: number;
}

/** Parse one SSE block ("event: X\ndata: {...}") into {event, data}, or null if empty/invalid. */
export function parseSseBlock(block: string): { event: string; data: any } | null {
  let event = 'message';
  let data = '';
  for (const line of block.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7).trim();
    else if (line.startsWith('data: ')) data += line.slice(6);
  }
  if (!data) return null;
  try {
    return { event, data: JSON.parse(data) };
  } catch {
    return null;
  }
}

export interface RagAnalyticsResponse {
  total_queries: number;
  kb_hit_rate: number;
  avg_top_score: number;
  avg_latency_ms: number;
  routing_breakdown: { kb_primary: number; kb_hint: number; groq_only: number };
  top_docs: { doc_id: string; count: number }[];
}

export interface SessionItem {
  id: string;
  title: string;
  created_at: string;
  updated_at?: string;
}

export interface MessageItem {
  id: number;
  sender: string;
  text: string;
  feedback?: string;
  created_at: string;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private baseUrl = environment.apiUrl;
  private _isAuthenticated$ = new BehaviorSubject<boolean>(false);
  readonly isAuthenticated$ = this._isAuthenticated$.asObservable();

  constructor(private http: HttpClient, private sessionExpiry: SessionExpiryService) {}

  // ── Auth ─────────────────────────────────────────────────
  login(email: string, password: string): Observable<LoginResponse> {
    return this.http.post<LoginResponse>(
      `${this.baseUrl}/api/auth/login`,
      { email, password },
      { withCredentials: true }
    ).pipe(
      tap(() => { this._isAuthenticated$.next(true); this.sessionExpiry.recordLogin(); }),
      catchError(this.handleError)
    );
  }

  logout(): Observable<any> {
    return this.http.post(
      `${this.baseUrl}/api/auth/logout`, {},
      { withCredentials: true }
    ).pipe(
      tap(() => { this._isAuthenticated$.next(false); this.sessionExpiry.clear(); }),
      catchError(this.handleError)
    );
  }

  getUser(): Observable<any> {
    return this.http.get(
      `${this.baseUrl}/api/auth/me`,
      { withCredentials: true }
    ).pipe(catchError(this.handleError));
  }

  // ── Chat ─────────────────────────────────────────────────
  sendMessage(message: string, sessionId?: string, file?: File): Observable<ChatApiResponse> {
    const formData = new FormData();
    formData.append('message', message);
    if (sessionId) formData.append('session_id', sessionId);
    if (file) formData.append('file', file, file.name);

    return this.http.post<ChatApiResponse>(
      `${this.baseUrl}/api/chat`,
      formData,
      { withCredentials: true }
    ).pipe(catchError(this.handleError));
  }

  // ── Chat streaming (SSE over POST — EventSource can't POST) ──
  async streamMessage(message: string, sessionId: string | undefined, handlers: ChatStreamHandlers): Promise<void> {
    const formData = new FormData();
    formData.append('message', message);
    if (sessionId) formData.append('session_id', sessionId);

    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/api/chat/stream`, {
        method: 'POST',
        body: formData,
        credentials: 'include',
      });
    } catch {
      handlers.onError('Impossible de contacter le serveur. Vérifiez votre connexion.');
      return;
    }
    if (!response.ok || !response.body) {
      handlers.onError(response.status === 401
        ? 'Session expirée. Veuillez vous reconnecter.'
        : `Erreur ${response.status}`);
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finished = false;

    const processBlock = (block: string) => {
      const parsed = parseSseBlock(block);
      if (!parsed) return;
      const payload = parsed.data;
      switch (parsed.event) {
        case 'status': handlers.onStatus?.(payload.text || ''); break;
        case 'token': handlers.onToken(payload.text || ''); break;
        case 'agent_step': handlers.onAgentStep?.(payload); break;
        case 'meta': handlers.onMeta(payload); break;
        case 'followups': handlers.onFollowups?.(payload.items || []); break;
        case 'done': finished = true; handlers.onDone(); break;
        case 'error': finished = true; handlers.onError(payload.detail || 'Erreur du serveur'); break;
      }
    };

    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep: number;
        while ((sep = buffer.indexOf('\n\n')) !== -1) {
          processBlock(buffer.slice(0, sep));
          buffer = buffer.slice(sep + 2);
        }
      }
      if (!finished) handlers.onDone();
    } catch {
      if (!finished) handlers.onError('Le flux de réponse a été interrompu.');
    }
  }

  // ── Generic SSE GET stream (admin live events) ───────────
  streamGet(path: string, onEvent: (event: string, data: any) => void): AbortController {
    const controller = new AbortController();
    (async () => {
      try {
        const response = await fetch(`${this.baseUrl}${path}`, {
          credentials: 'include',
          signal: controller.signal,
        });
        if (!response.ok || !response.body) return;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let sep: number;
          while ((sep = buffer.indexOf('\n\n')) !== -1) {
            const parsed = parseSseBlock(buffer.slice(0, sep));
            buffer = buffer.slice(sep + 2);
            if (parsed) onEvent(parsed.event, parsed.data);
          }
        }
      } catch {
        // aborted or network drop — silent (dashboard degrades to manual refresh)
      }
    })();
    return controller;
  }

  // ── PDF downloads (real formatted PDFs) ──────────────────
  async fetchPdf(path: string, payload: any): Promise<Blob> {
    const resp = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) throw new Error(`PDF ${resp.status}`);
    return resp.blob();
  }

  // ── Semantic conversation search ─────────────────────────
  searchConversations(query: string): Observable<{ results: ConversationSearchHit[] }> {
    return this.http.get<{ results: ConversationSearchHit[] }>(
      `${this.baseUrl}/api/chat/search?q=${encodeURIComponent(query)}`,
      { withCredentials: true }
    ).pipe(catchError(this.handleError));
  }

  // ── History ──────────────────────────────────────────────
  getSessions(): Observable<SessionItem[]> {
    return this.http.get<SessionItem[]>(
      `${this.baseUrl}/api/chat/sessions`,
      { withCredentials: true }
    ).pipe(catchError(this.handleError));
  }

  getSessionMessages(sessionId: string): Observable<MessageItem[]> {
    return this.http.get<MessageItem[]>(
      `${this.baseUrl}/api/chat/sessions/${sessionId}/messages`,
      { withCredentials: true }
    ).pipe(catchError(this.handleError));
  }

  deleteSession(sessionId: string): Observable<any> {
    return this.http.delete(
      `${this.baseUrl}/api/chat/sessions/${sessionId}`,
      { withCredentials: true }
    ).pipe(catchError(this.handleError));
  }

  // ── Terminal ─────────────────────────────────────────────
  executeTerminalCommand(command: string): Observable<{ output: string; exit_code: number }> {
    return this.http.post<{ output: string; exit_code: number }>(
      `${this.baseUrl}/api/terminal/execute`,
      { command },
      { withCredentials: true }
    ).pipe(catchError(this.handleError));
  }

  // ── Feedback ─────────────────────────────────────────────
  submitFeedback(messageId: number, rating: string, reason?: string): Observable<any> {
    return this.http.post(
      `${this.baseUrl}/api/feedback`,
      { message_id: messageId, rating, reason },
      { withCredentials: true }
    ).pipe(catchError(this.handleError));
  }

  // ── Admin Dashboard ────────────────────────────────────
  getDashboardStats(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/dashboard`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Admin Analytics ────────────────────────────────────
  getAnalytics(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/analytics`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getRagAnalytics(): Observable<RagAnalyticsResponse> {
    return this.http.get<RagAnalyticsResponse>(`${this.baseUrl}/api/admin/analytics/rag`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Admin AI Insights ──────────────────────────────────
  getKnowledgeGaps(refresh = false): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/knowledge-gaps?refresh=${refresh}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getIncidentClusters(days = 30, refresh = false): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/incident-clusters?days=${days}&refresh=${refresh}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getAnomalies(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/anomalies`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getRoutingThresholds(refresh = false): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/routing-thresholds?refresh=${refresh}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  applyRoutingThresholds(data: any): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/routing-thresholds`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Admin Users CRUD ───────────────────────────────────
  getUsers(): Observable<any[]> {
    return this.http.get<any[]>(`${this.baseUrl}/api/admin/users`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  createUser(data: { name: string; email: string; password: string; role?: string; department?: string }): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/users`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  updateUser(userId: number, data: any): Observable<any> {
    return this.http.put(`${this.baseUrl}/api/admin/users/${userId}`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  deleteUser(userId: number): Observable<any> {
    return this.http.delete(`${this.baseUrl}/api/admin/users/${userId}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  toggleUserStatus(userId: number, status: string): Observable<any> {
    return this.http.patch(`${this.baseUrl}/api/admin/users/${userId}/status`, { status }, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Admin System ───────────────────────────────────────
  getSystemHealth(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/health`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getSystemConfig(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/config`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  updateConfig(data: any): Observable<any> {
    return this.http.put(`${this.baseUrl}/api/admin/config`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  restartService(serviceId: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/restart/${serviceId}`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Admin Logs ─────────────────────────────────────────
  getLogs(lines: number = 50, level?: string, service?: string): Observable<any> {
    let url = `${this.baseUrl}/api/admin/logs?lines=${lines}`;
    if (level) url += `&level=${level}`;
    if (service) url += `&service=${encodeURIComponent(service)}`;
    return this.http.get(url, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  clearLogs(): Observable<any> {
    return this.http.delete(`${this.baseUrl}/api/admin/logs`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Admin Maintenance ──────────────────────────────────
  runBackup(): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/maintenance/backup`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  cleanCache(): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/maintenance/clean-cache`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  optimizeDb(): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/maintenance/optimize-db`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getMaintenanceHealth(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/maintenance/health`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getMaintenanceTasks(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/maintenance/tasks`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  createMaintenanceTask(data: any): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/maintenance/tasks`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  updateMaintenanceTask(id: number, data: any): Observable<any> {
    return this.http.put(`${this.baseUrl}/api/admin/maintenance/tasks/${id}`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  runMaintenanceTask(id: number): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/maintenance/tasks/${id}/run`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  deleteMaintenanceTask(id: number): Observable<any> {
    return this.http.delete(`${this.baseUrl}/api/admin/maintenance/tasks/${id}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Admin Reports ──────────────────────────────────────
  getReportSummary(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/reports/summary`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getReportData(type: string): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/reports/${type}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Audit Log ──────────────────────────────────────────
  getAuditLog(page = 1, pageSize = 50): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/audit-log?page=${page}&page_size=${pageSize}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Admin Settings ─────────────────────────────────────
  getAdminSettings(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/settings`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  saveAdminSettings(section: string, data: any): Observable<any> {
    return this.http.put(`${this.baseUrl}/api/admin/settings/${section}`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  resetAdminSettings(section: string): Observable<any> {
    return this.http.delete(`${this.baseUrl}/api/admin/settings/${section}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  testSmtp(): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/settings/test-smtp`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  testWebhook(): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/settings/test-webhook`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  regenerateApiKey(type: 'public' | 'secret'): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/settings/regenerate-api-key`, { type }, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── User Profile ───────────────────────────────────────
  updateProfile(data: { full_name?: string; department?: string }): Observable<any> {
    return this.http.put(`${this.baseUrl}/api/admin/profile`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  changePassword(currentPassword: string, newPassword: string): Observable<any> {
    return this.http.put(`${this.baseUrl}/api/admin/profile/password`,
      { current_password: currentPassword, new_password: newPassword },
      { withCredentials: true }
    ).pipe(catchError(this.handleError));
  }

  // ── Terminal ───────────────────────────────────────────
  executeCommand(command: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/terminal/execute`, { command }, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Incident Guides ────────────────────────────────────
  getGuides(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/guides`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getDraftGuides(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/guides/drafts`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  createGuide(data: any): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/guides`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  updateGuide(id: number, data: any): Observable<any> {
    return this.http.put(`${this.baseUrl}/api/admin/guides/${id}`, data, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  approveGuide(id: number): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/guides/${id}/approve`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  deleteGuide(id: number): Observable<any> {
    return this.http.delete(`${this.baseUrl}/api/admin/guides/${id}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Jira ───────────────────────────────────────────────
  createJiraTicket(summary: string, description: string, priority?: string): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/jira/ticket`, { summary, description, priority }, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getJiraStatus(ticketKey: string): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/jira/status/${ticketKey}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Knowledge Base ─────────────────────────────────────
  uploadKnowledgeDoc(file: File): Observable<any> {
    const fd = new FormData();
    fd.append('file', file, file.name);
    return this.http.post(`${this.baseUrl}/api/admin/knowledge/upload`, fd, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getKnowledgeDocs(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/knowledge/documents`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  deleteKnowledgeDoc(docId: string): Observable<any> {
    return this.http.delete(`${this.baseUrl}/api/admin/knowledge/documents/${docId}`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  getKnowledgeStats(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/admin/knowledge/stats`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  seedKnowledge(): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/admin/knowledge/seed`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Agent de synchronisation KB ──────────────────────────
  getAgentStatus(): Observable<any> {
    return this.http.get(`${this.baseUrl}/api/agent/status`, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  setAgentFrequency(frequency: string): Observable<any> {
    return this.http.put(`${this.baseUrl}/api/agent/frequency`, { frequency }, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  runAgentNow(): Observable<any> {
    return this.http.post(`${this.baseUrl}/api/agent/run`, {}, { withCredentials: true })
      .pipe(catchError(this.handleError));
  }

  // ── Error handler ────────────────────────────────────────
  private handleError(error: HttpErrorResponse) {
    // FastAPI returns `detail` as a string (HTTPException) or as an array of
    // validation errors (422) — flatten the array to readable French text.
    const rawDetail = error.error?.detail;
    const detail = Array.isArray(rawDetail)
      ? rawDetail
          .map((d: any) => String(d?.msg || '').replace(/^Value error,\s*/i, ''))
          .filter((m: string) => m)
          .join(' — ')
      : (typeof rawDetail === 'string' ? rawDetail : '');

    let message = 'Erreur inconnue';
    if (error.error instanceof ErrorEvent) {
      message = `Erreur réseau: ${error.error.message}`;
    } else if (error.status === 0) {
      message = 'Impossible de contacter le serveur. Vérifiez votre connexion.';
    } else if (error.status === 401) {
      message = 'Session expirée. Veuillez vous reconnecter.';
    } else if (error.status === 400 || error.status === 422) {
      message = detail || 'Requête invalide';
    } else if (error.status === 500) {
      message = 'Erreur serveur. Veuillez réessayer plus tard.';
    } else {
      message = detail || `Erreur ${error.status}`;
    }
    return throwError(() => new Error(message));
  }
}
