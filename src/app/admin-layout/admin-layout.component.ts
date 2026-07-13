import { Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

/**
 * Thin wrapper for the lazy-loaded admin routes.
 * Navigation lives in the ONE main sidebar (LayoutComponent switches to admin
 * mode on /admin/** URLs) — this component intentionally renders no chrome,
 * which removes the old nested double-sidebar.
 */
@Component({
  selector: 'app-admin-layout',
  standalone: true,
  imports: [RouterOutlet],
  template: `<router-outlet></router-outlet>`,
  styles: `
    :host { display: block; height: 100%; }
  `,
})
export class AdminLayoutComponent {}
