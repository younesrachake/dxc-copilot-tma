import { TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { of, throwError, Observable } from 'rxjs';
import { authGuard } from './auth.guard';
import { ApiService } from '../../services/api.service';

describe('authGuard', () => {
  let apiSpy: jasmine.SpyObj<ApiService>;
  let routerSpy: jasmine.SpyObj<Router>;

  beforeEach(() => {
    apiSpy = jasmine.createSpyObj('ApiService', ['getUser']);
    routerSpy = jasmine.createSpyObj('Router', ['navigate']);
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: apiSpy },
        { provide: Router, useValue: routerSpy },
      ],
    });
  });

  function runGuard(): Observable<boolean> {
    return TestBed.runInInjectionContext(() => authGuard({} as any, {} as any)) as Observable<boolean>;
  }

  it('allows navigation when the user is authenticated', (done) => {
    apiSpy.getUser.and.returnValue(of({ id: 1, email: 'a@b.com' }));
    runGuard().subscribe(allowed => {
      expect(allowed).toBeTrue();
      expect(routerSpy.navigate).not.toHaveBeenCalled();
      done();
    });
  });

  it('redirects to /login when the session is invalid', (done) => {
    apiSpy.getUser.and.returnValue(throwError(() => new Error('401')));
    runGuard().subscribe(allowed => {
      expect(allowed).toBeFalse();
      expect(routerSpy.navigate).toHaveBeenCalledWith(['/login']);
      done();
    });
  });
});
