import { Component, OnInit } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { SessionExpiryService } from './services/session-expiry.service';
import { AppearanceService } from './services/appearance.service';

@Component({
  selector: 'app-root',
  standalone: true,
  imports: [RouterOutlet],
  templateUrl: './app.component.html',
  styleUrl: './app.component.scss'
})
export class AppComponent implements OnInit {
  title = 'dxc-copilot-tma';

  constructor(
    private sessionExpiry: SessionExpiryService,
    private appearance: AppearanceService
  ) {}

  ngOnInit(): void {
    this.sessionExpiry.init();
    // Apply persisted admin appearance settings to the live app.
    this.appearance.init();
  }
}
