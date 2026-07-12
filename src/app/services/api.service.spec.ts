import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule, HttpTestingController } from '@angular/common/http/testing';
import { ApiService, parseSseBlock } from './api.service';
import { environment } from '../../environments/environment';

describe('ApiService', () => {
  let service: ApiService;
  let httpMock: HttpTestingController;
  const base = environment.apiUrl;

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [HttpClientTestingModule],
    });
    service = TestBed.inject(ApiService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => httpMock.verify());

  it('login posts credentials with cookies and flips auth state', (done) => {
    let authState = false;
    service.isAuthenticated$.subscribe(v => authState = v);

    service.login('a@b.com', 'secret').subscribe(res => {
      expect(res.user.email).toBe('a@b.com');
      expect(authState).toBeTrue();
      done();
    });

    const req = httpMock.expectOne(`${base}/api/auth/login`);
    expect(req.request.method).toBe('POST');
    expect(req.request.withCredentials).toBeTrue();
    req.flush({ message: 'ok', user: { id: 1, email: 'a@b.com' } });
  });

  it('sendMessage posts multipart form data', (done) => {
    service.sendMessage('bonjour', 'session-1').subscribe(res => {
      expect(res.reply).toBe('salut');
      done();
    });

    const req = httpMock.expectOne(`${base}/api/chat`);
    expect(req.request.method).toBe('POST');
    const body = req.request.body as FormData;
    expect(body.get('message')).toBe('bonjour');
    expect(body.get('session_id')).toBe('session-1');
    req.flush({ reply: 'salut', session_id: 'session-1' });
  });

  it('searchConversations URL-encodes the query', (done) => {
    service.searchConversations('panne redis & co').subscribe(res => {
      expect(res.results.length).toBe(0);
      done();
    });

    const req = httpMock.expectOne(
      r => r.url.startsWith(`${base}/api/chat/search`)
    );
    expect(req.request.urlWithParams).toContain('panne%20redis%20%26%20co');
    req.flush({ results: [] });
  });

  it('maps 401 errors to a session-expired message', (done) => {
    service.getSessions().subscribe({
      error: (err: Error) => {
        expect(err.message).toContain('Session expirée');
        done();
      }
    });
    httpMock.expectOne(`${base}/api/chat/sessions`)
      .flush({ detail: 'Non authentifié' }, { status: 401, statusText: 'Unauthorized' });
  });

  it('flattens FastAPI 422 validation arrays into readable text', (done) => {
    service.createUser({ name: 'x', email: 'bad', password: 'short' }).subscribe({
      error: (err: Error) => {
        expect(err.message).toContain('mot de passe');
        done();
      }
    });
    httpMock.expectOne(`${base}/api/admin/users`).flush(
      { detail: [{ msg: 'Value error, Le mot de passe doit contenir au moins 12 caractères' }] },
      { status: 422, statusText: 'Unprocessable Entity' }
    );
  });
});

describe('parseSseBlock', () => {
  it('parses a token event', () => {
    const parsed = parseSseBlock('event: token\ndata: {"text": "Bonjour"}');
    expect(parsed).toEqual({ event: 'token', data: { text: 'Bonjour' } });
  });

  it('parses meta events with nested payloads', () => {
    const parsed = parseSseBlock(
      'event: meta\ndata: {"session_id": "s1", "citations": [{"index": 1, "source": "kb"}]}'
    );
    expect(parsed!.event).toBe('meta');
    expect(parsed!.data.citations[0].source).toBe('kb');
  });

  it('returns null for empty or malformed blocks', () => {
    expect(parseSseBlock('')).toBeNull();
    expect(parseSseBlock('event: token')).toBeNull();               // no data
    expect(parseSseBlock('event: token\ndata: not-json')).toBeNull();
  });

  it('defaults event to "message" when only data is present', () => {
    const parsed = parseSseBlock('data: {"x": 1}');
    expect(parsed!.event).toBe('message');
  });
});
