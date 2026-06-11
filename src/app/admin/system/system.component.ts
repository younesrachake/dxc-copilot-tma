import { Component, OnInit } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ApiService } from '../../services/api.service';

@Component({
  selector: 'app-system',
  standalone: true,
  imports: [NgFor, NgIf, FormsModule],
  templateUrl: './system.component.html',
  styleUrl: './system.component.scss'
})
export class SystemComponent implements OnInit {
  // ── Panel state ────────────────────────────────────────────────
  configPanelOpen = false;
  saveSuccess     = false;
  restartingId: string | null = null;
  isLoading = false;

  // ── System info cards ──────────────────────────────────────────
  systemInfo = [
    { label: 'Version Application', value: '—', status: 'success' },
    { label: 'Version Angular',     value: '17.3.0', status: 'success' },
    { label: 'Serveur API',         value: '—', status: 'success' },
    { label: 'Base de données',     value: '—', status: 'success' },
    { label: 'Uptime',              value: '—', status: 'success' },
    { label: 'Dernière sauvegarde', value: '—', status: 'success' }
  ];

  // ── Services ───────────────────────────────────────────────────
  services = [
    { id: 'api-gw',  name: 'API Gateway',       status: 'running', cpu: 0, memory: 0 },
    { id: 'auth',    name: 'Auth Service',       status: 'running', cpu: 0, memory: 0 },
    { id: 'chat',    name: 'Chat Service',       status: 'running', cpu: 0, memory: 0 },
    { id: 'docs',    name: 'Document Service',   status: 'running', cpu: 0, memory: 0 },
    { id: 'analytics', name: 'Analytics Service', status: 'running', cpu: 0, memory: 0 }
  ];

  // ── Configuration model ────────────────────────────────────────
  config = {
    apiBaseUrl:       'https://api.dxc.com',
    apiPort:          443,
    apiTimeout:       30,
    apiMaxRetries:    3,
    dbHost:           'db.dxc.com',
    dbPort:           5432,
    dbName:           'dxc_copilot_prod',
    dbPoolMin:        5,
    dbPoolMax:        50,
    dbSslEnabled:     true,
    redisHost:        'redis.dxc.com',
    redisPort:        6379,
    redisTtl:         3600,
    apiGatewayPort:   8080,
    authServicePort:  8081,
    chatServicePort:  8082,
    docServicePort:   8083,
    analyticsPort:    8084,
    maxUploadMb:      50,
    maxConcurrentReq: 500,
    logLevel:         'info',
    logRetentionDays: 90
  };

  constructor(private router: Router, private api: ApiService) {}

  ngOnInit(): void {
    this.loadSystemData();
  }

  loadSystemData(): void {
    this.isLoading = true;
    this.api.getSystemHealth().subscribe({
      next: (data) => {
        if (data.system_info) {
          this.systemInfo = data.system_info;
        }
        if (data.services) {
          this.services = data.services;
        }
        this.isLoading = false;
      },
      error: () => { this.isLoading = false; }
    });

    this.api.getSystemConfig().subscribe({
      next: (data) => {
        if (data) { Object.assign(this.config, data); }
      }
    });
  }

  goBack(): void {
    this.router.navigate(['/admin']);
  }

  configureSystem(): void {
    this.configPanelOpen = true;
  }

  closePanel(): void {
    this.configPanelOpen = false;
  }

  saveConfig(): void {
    this.api.updateConfig(this.config).subscribe({
      next: () => {
        this.saveSuccess = true;
        setTimeout(() => {
          this.saveSuccess = false;
          this.configPanelOpen = false;
        }, 1800);
      },
      error: () => {
        this.saveSuccess = false;
      }
    });
  }

  restartService(service: any): void {
    this.restartingId = service.id;
    service.status = 'restarting';
    this.api.restartService(service.id).subscribe({
      next: () => {
        service.status = 'running';
        this.restartingId = null;
      },
      error: () => {
        service.status = 'error';
        this.restartingId = null;
      }
    });
  }

  viewLogs(service: any): void {
    this.router.navigate(['/admin/logs']);
  }
}
